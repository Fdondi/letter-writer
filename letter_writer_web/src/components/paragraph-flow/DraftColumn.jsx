import React from "react";
import ParagraphOptionCard from "./ParagraphOptionCard";
import { feedbackTopicLabel, vendorNoteColor } from "../../constants/feedbackTopics";
import { isStrongNote, PARAGRAPH_FEEDBACK_TOPICS } from "../../utils/paragraphFlow";

/** One column of paragraph options: a whole draft, or the "More options" continuations. */
export default function DraftColumn({
  title,
  subtitle,
  color,
  drafts,
  usedIds,
  vendors,
  regeneratingIds,
  onRetryDraft,
  onDismissDraft,
  onUse,
  onDiscard,
  onRestore,
  onRegenerate,
  onRetryFeedback,
  width = 320,
  emptyHint = null,
}) {
  return (
    <div
      data-testid="paragraph-draft-column"
      style={{
        width,
        minWidth: width,
        display: "flex",
        flexDirection: "column",
        border: "1px solid var(--border-color)",
        borderRadius: 6,
        background: "var(--panel-bg)",
        minHeight: 0,
        maxHeight: "100%",
      }}
    >
      <div
        style={{
          padding: "6px 10px",
          background: color || "var(--header-bg)",
          borderRadius: "6px 6px 0 0",
          color: "var(--text-color)",
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          flexShrink: 0,
        }}
      >
        <strong style={{ textTransform: "capitalize" }}>{title}</strong>
        {subtitle && <span style={{ fontSize: 11, opacity: 0.85 }}>{subtitle}</span>}
      </div>
      <div style={{ padding: 8, display: "flex", flexDirection: "column", gap: 8, overflowY: "auto", minHeight: 0 }}>
        {drafts.length === 0 && emptyHint}
        {drafts.map((draft) => (
          <React.Fragment key={draft.id}>
            {draft.kind === "continuation" && (
              <div style={{ fontSize: 11, color: "var(--secondary-text-color)", textTransform: "capitalize" }}>
                {draft.vendor}
                {draft.model ? ` · ${draft.model}` : ""}
                {draft.letterComplete ? " · says the letter is complete" : ""}
              </div>
            )}
            {draft.status === "loading" && (
              <div style={{ fontSize: 12, color: "var(--secondary-text-color)", padding: 8 }}>
                {draft.kind === "letter" ? "Writing a draft…" : "Writing the next paragraph…"}
              </div>
            )}
            {draft.status === "error" && (
              <div style={{ fontSize: 12, color: "var(--error-text)", padding: 8, border: "1px solid var(--warning-border)", borderRadius: 4, background: "var(--warning-bg)" }}>
                {draft.error || "Failed"}
                <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                  <button type="button" onClick={() => onRetryDraft?.(draft)}>Retry</button>
                  <button type="button" onClick={() => onDismissDraft?.(draft)}>Dismiss</button>
                </div>
              </div>
            )}
            {draft.status === "ready" && <WholeLetterNotes draft={draft} />}
            {draft.status === "ready" &&
              draft.paragraphs.map((p) => (
                <div key={p.id} style={{ marginLeft: p.parentId ? 12 : 0 }}>
                  <ParagraphOptionCard
                    paragraph={p}
                    vendor={draft.vendor}
                    color={color}
                    used={usedIds.has(p.id)}
                    vendors={vendors}
                    regenerating={regeneratingIds.has(p.id)}
                    onUse={() => onUse(draft, p)}
                    onDiscard={() => onDiscard(draft, p)}
                    onRestore={() => onRestore(draft, p)}
                    onRegenerate={(opts) => onRegenerate(draft, p, opts)}
                    onRetryFeedback={(topics) => onRetryFeedback(draft, p, topics)}
                  />
                </div>
              ))}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

function WholeLetterNotes({ draft }) {
  const rows = [];
  for (const topic of PARAGRAPH_FEEDBACK_TOPICS) {
    for (const it of draft.wholeLetterNotes?.[topic] || []) rows.push({ ...it, topic });
  }
  if (rows.length === 0) return null;
  const strong = rows.filter(isStrongNote).length;
  return (
    <details style={{ fontSize: 12, border: "1px solid var(--border-color)", borderRadius: 4, padding: "4px 8px", background: "var(--card-bg)" }}>
      <summary style={{ cursor: "pointer" }}>
        Notes on the whole letter ({rows.length}
        {strong ? `, ${strong} to consider` : ""})
      </summary>
      <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>
        {rows.map((it) => (
          <li key={it.id} style={{ opacity: isStrongNote(it) ? 1 : 0.55, marginBottom: 2 }}>
            <strong style={{ color: vendorNoteColor(it.topic) }}>{feedbackTopicLabel(it.topic)}:</strong> {it.observation}
          </li>
        ))}
      </ul>
    </details>
  );
}
