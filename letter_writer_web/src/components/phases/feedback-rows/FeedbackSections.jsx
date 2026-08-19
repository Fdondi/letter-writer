import React from "react";
import { GoodRow } from "./GoodRow";

export function FilteredFeedbackSection({ entries }) {
  if (!entries.length) return null;
  return (
    <details style={{ marginTop: 16, borderTop: "1px solid #e5e7eb", paddingTop: 12 }}>
      <summary style={{ cursor: "pointer", fontSize: 13, color: "#6b7280", fontWeight: 500 }}>
        Filtered feedback ({entries.length}) — not shown as critiques
      </summary>
      <p style={{ fontSize: 12, color: "#9ca3af", margin: "8px 0 10px" }}>
        The model (or legacy format) sent text that is intentionally not imported as open issues — for example NO
        COMMENT, SKIP, or an empty PLEASE FIX line.
      </p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
        {entries.map((entry, idx) => (
          <li
            key={`filtered-${idx}`}
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 6,
              padding: 8,
              background: "#fafafa",
              fontSize: 13,
              color: "#4b5563",
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 600, color: "#9ca3af", marginBottom: 6 }}>{entry.label}</div>
            <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{entry.text}</div>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function GoodItemsSection({
  goodItems,
  categoryKey,
  translation,
  editingId,
  disabled,
  draftObservation,
  setDraftObservation,
  editingPromoteToFix,
  setEditingPromoteToFix,
  onSave,
  onCancel,
  onStartEdit,
  onRemove,
}) {
  if (!goodItems.length) return null;
  return (
    <details style={{ marginTop: 16, borderTop: "1px solid #e5e7eb", paddingTop: 12 }}>
      <summary style={{ cursor: "pointer", fontSize: 13, color: "#6b7280", fontWeight: 500 }}>
        Positive or neutral model notes ({goodItems.length}) — no approval needed
      </summary>
      <p style={{ fontSize: 12, color: "#9ca3af", margin: "8px 0 10px" }}>
        These are optional to read. Use Edit → “Turn into critique” if the model was too optimistic.
      </p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {goodItems.map((it) => {
          const fieldId = `feedback_${categoryKey}_${it.id}`;
          const displayedObservation =
            translation && fieldId
              ? translation.getTranslatedText(fieldId, it.observation || "")
              : it.observation || "";
          return (
            <GoodRow
              key={it.id}
              it={it}
              isEditing={editingId === it.id}
              disabled={disabled}
              draftObservation={draftObservation}
              setDraftObservation={setDraftObservation}
              editingPromoteToFix={editingPromoteToFix}
              setEditingPromoteToFix={setEditingPromoteToFix}
              displayedObservation={displayedObservation}
              onSave={onSave}
              onCancel={onCancel}
              onStartEdit={onStartEdit}
              onRemove={onRemove}
            />
          );
        })}
      </ul>
    </details>
  );
}
