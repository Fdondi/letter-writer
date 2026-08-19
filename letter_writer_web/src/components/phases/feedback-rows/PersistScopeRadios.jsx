import React from "react";

export function PersistScopeRadios({ name, scope, onScopeChange, disabled }) {
  return (
    <div style={{ marginTop: 8, fontSize: 12, color: "#374151" }}>
      <div style={{ marginBottom: 4, fontWeight: 600 }}>Save your reply</div>
      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer", marginBottom: 4 }}>
        <input
          type="radio"
          name={name}
          checked={scope === "both"}
          onChange={() => onScopeChange("both")}
          disabled={disabled}
        />
        CV appendix and model context — reuse in future checks
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer", marginBottom: 4 }}>
        <input
          type="radio"
          name={name}
          checked={scope === "agent"}
          onChange={() => onScopeChange("agent")}
          disabled={disabled}
        />
        Model context only (not CV appendix) — if this is already in your CV
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer" }}>
        <input
          type="radio"
          name={name}
          checked={scope === "none"}
          onChange={() => onScopeChange("none")}
          disabled={disabled}
        />
        No — only use for this revision
      </label>
    </div>
  );
}

export function persistScopeFromFlags(persistToCv, persistForAgents) {
  if (persistToCv && persistForAgents) return "both";
  if (!persistToCv && persistForAgents) return "agent";
  return "none";
}

export function flagsFromPersistScope(scope) {
  const cv = scope === "both";
  const agent = scope === "both" || scope === "agent";
  return { cv, agent };
}
