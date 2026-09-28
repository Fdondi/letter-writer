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

export function InvalidItemsSection({ items, disabled, onRestore }) {
  if (!items.length) return null;
  return (
    <details open style={{ marginTop: 12, borderTop: "1px solid #e5e7eb", paddingTop: 12 }}>
      <summary style={{ cursor: "pointer", fontSize: 13, color: "#6b7280", fontWeight: 500 }}>
        Laya marked invalid ({items.length}) — not treated as critiques
      </summary>
      <p style={{ fontSize: 12, color: "#9ca3af", margin: "8px 0 10px" }}>
        Local Laya judged these comments as ungrounded. They stay out of the letter until you restore one.
      </p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((it) => {
          const probability = typeof it.laya_valid_probability === "number" ? it.laya_valid_probability : null;
          return (
            <li
              key={it.id}
              style={{
                border: "1px solid #e5e7eb",
                borderRadius: 6,
                padding: 8,
                background: "#fafafa",
                fontSize: 13,
                color: "#4b5563",
              }}
            >
              <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{it.observation}</div>
              <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                {probability != null && (
                  <span style={{ fontSize: 11, color: "#9ca3af" }}>
                    {Math.round(probability * 100)}% grounded
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => onRestore(it)}
                  disabled={disabled}
                  style={{ fontSize: 12, padding: "2px 8px", cursor: disabled ? "not-allowed" : "pointer" }}
                >
                  Restore
                </button>
              </div>
            </li>
          );
        })}
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
