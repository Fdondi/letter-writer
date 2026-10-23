import React, { useMemo, useState } from "react";
import { useDrag } from "react-dnd";
import AnnotatedDraft from "../AnnotatedDraft";
import { ItemTypes } from "../../constants";
import { resolveQuoteSpan } from "../../utils/resolveQuoteSpan";
import { feedbackTopicLabel, vendorNoteColor, vendorNoteTitle } from "../../constants/feedbackTopics";
import { feedbackItems, isStrongNote, PARAGRAPH_FEEDBACK_TOPICS } from "../../utils/paragraphFlow";

const smallButton = {
  padding: "3px 8px",
  fontSize: 12,
  border: "1px solid var(--border-color)",
  borderRadius: 4,
  background: "var(--button-bg)",
  color: "var(--button-text)",
  cursor: "pointer",
};

/**
 * One paragraph option: text with faint/strong feedback notes (never blocking),
 * Use / drag into the letter, Discard, and Regenerate with optional feedback.
 */
export default function ParagraphOptionCard({
  paragraph,
  vendor,
  color,
  used = false,
  vendors = [],
  regenerating = false,
  onUse,
  onDiscard,
  onRestore,
  onRegenerate,
  onRetryFeedback,
}) {
  const [expandedNoteId, setExpandedNoteId] = useState(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [userFeedback, setUserFeedback] = useState("");
  const [pickedNoteIds, setPickedNoteIds] = useState([]);
  const [regenVendor, setRegenVendor] = useState(paragraph.vendor || vendor);

  const discarded = paragraph.status === "discarded";
  const items = useMemo(() => feedbackItems(paragraph), [paragraph]);
  const strongCount = items.filter(isStrongNote).length;
  const pending = paragraph.feedbackPending || [];
  const failedTopics = Object.keys(paragraph.feedbackErrors || {});

  const notes = useMemo(
    () =>
      items.map((it) => {
        const span = paragraph.text ? resolveQuoteSpan(paragraph.text, it.quote, it.matched_text) : null;
        return {
          id: it.id,
          categoryKey: it.topic,
          title: vendorNoteTitle(it.type, it.topic),
          color: vendorNoteColor(it.topic),
          faint: !isStrongNote(it),
          start: span?.start,
          end: span?.end,
          unanchored: !span,
          body: it.observation,
          item: it,
        };
      }),
    [items, paragraph.text],
  );

  const [{ isDragging }, drag] = useDrag(
    () => ({
      type: ItemTypes.PARAGRAPH,
      item: () => ({
        paragraph: { id: paragraph.id, sourceId: paragraph.id, text: paragraph.text, vendor: paragraph.vendor || vendor },
        index: -1,
        isFromFinalColumn: false,
      }),
      canDrag: !discarded && !feedbackOpen,
      collect: (monitor) => ({ isDragging: monitor.isDragging() }),
    }),
    [paragraph.id, paragraph.text, paragraph.vendor, vendor, discarded, feedbackOpen],
  );

  const togglePicked = (id) =>
    setPickedNoteIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const addNoteToFeedback = (note) => {
    setFeedbackOpen(true);
    if (!pickedNoteIds.includes(note.id)) setPickedNoteIds((prev) => [...prev, note.id]);
  };

  const submitRegenerate = () => {
    const aiNotes = items
      .filter((it) => pickedNoteIds.includes(it.id))
      .map((it) => ({ id: it.id, topic: it.topic, observation: it.observation, quote: it.quote || "" }));
    onRegenerate?.({ userFeedback: userFeedback.trim(), aiNotes, vendor: regenVendor });
    setFeedbackOpen(false);
    setUserFeedback("");
    setPickedNoteIds([]);
  };

  if (discarded) {
    return (
      <div
        data-testid={`paragraph-option-${paragraph.id}`}
        data-status="discarded"
        style={{ padding: "6px 8px", border: "1px dashed var(--border-color)", borderRadius: 6, fontSize: 12, color: "var(--secondary-text-color)", display: "flex", gap: 8, alignItems: "center" }}
      >
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          Discarded: {paragraph.text}
        </span>
        <button type="button" style={smallButton} onClick={() => onRestore?.()}>Undo</button>
      </div>
    );
  }

  return (
    <div
      ref={drag}
      data-testid={`paragraph-option-${paragraph.id}`}
      data-status={paragraph.status}
      data-strong-notes={strongCount}
      style={{
        border: `1px solid ${used ? color || "var(--border-color)" : "var(--border-color)"}`,
        borderLeft: `4px solid ${color || "var(--border-color)"}`,
        borderRadius: 6,
        padding: 8,
        background: "var(--card-bg)",
        opacity: isDragging ? 0.5 : 1,
        cursor: "grab",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, fontSize: 12, flexWrap: "wrap" }}>
        {paragraph.parentId && (
          <span title={paragraph.userFeedback ? `Feedback: ${paragraph.userFeedback}` : "Regenerated"} style={{ color: "var(--secondary-text-color)" }}>
            ↻ {paragraph.vendor || vendor}
          </span>
        )}
        <span
          data-testid="strong-note-count"
          title="Suggested fixes (not blocking)"
          style={{
            padding: "1px 6px",
            borderRadius: 999,
            background: strongCount ? "rgba(220, 38, 38, 0.12)" : "rgba(13, 148, 136, 0.12)",
            color: strongCount ? "#b91c1c" : "#0f766e",
            fontWeight: 600,
          }}
        >
          {strongCount ? `${strongCount} to consider` : "no fixes"}
        </span>
        {pending.length > 0 && (
          <span title={`Checking: ${pending.map(feedbackTopicLabel).join(", ")}`} style={{ color: "var(--secondary-text-color)" }}>
            checking {PARAGRAPH_FEEDBACK_TOPICS.length - pending.length}/{PARAGRAPH_FEEDBACK_TOPICS.length}…
          </span>
        )}
        {failedTopics.length > 0 && pending.length === 0 && (
          <button
            type="button"
            style={{ ...smallButton, padding: "1px 6px", fontSize: 11 }}
            title={failedTopics.map((t) => `${feedbackTopicLabel(t)}: ${paragraph.feedbackErrors[t]}`).join("\n")}
            onClick={() => onRetryFeedback?.(failedTopics)}
          >
            retry {failedTopics.length} check{failedTopics.length > 1 ? "s" : ""}
          </button>
        )}
        {used && <span style={{ marginLeft: "auto", color: "var(--secondary-text-color)" }}>in letter</span>}
      </div>

      <AnnotatedDraft
        text={paragraph.text}
        notes={notes}
        expandedId={expandedNoteId}
        onToggle={setExpandedNoteId}
        minHeight={0}
        renderExpanded={(note) => (
          <div style={{ fontSize: 12 }}>
            <div style={{ whiteSpace: "pre-wrap" }}>{note.body}</div>
            {!note.faint && (
              <button type="button" style={{ ...smallButton, marginTop: 6 }} onClick={() => addNoteToFeedback(note)}>
                + Add to regenerate feedback
              </button>
            )}
          </div>
        )}
      />

      <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
        <button type="button" data-testid="paragraph-use" style={{ ...smallButton, fontWeight: 600 }} onClick={() => onUse?.()}>
          Use
        </button>
        <button type="button" data-testid="paragraph-discard" style={smallButton} onClick={() => onDiscard?.()}>
          Discard
        </button>
        <button
          type="button"
          data-testid="paragraph-feedback-toggle"
          style={smallButton}
          disabled={regenerating}
          onClick={() => setFeedbackOpen((v) => !v)}
        >
          {regenerating ? "Regenerating…" : feedbackOpen ? "Feedback ▾" : "Feedback ▸"}
        </button>
      </div>

      {feedbackOpen && (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
          <textarea
            data-testid="paragraph-feedback-text"
            value={userFeedback}
            onChange={(e) => setUserFeedback(e.target.value)}
            placeholder="What should change? (optional: leave empty for a fresh alternative)"
            rows={3}
            style={{ width: "100%", boxSizing: "border-box", fontSize: 12, padding: 6, borderRadius: 4, border: "1px solid var(--border-color)", background: "var(--bg-color)", color: "var(--text-color)" }}
          />
          {items.filter(isStrongNote).length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 12 }}>
              {items.filter(isStrongNote).map((it) => (
                <label key={it.id} style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                  <input type="checkbox" checked={pickedNoteIds.includes(it.id)} onChange={() => togglePicked(it.id)} />
                  <span>
                    <strong style={{ color: vendorNoteColor(it.topic) }}>{feedbackTopicLabel(it.topic)}:</strong> {it.observation}
                  </span>
                </label>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            {vendors.length > 1 && (
              <select
                aria-label="Vendor for regeneration"
                value={regenVendor}
                onChange={(e) => setRegenVendor(e.target.value)}
                style={{ fontSize: 12, padding: "2px 4px" }}
              >
                {vendors.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            )}
            <button type="button" data-testid="paragraph-regenerate" style={{ ...smallButton, fontWeight: 600 }} onClick={submitRegenerate}>
              Regenerate
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
