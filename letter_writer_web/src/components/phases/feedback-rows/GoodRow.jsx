import React from "react";

export function GoodRow({
  it,
  isEditing,
  disabled,
  draftObservation,
  setDraftObservation,
  editingPromoteToFix,
  setEditingPromoteToFix,
  displayedObservation,
  onSave,
  onCancel,
  onStartEdit,
  onRemove,
}) {
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
      {isEditing ? (
        <>
          <textarea
            style={{ width: "100%", minHeight: 72, padding: 8, fontSize: 13 }}
            value={draftObservation}
            onChange={(e) => setDraftObservation(e.target.value)}
            disabled={disabled}
          />
          <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              onClick={() => setEditingPromoteToFix(true)}
              disabled={disabled || editingPromoteToFix}
              style={{
                fontSize: 12,
                border: "1px solid #d97706",
                color: "#92400e",
                background: "#fffbeb",
              }}
            >
              Turn into critique
            </button>
            {editingPromoteToFix ? (
              <span style={{ fontSize: 11, color: "#92400e" }}>Will save as an issue to fix</span>
            ) : null}
            <button type="button" onClick={onSave} disabled={disabled} style={{ fontSize: 12 }}>
              Save
            </button>
            <button type="button" onClick={onCancel} style={{ fontSize: 12 }}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <div style={{ whiteSpace: "pre-wrap" }}>{displayedObservation || "(empty)"}</div>
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
            <button type="button" onClick={() => onStartEdit(it)} disabled={disabled} style={{ fontSize: 11 }}>
              Edit
            </button>
            <button type="button" onClick={() => onRemove(it.id)} disabled={disabled} style={{ fontSize: 11, color: "#b91c1c" }}>
              Remove
            </button>
          </div>
        </>
      )}
    </li>
  );
}
