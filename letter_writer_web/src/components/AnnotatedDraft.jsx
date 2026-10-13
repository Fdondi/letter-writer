import React, { useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { splitHighlightedSegments } from "../utils/resolveQuoteSpan";
import { placeFloatingNote } from "../utils/floatingNotePosition";

function hexToRgba(hex, alpha) {
  const m = String(hex || "").match(/^#([0-9a-fA-F]{6})$/);
  if (!m) return `rgba(217, 119, 6, ${alpha})`;
  const n = parseInt(m[1], 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function highlightAlpha(note) {
  return note?.faint ? 0.05 : 0.22;
}

function markStyle(note) {
  const active = Boolean(note) && !note.faint;
  return {
    background: hexToRgba(note.color, highlightAlpha(note)),
    color: "inherit",
    cursor: "pointer",
    borderRadius: 2,
    padding: active ? "0 1px" : 0,
    boxShadow: active ? `0 0 0 1.5px ${note.color}` : "none",
    boxDecorationBreak: "clone",
    WebkitBoxDecorationBreak: "clone",
  };
}

function NoteCard({ note, expanded, onToggle, overlay, children }) {
  const color = note.color;
  return (
    <div
      style={{
        border: `1px solid ${color}`,
        borderLeftWidth: 4,
        borderRadius: 6,
        background: expanded ? "#fff" : hexToRgba(color, 0.08),
        marginTop: overlay ? 0 : 8,
        boxShadow: overlay ? "0 8px 24px rgba(17, 24, 39, 0.22)" : "none",
        maxWidth: overlay ? "100%" : undefined,
        maxHeight: overlay ? "100%" : undefined,
        minHeight: overlay ? 0 : undefined,
        flex: overlay ? 1 : undefined,
        width: overlay ? "100%" : undefined,
        display: overlay ? "flex" : undefined,
        flexDirection: overlay ? "column" : undefined,
        overflow: overlay ? "hidden" : undefined,
        boxSizing: "border-box",
      }}
    >
      <button
        type="button"
        aria-label={overlay ? `Close ${note.title}` : undefined}
        onClick={() => onToggle(note.id)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          textAlign: "left",
          padding: "8px 10px",
          border: "none",
          background: "transparent",
          cursor: "pointer",
          font: "inherit",
          flexShrink: 0,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: color,
            flexShrink: 0,
          }}
        />
        {!overlay && (
          <span style={{ fontSize: 12, fontWeight: 700, color: "#111827" }}>{note.title}</span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 10, color: "#6b7280" }}>
          {expanded ? "▼" : "▶"}
        </span>
      </button>
      {expanded && (
        <div
          style={{
            padding: "0 10px 10px",
            fontSize: 13,
            color: "#111827",
            flex: overlay ? 1 : undefined,
            minHeight: overlay ? 0 : undefined,
            overflow: overlay ? "hidden" : undefined,
            display: overlay ? "flex" : undefined,
            flexDirection: overlay ? "column" : undefined,
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function FloatingNote({ cardRef, children }) {
  const anchorRef = useRef(null);
  const [pos, setPos] = useState(null);

  useLayoutEffect(() => {
    const update = () => {
      const node = anchorRef.current;
      const card = cardRef?.current;
      if (!node || typeof node.getBoundingClientRect !== "function") return;
      const r = node.getBoundingClientRect();
      const cardRect = card && typeof card.getBoundingClientRect === "function"
        ? card.getBoundingClientRect()
        : { left: r.left, width: 320 };
      const next = placeFloatingNote(r, cardRect, 8, {
        height: typeof window !== "undefined" ? window.innerHeight : 0,
      });
      setPos((prev) => {
        if (
          prev
          && prev.top === next.top
          && prev.left === next.left
          && prev.width === next.width
          && prev.maxHeight === next.maxHeight
        ) {
          return prev;
        }
        return next;
      });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [children, cardRef]);

  return (
    <>
      <span ref={anchorRef} data-testid="note-anchor" />
      {pos
        && createPortal(
          <div
            data-testid="inline-note"
            style={{
              position: "fixed",
              top: pos.top,
              left: pos.left,
              width: pos.width,
              maxWidth: pos.width,
              maxHeight: pos.maxHeight != null ? pos.maxHeight : undefined,
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
              overflow: "hidden",
              boxSizing: "border-box",
              zIndex: 11000,
              whiteSpace: "normal",
              lineHeight: 1.45,
            }}
          >
            {children}
          </div>,
          document.body,
        )}
    </>
  );
}

function markerStyle(note) {
  const dealt = Boolean(note.faint);
  return {
    display: "inline-block",
    width: dealt ? 5 : 8,
    height: dealt ? 5 : 8,
    borderRadius: "50%",
    border: dealt ? "none" : "1px solid #fff",
    background: hexToRgba(note.color, dealt ? 0.2 : 1),
    padding: 0,
    marginRight: dealt ? 0 : 3,
    marginLeft: dealt ? -1 : 0,
    position: "relative",
    top: dealt ? 3 : 0,
    verticalAlign: dealt ? "text-bottom" : "middle",
    cursor: "pointer",
  };
}

/**
 * Letter text with quote-anchored notes. Anchored notes appear only in the text;
 * unanchored notes list below. Never both.
 */
export default function AnnotatedDraft({
  text = "",
  notes = [],
  expandedId = null,
  onToggle,
  renderExpanded,
  translationNotice = null,
  minHeight = 220,
}) {
  const anchored = useMemo(
    () => (notes || []).filter((n) => !n.unanchored && n.start != null && n.end != null && n.end > n.start),
    [notes],
  );
  const unanchored = useMemo(
    () => (notes || []).filter((n) => n.unanchored || n.start == null || n.end == null || n.end <= n.start),
    [notes],
  );
  const byId = useMemo(() => {
    const map = new Map();
    for (const n of notes || []) map.set(n.id, n);
    return map;
  }, [notes]);

  const ranges = useMemo(
    () => anchored.map((n) => ({ id: n.id, start: n.start, end: n.end })),
    [anchored],
  );
  const segments = useMemo(
    () => (translationNotice ? [] : splitHighlightedSegments(text, ranges)),
    [text, ranges, translationNotice],
  );

  const startsAt = useMemo(() => {
    const map = new Map();
    for (const n of anchored) {
      const list = map.get(n.start) || [];
      list.push(n);
      map.set(n.start, list);
    }
    return map;
  }, [anchored]);

  const letterBoxRef = useRef(null);

  const expandedAnchored = expandedId && byId.get(expandedId) && !unanchored.some((n) => n.id === expandedId)
    ? byId.get(expandedId)
    : null;

  const handleToggle = (id) => {
    if (!onToggle) return;
    onToggle(expandedId === id ? null : id);
  };

  return (
    <div data-testid="annotated-draft">
      <div
        ref={letterBoxRef}
        data-testid="annotated-letter"
        style={{
          position: "relative",
          overflow: "visible",
          width: "100%",
          minHeight,
          padding: 8,
          border: "1px solid #e5e7eb",
          borderRadius: 4,
          background: "#f9fafb",
          whiteSpace: "pre-wrap",
          fontSize: 13,
          lineHeight: 1.5,
          wordBreak: "break-word",
        }}
      >
        {translationNotice ? (
          <>
            <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 8 }}>{translationNotice}</div>
            {text}
          </>
        ) : (
          segments.map((seg) => {
            const covering = seg.noteIds.map((id) => byId.get(id)).filter(Boolean);
            const primary = covering.find((n) => !n.faint) || covering[0] || null;
            const markers = startsAt.get(seg.start) || [];
            const isQuoteEnd = Boolean(
              expandedAnchored
              && seg.end === expandedAnchored.end
              && seg.noteIds.includes(expandedAnchored.id),
            );
            return (
              <span
                key={`${seg.start}-${seg.end}`}
                style={isQuoteEnd ? { position: "relative" } : undefined}
              >
                {markers.map((n) => (
                  <button
                    key={`m-${n.id}`}
                    type="button"
                    title={n.title}
                    aria-label={n.title}
                    data-testid={`note-marker-${n.id}`}
                    data-dealt={n.faint ? "true" : "false"}
                    data-inactive-reason={n.inactiveReason || undefined}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleToggle(n.id);
                    }}
                    style={markerStyle(n)}
                  />
                ))}
                {primary ? (
                  <mark
                    data-note-id={primary.id}
                    data-active={primary.faint ? "false" : "true"}
                    onClick={() => handleToggle(primary.id)}
                    style={markStyle(primary)}
                  >
                    {seg.text}
                  </mark>
                ) : (
                  seg.text
                )}
                {isQuoteEnd && (
                  <FloatingNote cardRef={letterBoxRef}>
                    <NoteCard
                      note={expandedAnchored}
                      expanded
                      overlay
                      onToggle={handleToggle}
                    >
                      {renderExpanded ? renderExpanded(expandedAnchored) : expandedAnchored.body}
                    </NoteCard>
                  </FloatingNote>
                )}
              </span>
            );
          })
        )}
      </div>

      {unanchored.length > 0 && (
        <div data-testid="unanchored-notes" style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 4 }}>
            Notes on the letter as a whole
          </div>
          {unanchored.map((note) => (
            <NoteCard
              key={note.id}
              note={note}
              expanded={expandedId === note.id}
              onToggle={handleToggle}
            >
              {renderExpanded ? renderExpanded(note) : note.body}
            </NoteCard>
          ))}
        </div>
      )}
    </div>
  );
}
