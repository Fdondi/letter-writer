import React from "react";
import {
  CONTEXT_SOURCES,
  CONTEXT_SOURCE_LABELS,
  CONTEXT_USER_SOURCE,
} from "../feedbackItemUtils";
import { iconBtnStyle } from "./feedbackRowStyles";
import {
  PersistScopeRadios,
  persistScopeFromFlags,
  flagsFromPersistScope,
} from "./PersistScopeRadios";

export function MachineRow({
  itemId,
  idx,
  raw,
  isRowEditing,
  isEditing,
  disabled,
  draftContextLine,
  setDraftContextLine,
  onSave,
  onCancel,
  onStartEdit,
  onRemove,
  onUpdateSource,
  onUpdatePersistScope,
}) {
  const text = String(raw && typeof raw === "object" && !Array.isArray(raw) ? raw.text : (raw ?? ""));
  const src = String(raw && typeof raw === "object" && !Array.isArray(raw) ? raw.source : "CV").toUpperCase();
  const normalizedSrc =
    src === CONTEXT_USER_SOURCE
      ? CONTEXT_USER_SOURCE
      : CONTEXT_SOURCES.includes(src)
        ? src
        : "CV";
  const isUserAdded = normalizedSrc === CONTEXT_USER_SOURCE;
  const btnStyle = iconBtnStyle(disabled);

  if (!text.trim() && !isRowEditing && !isEditing) return null;

  if (isRowEditing) {
    if (isUserAdded) {
      const persistLineToCv = raw && typeof raw === "object" && raw.persist_to_cv !== false;
      const persistLineForAgents =
        raw && typeof raw === "object" && raw.persist_for_agents !== undefined
          ? raw.persist_for_agents !== false
          : persistLineToCv;
      const persistLineScope = persistScopeFromFlags(persistLineToCv, persistLineForAgents);
      return (
        <div key={`${itemId}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#b91c1c", marginBottom: 6 }}>
              Your context
            </div>
            <textarea
              style={{
                width: "100%",
                minHeight: 56,
                fontSize: 13,
                padding: 8,
                resize: "vertical",
                border: "1px solid #fca5a5",
                background: "#fff",
              }}
              value={draftContextLine}
              onChange={(e) => setDraftContextLine(e.target.value)}
              disabled={disabled}
              placeholder="Facts or notes for this critique (not labeled as CV / job material)"
            />
            <PersistScopeRadios
              name={`persist-user-line-${itemId}-${idx}`}
              scope={persistLineScope}
              onScopeChange={(scope) => {
                const { cv, agent } = flagsFromPersistScope(scope);
                onUpdatePersistScope(idx, { persist_to_cv: cv, persist_for_agents: agent });
              }}
              disabled={disabled}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
            <button type="button" onClick={onSave} disabled={disabled} style={btnStyle} title="Save" aria-label="Save">
              ✓
            </button>
            <button type="button" onClick={onCancel} disabled={disabled} style={btnStyle} title="Cancel" aria-label="Cancel">
              ×
            </button>
          </div>
        </div>
      );
    }
    return (
      <div key={`${itemId}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>
            Source
          </div>
          <select
            value={normalizedSrc}
            onChange={(e) => onUpdateSource(idx, e.target.value)}
            disabled={disabled}
            style={{ fontSize: 12, padding: "4px 8px", marginBottom: 6, maxWidth: 220 }}
          >
            {CONTEXT_SOURCES.map((s) => (
              <option key={s} value={s}>
                {CONTEXT_SOURCE_LABELS[s] ?? s}
              </option>
            ))}
          </select>
          <textarea
            style={{ width: "100%", minHeight: 56, fontSize: 13, padding: 8, resize: "vertical" }}
            value={draftContextLine}
            onChange={(e) => setDraftContextLine(e.target.value)}
            disabled={disabled}
            placeholder="Paste-ready fact/snippet (no instructions)"
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
          <button type="button" onClick={onSave} disabled={disabled} style={btnStyle} title="Save" aria-label="Save">
            ✓
          </button>
          <button type="button" onClick={onCancel} disabled={disabled} style={btnStyle} title="Cancel" aria-label="Cancel">
            ×
          </button>
        </div>
      </div>
    );
  }

  if (isUserAdded) {
    const persistLineToCv = raw && typeof raw === "object" && raw.persist_to_cv !== false;
    const persistLineForAgents =
      raw && typeof raw === "object" && raw.persist_for_agents !== undefined
        ? raw.persist_for_agents !== false
        : persistLineToCv;
    const persistLineScope = persistScopeFromFlags(persistLineToCv, persistLineForAgents);
    return (
      <div key={`${itemId}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#b91c1c", marginBottom: 4 }}>
            Your context
          </div>
          <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.45, color: "#111827" }}>
            {text.trim() ? text : "(empty)"}
          </div>
          {text.trim() ? (
            <PersistScopeRadios
              name={`persist-user-line-${itemId}-${idx}`}
              scope={persistLineScope}
              onScopeChange={(scope) => {
                const { cv, agent } = flagsFromPersistScope(scope);
                onUpdatePersistScope(idx, { persist_to_cv: cv, persist_for_agents: agent });
              }}
              disabled={disabled}
            />
          ) : null}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
          <button
            type="button"
            onClick={() => onStartEdit(idx)}
            disabled={disabled}
            style={btnStyle}
            title="Edit"
            aria-label="Edit context line"
          >
            ✎
          </button>
          <button
            type="button"
            onClick={() => onRemove(idx)}
            disabled={disabled}
            style={{ ...btnStyle, color: "#b91c1c", borderColor: "#fca5a5" }}
            title="Remove"
            aria-label="Remove context line"
          >
            ×
          </button>
        </div>
      </div>
    );
  }

  return (
    <div key={`${itemId}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 2 }}>
          {CONTEXT_SOURCE_LABELS[normalizedSrc] ?? normalizedSrc}
        </div>
        <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.45, color: "#111827" }}>
          {text.trim() ? text : "(empty)"}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
        <button
          type="button"
          onClick={() => onStartEdit(idx)}
          disabled={disabled}
          style={btnStyle}
          title="Edit"
          aria-label="Edit context line"
        >
          ✎
        </button>
        <button
          type="button"
          onClick={() => onRemove(idx)}
          disabled={disabled}
          style={{ ...btnStyle, color: "#b91c1c", borderColor: "#fca5a5" }}
          title="Remove"
          aria-label="Remove context line"
        >
          ×
        </button>
      </div>
    </div>
  );
}
