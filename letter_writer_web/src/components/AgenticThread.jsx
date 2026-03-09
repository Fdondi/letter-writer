/**
 * Renders one topic's feedback thread: comments with subcomments, addendums, and vote counts.
 * When canEdit, shows Edit and Remove so user can adjust feedback before Refine.
 * Block color = author vendor (same palette as assembly). Shapes: root = speech bubble, addendum = red +, subcomment = thought bubble.
 * Status color (done/active) is only used for the status badge at the top.
 */
import React, { useEffect, useState } from "react";
import LanguageSelector from "./LanguageSelector";

// Opacity by level so hierarchy is clear; hue comes from vendor color.
const ROOT_OPACITY = 0.55;
const ADDENDUM_OPACITY = 0.35;
const SUBCOMMENT_OPACITY = 0.18;

/** Parse hsl(H, S%, L%) or #rrggbb to "r, g, b" for rgba(). Falls back to neutral if invalid. */
function colorToRgbString(color) {
  if (!color || typeof color !== "string") return "120, 120, 120";
  const hex = color.match(/^#([0-9a-fA-F]{6})$/);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
  }
  const hsl = color.match(/hsl\(\s*(\d+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)/);
  if (!hsl) return "120, 120, 120";
  const h = Number(hsl[1]) / 360;
  const s = Number(hsl[2]) / 100;
  const l = Number(hsl[3]) / 100;
  let r, g, b;
  if (s === 0) {
    r = g = b = l;
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }
  return `${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}`;
}
function hue2rgb(p, q, t) {
  if (t < 0) t += 1;
  if (t > 1) t -= 1;
  if (t < 1 / 6) return p + (q - p) * 6 * t;
  if (t < 1 / 2) return q;
  if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
  return p;
}

const topicLabels = {
  instruction: "Instruction",
  accuracy: "CV accuracy",
  precision: "Precision",
  company_fit: "Company fit",
  user_fit: "User fit",
  human: "Human",
};

function topicStatusLabel(meta) {
  if (!meta) return null;
  if (meta.done) return "Done";
  return "Active";
}

function topicStatusColor(meta) {
  if (!meta) return "var(--secondary-text-color)";
  if (meta.done) return "#16a34a";
  return "#0d9488";
}

/** Renders a translation bar above and translated content. Used for addendums and subcomments.
 * leftSlot: optional content to show on the left of the bar (e.g. Edit/Remove) so it doesn't overlap the language selector. */
function TranslatableSlice({ translation, fieldId, sourceText, render, leftSlot }) {
  useEffect(() => {
    if (translation && fieldId) translation.resetFieldTranslation(fieldId, sourceText);
  }, [sourceText, fieldId, translation]);

  const displayedText = translation && fieldId
    ? translation.getTranslatedText(fieldId, sourceText)
    : sourceText;
  const viewLanguage = translation && fieldId ? translation.getFieldViewLanguage(fieldId) : "source";

  const handleLanguageChange = async (code) => {
    if (!translation || !fieldId) return;
    translation.setFieldViewLanguage(fieldId, code);
    if (code === "source") return;
    if (sourceText) await translation.translateField(fieldId, sourceText, code);
  };

  if (!translation || !fieldId) {
    if (leftSlot && render) {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
          <div style={{ display: "flex", justifyContent: "flex-start", alignItems: "center", marginBottom: 2 }}>
            {leftSlot}
          </div>
          {render(sourceText)}
        </div>
      );
    }
    return render ? render(sourceText) : sourceText;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}>
      <div
        style={{
          display: "flex",
          justifyContent: leftSlot ? "space-between" : "flex-end",
          alignItems: "center",
          marginBottom: 2,
          gap: 8,
        }}
      >
        {leftSlot ?? null}
        <LanguageSelector
          languages={translation.languages}
          viewLanguage={viewLanguage}
          onLanguageChange={handleLanguageChange}
          hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
          isTranslating={translation.isTranslating[fieldId] || false}
          size="tiny"
        />
      </div>
      {render ? render(displayedText) : displayedText}
    </div>
  );
}

export default function AgenticThread({
  topic,
  thread = [],
  topicMeta,
  description,
  vendorColors = {},
  translation,
  canEdit = false,
  canSuspend = false,
  canResume = false,
  onSuspend,
  onResume,
  onAddRound,
  addRoundLoading = false,
  onRemoveComment,
  onReinstateComment,
  onEditComment,
  onRemoveAddendum,
  onEditAddendum,
}) {
  const label = topicLabels[topic] || topic;
  const meta = topicMeta || {};
  const statusLabel = topicStatusLabel(meta);
  const visibleThreadEntries = (thread || [])
    .map((comment, index) => ({ comment, index }))
    .filter(({ comment }) => !comment?.carried);
  const messages = meta.messages ?? visibleThreadEntries.length;
  const turns = meta.round ?? 0;

  return (
    <div
      style={{
        padding: 12,
        backgroundColor: "var(--panel-bg)",
        border: "1px solid var(--border-color)",
        borderRadius: 8,
        minHeight: 120,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 8,
          marginBottom: 6,
          flexWrap: "wrap",
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-color)" }}>{label}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {statusLabel != null && (
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: topicStatusColor(meta),
                textTransform: "uppercase",
              }}
            >
              {statusLabel}
            </span>
          )}
          <span style={{ fontSize: 11, color: "var(--secondary-text-color)" }}>
            {messages} msg{messages !== 1 ? "s" : ""} · {turns} turn{turns !== 1 ? "s" : ""}
          </span>
          {onAddRound && (
            <button
              type="button"
              onClick={onAddRound}
              disabled={addRoundLoading}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                cursor: addRoundLoading ? "not-allowed" : "pointer",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--bg-color)",
                color: "var(--text-color)",
              }}
              title="Add one more round for this topic"
            >
              +1 round
            </button>
          )}
          {canSuspend && onSuspend && (
            <button
              type="button"
              onClick={onSuspend}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                cursor: "pointer",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--bg-color)",
                color: "var(--text-color)",
              }}
            >
              Suspend
            </button>
          )}
          {canResume && onResume && (
            <button
              type="button"
              onClick={onResume}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                cursor: "pointer",
                border: "none",
                borderRadius: 4,
                background: "#0d9488",
                color: "white",
              }}
            >
              Resume
            </button>
          )}
        </div>
      </div>
      {description && (
        <div
          style={{
            fontSize: 11,
            color: "var(--secondary-text-color)",
            marginBottom: 8,
          }}
        >
          {description}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {visibleThreadEntries.length === 0 ? (
          <div
            style={{
              fontSize: 12,
              color: "var(--secondary-text-color)",
              fontStyle: "italic",
            }}
          >
            No comments yet.
          </div>
        ) : (
          visibleThreadEntries.map(({ comment, index }) => (
            <CommentBlock
              key={comment.id || comment.text?.slice(0, 20) || index}
              comment={comment}
              commentIndex={index}
              topic={topic}
              fieldId={translation ? `agentic_${topic}_${index}` : null}
              vendorColors={vendorColors}
              translation={translation}
              canEdit={canEdit}
              onRemove={() => onRemoveComment?.(topic, index)}
              onReinstate={() => onReinstateComment?.(topic, index)}
              onEdit={(newText) => onEditComment?.(topic, index, newText)}
              onRemoveAddendum={onRemoveAddendum ? (addendumIndex) => onRemoveAddendum(topic, index, addendumIndex) : undefined}
              onEditAddendum={onEditAddendum ? (addendumIndex, newText) => onEditAddendum(topic, index, addendumIndex, newText) : undefined}
            />
          ))
        )}
      </div>
    </div>
  );
}

function CommentBlock({ comment, commentIndex, topic, fieldId, vendorColors, translation, canEdit, onRemove, onReinstate, onEdit, onRemoveAddendum, onEditAddendum }) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(comment.text || "");
  const [collapsed, setCollapsed] = useState(false); // top-level comment starts open
  const [subcommentsCollapsed, setSubcommentsCollapsed] = useState(true); // subcomment thread starts collapsed
  const [addendumEditingIndex, setAddendumEditingIndex] = useState(null);
  const [addendumEditText, setAddendumEditText] = useState("");
  const up = (comment.votes && comment.votes.up) || [];
  const down = (comment.votes && comment.votes.down) || [];
  const abstain = (comment.votes && comment.votes.abstain) || [];
  const net = up.length - down.length;
  const removed = Boolean(comment.removed) || down.length > 0;
  const votesByRoundRaw = comment.votes_by_round && typeof comment.votes_by_round === "object"
    ? comment.votes_by_round
    : null;
  const roundVoteRows = votesByRoundRaw
    ? Object.entries(votesByRoundRaw)
        .map(([roundKey, data]) => {
          const roundNum = Number(roundKey);
          const upList = Array.isArray(data?.up) ? data.up : [];
          const downList = Array.isArray(data?.down) ? data.down : [];
          const abstainList = Array.isArray(data?.abstain) ? data.abstain : [];
          const reasons = data?.reasons && typeof data.reasons === "object" ? data.reasons : {};
          return { round: Number.isFinite(roundNum) ? roundNum : roundKey, upList, downList, abstainList, reasons };
        })
        .sort((a, b) => Number(a.round) - Number(b.round))
    : [{
        round: Number(comment.created_round) || 1,
        upList: up,
        downList: down,
        abstainList: abstain,
        reasons: {},
      }];

  const rootRgb = colorToRgbString(vendorColors[comment.vendor] || null);
  const sourceText = comment.text || "";
  const subcomments = comment.subcomments || [];
  const subcommentCount = subcomments.length;

  useEffect(() => {
    if (translation && fieldId) translation.resetFieldTranslation(fieldId, sourceText);
  }, [sourceText, fieldId, translation]);

  const displayedText = translation && fieldId
    ? translation.getTranslatedText(fieldId, sourceText)
    : sourceText;
  const viewLanguage = translation && fieldId ? translation.getFieldViewLanguage(fieldId) : "source";

  const handleLanguageChange = async (code) => {
    if (!translation || !fieldId) return;
    translation.setFieldViewLanguage(fieldId, code);
    if (code === "source") return;
    if (sourceText) await translation.translateField(fieldId, sourceText, code);
  };

  const handleSaveEdit = () => {
    if (editText.trim() !== (comment.text || "").trim()) onEdit?.(editText.trim() || comment.text);
    setEditing(false);
  };

  return (
    <div
      style={{
        position: "relative",
        padding: 8,
        backgroundColor: `rgba(${rootRgb}, ${ROOT_OPACITY})`,
        border: "1px solid var(--border-color)",
        borderRadius: 10,
        marginLeft: 10,
        opacity: removed ? 0.75 : 1,
      }}
    >
      {/* Speech bubble tail (downward, below box for full lateral space) */}
      <div
        style={{
          position: "absolute",
          left: 20,
          bottom: -8,
          width: 0,
          height: 0,
          borderLeft: "8px solid transparent",
          borderRight: "8px solid transparent",
          borderTop: `8px solid rgba(${rootRgb}, ${ROOT_OPACITY})`,
        }}
      />
      <div
        style={{
          fontSize: 11,
          color: "var(--secondary-text-color)",
          marginBottom: collapsed ? 0 : 4,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: 0,
            border: "none",
            background: "none",
            cursor: "pointer",
            color: "inherit",
            font: "inherit",
          }}
          title={collapsed ? "Expand comment" : "Collapse comment"}
        >
          <span style={{ fontSize: 10 }}>{collapsed ? "▶" : "▼"}</span>
          <span>{comment.vendor}</span>
          {comment.carried_from_topic && (
            <span style={{ fontSize: 10, opacity: 0.8 }}>
              from {topicLabels[comment.carried_from_topic] || comment.carried_from_topic}
            </span>
          )}
          {removed && (
            <span style={{ fontSize: 10, color: "#dc2626", fontWeight: 700 }}>
              REMOVED
            </span>
          )}
        </button>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {!editing && translation && fieldId && (
            <LanguageSelector
              languages={translation.languages}
              viewLanguage={viewLanguage}
              onLanguageChange={handleLanguageChange}
              hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
              isTranslating={translation.isTranslating[fieldId] || false}
              size="tiny"
            />
          )}
          {canEdit && (
            <>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); if (editing) handleSaveEdit(); else { setCollapsed(false); setEditing(true); } }}
              title={editing ? "Save" : "Edit"}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                padding: "4px",
                cursor: "pointer",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--panel-bg)",
                color: "var(--text-color)",
              }}
            >
              {editing ? (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden><polyline points="20 6 9 17 4 12" /></svg>
              ) : (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
              )}
            </button>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onRemove?.(); }}
              title={removed ? "Keep removed" : "Remove"}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                padding: "4px",
                cursor: removed ? "not-allowed" : "pointer",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "#fef2f2",
                color: "#b91c1c",
              }}
              disabled={removed}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
            </button>
            {removed && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onReinstate?.(); }}
                title="Reinstate comment"
                style={{
                  fontSize: 11,
                  padding: "2px 6px",
                  cursor: "pointer",
                  border: "1px solid #16a34a",
                  borderRadius: 4,
                  background: "#dcfce7",
                  color: "#166534",
                }}
              >
                Reinstate
              </button>
            )}
            </>
          )}
        </span>
      </div>
      {!collapsed && (
        <>
      {editing ? (
        <textarea
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onBlur={handleSaveEdit}
          style={{
            width: "100%",
            minHeight: 80,
            fontSize: 13,
            padding: 6,
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            resize: "vertical",
            fontFamily: "inherit",
          }}
        />
      ) : (
        <div
          style={{
            fontSize: 13,
            color: "var(--text-color)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {displayedText}
        </div>
      )}
      {(comment.addendums || []).length > 0 && (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
          {(comment.addendums || []).map((a, i) => {
            const addendumUpList = (a.up && Array.isArray(a.up)) ? a.up : [];
            const addendumDownList = (a.down && Array.isArray(a.down)) ? a.down : [];
            const addendumUp = addendumUpList.length;
            const addendumDown = addendumDownList.length;
            const addendumVoteTooltip = [
              addendumUp ? `Up: ${addendumUpList.join(", ")}` : null,
              addendumDown ? `Down: ${addendumDownList.join(", ")}` : null,
            ].filter(Boolean).join(". ") || "No votes yet";
            const addendumRgb = colorToRgbString(vendorColors[a.vendor] || null);
            const addendumFieldId = fieldId ? `${fieldId}_addendum_${i}` : null;
            const isEditingAddendum = addendumEditingIndex === i;
            const handleSaveAddendumEdit = () => {
              if ((addendumEditText || "").trim() !== (a.text || "").trim()) {
                onEditAddendum?.(i, (addendumEditText || "").trim() || a.text);
              }
              setAddendumEditingIndex(null);
            };
            const addendumLeftSlot = canEdit && (onRemoveAddendum || onEditAddendum) ? (
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isEditingAddendum) handleSaveAddendumEdit();
                    else {
                      setAddendumEditingIndex(i);
                      setAddendumEditText(a.text || "");
                    }
                  }}
                  title={isEditingAddendum ? "Save" : "Edit addendum"}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "4px",
                    cursor: "pointer",
                    border: "1px solid var(--border-color)",
                    borderRadius: 4,
                    background: "var(--panel-bg)",
                    color: "var(--text-color)",
                  }}
                >
                  {isEditingAddendum ? (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden><polyline points="20 6 9 17 4 12" /></svg>
                  ) : (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                  )}
                </button>
                {onRemoveAddendum && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemoveAddendum(i);
                      if (addendumEditingIndex === i) setAddendumEditingIndex(null);
                    }}
                    title="Remove addendum"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: "4px",
                      cursor: "pointer",
                      border: "1px solid var(--border-color)",
                      borderRadius: 4,
                      background: "#fef2f2",
                      color: "#b91c1c",
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
                  </button>
                )}
              </span>
            ) : null;
            return (
              <div
                key={a.id || i}
                style={{
                  position: "relative",
                  fontSize: 12,
                  color: "var(--text-color)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  backgroundColor: `rgba(${addendumRgb}, ${ADDENDUM_OPACITY})`,
                  borderRadius: 6,
                  padding: "6px 8px 6px 14px",
                  minHeight: 32,
                  overflow: "visible",
                }}
              >
                {/* Red + at edge: center on boundary main/addendum, arm in white, no layout space */}
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    top: 0,
                    transform: "translate(-50%, -50%)",
                    width: 22,
                    height: 22,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 16,
                    fontWeight: 700,
                    color: "#dc2626",
                    lineHeight: 1,
                    pointerEvents: "none",
                  }}
                  aria-hidden
                >
                  +
                </div>
                <TranslatableSlice
                  translation={translation}
                  fieldId={addendumFieldId}
                  sourceText={a.text}
                  leftSlot={addendumLeftSlot}
                  render={(displayedText) =>
                    isEditingAddendum ? (
                      <textarea
                        value={addendumEditText}
                        onChange={(e) => setAddendumEditText(e.target.value)}
                        onBlur={handleSaveAddendumEdit}
                        style={{
                          width: "100%",
                          minHeight: 48,
                          fontSize: 12,
                          padding: 6,
                          border: "1px solid var(--border-color)",
                          borderRadius: 4,
                          resize: "vertical",
                          fontFamily: "inherit",
                        }}
                      />
                    ) : (
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ flex: 1, minWidth: 0 }}>
                          <span style={{ fontWeight: 600, color: "var(--secondary-text-color)" }}>{a.vendor}:</span> {displayedText}
                        </span>
                        <span
                          style={{
                            fontSize: 11,
                            color: addendumUp > addendumDown ? "#16a34a" : addendumDown > addendumUp ? "#dc2626" : "var(--secondary-text-color)",
                            flexShrink: 0,
                            fontWeight: 600,
                          }}
                          title={`${addendumVoteTooltip}. Only addendums with more up than down are used in the revision.`}
                        >
                          ↑ {addendumUp}  ↓ {addendumDown}
                        </span>
                      </div>
                    )
                  }
                />
              </div>
            );
          })}
        </div>
      )}
      {subcommentCount > 0 && (
        <div style={{ marginTop: 6 }}>
          <button
            type="button"
            onClick={() => setSubcommentsCollapsed((c) => !c)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 0",
              border: "none",
              background: "none",
              cursor: "pointer",
              fontSize: 11,
              color: "var(--secondary-text-color)",
            }}
            title={subcommentsCollapsed ? "Expand subcomments" : "Collapse subcomments"}
          >
            <span style={{ fontSize: 10 }}>{subcommentsCollapsed ? "▶" : "▼"}</span>
            {subcommentCount} subcomment{subcommentCount !== 1 ? "s" : ""}
          </button>
          {!subcommentsCollapsed && (
            <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 6 }}>
              {subcomments.map((s, subIdx) => {
                const subRgb = colorToRgbString(vendorColors[s.vendor] || null);
                const subFieldId = fieldId ? `${fieldId}_sub_${subIdx}` : null;
                return (
                  <div
                    key={s.id || s.text?.slice(0, 12)}
                    style={{
                      position: "relative",
                      fontSize: 12,
                      padding: "6px 8px 6px 14px",
                      marginLeft: 8,
                      backgroundColor: `rgba(${subRgb}, ${SUBCOMMENT_OPACITY})`,
                      borderRadius: 12,
                      border: "1px solid var(--border-color)",
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                    }}
                  >
                    {/* Thought bubble: small circle on the left */}
                    <div
                      style={{
                        position: "absolute",
                        left: -4,
                        top: "50%",
                        transform: "translateY(-50%)",
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        backgroundColor: `rgba(${subRgb}, ${SUBCOMMENT_OPACITY})`,
                        border: "1px solid var(--border-color)",
                      }}
                    />
                    <TranslatableSlice
                      translation={translation}
                      fieldId={subFieldId}
                      sourceText={s.text}
                      render={(displayedText) => (
                        <span>
                          <span style={{ color: "var(--secondary-text-color)", fontWeight: 600 }}>{s.vendor}:</span> {displayedText}
                        </span>
                      )}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
      <div
        style={{
          marginTop: 6,
          fontSize: 11,
          display: "flex",
          gap: 4,
          alignItems: "flex-start",
          flexDirection: "column",
        }}
      >
        {roundVoteRows.map((row, idx) => {
          const upCount = row.upList.length;
          const downCount = row.downList.length;
          const abstainCount = row.abstainList.length;
          const reasons = row.reasons || {};
          const reasonLines = Object.entries(reasons)
            .map(([vendor, reason]) => `${vendor}: ${reason}`)
            .filter((line) => line.trim() !== "");
          const tooltipParts = [
            upCount ? `Up: ${row.upList.join(", ")}` : null,
            downCount ? `Down: ${row.downList.join(", ")}` : null,
            abstainCount ? `Abstain: ${row.abstainList.join(", ")}` : null,
            reasonLines.length ? `Why:\n${reasonLines.join("\n")}` : null,
          ].filter(Boolean);
          const tooltip = tooltipParts.length ? tooltipParts.join("\n\n") : "No votes";
          return (
            <div
              key={`${comment.id || commentIndex}_round_${row.round}_${idx}`}
              title={tooltip}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                color: "var(--secondary-text-color)",
              }}
            >
              <span style={{ fontWeight: 700, color: "var(--text-color)" }}>R{row.round}</span>
              <span style={{ color: upCount > downCount ? "#16a34a" : "var(--secondary-text-color)" }}>↑ {upCount}</span>
              <span style={{ color: downCount > 0 ? "#dc2626" : "var(--secondary-text-color)" }}>↓ {downCount}</span>
              <span style={{ color: abstainCount > 0 ? "#0d9488" : "var(--secondary-text-color)" }}>⏭ {abstainCount}</span>
            </div>
          );
        })}
        <span style={{ fontSize: 10, color: net > 0 ? "#16a34a" : "var(--secondary-text-color)" }}>
          Net: {net}
        </span>
      </div>
        </>
      )}
    </div>
  );
}
