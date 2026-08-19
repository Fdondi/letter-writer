import React from "react";
import { iconBtnStyle } from "./feedbackRowStyles";
import { PersistScopeRadios, persistScopeFromFlags, flagsFromPersistScope } from "./PersistScopeRadios";

export function UserContextRow({
  itemId,
  showInputEditor,
  inputDeclined,
  userContextFilled,
  userContext,
  userContextPlaceholder,
  needsInput,
  isEditingUser,
  disabled,
  draftUserContext,
  setDraftUserContext,
  persistScope,
  onPersistScopeChange,
  onSave,
  onCancel,
  onStartEdit,
  onClear,
}) {
  if (showInputEditor) return null;
  const btnStyle = iconBtnStyle(disabled);

  if (inputDeclined && !userContextFilled && !isEditingUser) {
    return (
      <div key={`${itemId}-ctx-user`} style={{ marginTop: 8, fontSize: 12, color: "#6b7280", fontStyle: "italic" }}>
        You approved this critique without adding missing facts. The model will not receive new facts for this point.
      </div>
    );
  }
  if (!userContextFilled && !isEditingUser) return null;

  if (isEditingUser) {
    return (
      <div key={`${itemId}-ctx-user`} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          <textarea
            style={{ flex: 1, minHeight: 56, fontSize: 13, padding: 8, resize: "vertical", border: "1px solid #fca5a5", background: "#fff" }}
            value={draftUserContext}
            onChange={(e) => setDraftUserContext(e.target.value)}
            disabled={disabled}
            placeholder={userContextPlaceholder}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
            <button type="button" onClick={onSave} disabled={disabled} style={btnStyle} title="Save" aria-label="Save">
              ✓
            </button>
            <button type="button" onClick={onCancel} disabled={disabled} style={btnStyle} title="Cancel" aria-label="Cancel">
              ×
            </button>
          </div>
        </div>
        {needsInput ? (
          <PersistScopeRadios
            name={`persist-${itemId}`}
            scope={persistScope}
            onScopeChange={(scope) => {
              const { cv, agent } = flagsFromPersistScope(scope);
              onPersistScopeChange(cv, agent);
            }}
            disabled={disabled}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div key={`${itemId}-ctx-user`} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0, whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.45, color: "#111827" }}>
          {userContext}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
          <button
            type="button"
            onClick={onStartEdit}
            disabled={disabled}
            style={btnStyle}
            title="Edit"
            aria-label="Edit context line"
          >
            ✎
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={disabled}
            style={{ ...btnStyle, color: "#b91c1c", borderColor: "#fca5a5" }}
            title="Remove"
            aria-label="Remove context line"
          >
            ×
          </button>
        </div>
      </div>
      {needsInput && userContextFilled ? (
        <PersistScopeRadios
          name={`persist-${itemId}`}
          scope={persistScope}
          onScopeChange={(scope) => {
            const { cv, agent } = flagsFromPersistScope(scope);
            onPersistScopeChange(cv, agent);
          }}
          disabled={disabled}
        />
      ) : null}
    </div>
  );
}

export function computePersistScope(persistUserContextToCv, persistUserContextForAgents) {
  return persistScopeFromFlags(persistUserContextToCv, persistUserContextForAgents);
}
