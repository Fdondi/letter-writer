import React, { useState, useEffect } from "react";
import {
  getScaleConfig,
  setScaleConfig,
  DEFAULT_NEED,
  DEFAULT_LEVEL,
  DEFAULT_NEED_SCALE,
  DEFAULT_NEED_SEMANTICS,
} from "../utils/competenceScales";

export default function CompetenceScaleSettings({ onSaved }) {
  const [need, setNeed] = useState(() => ({ ...DEFAULT_NEED }));
  const [level, setLevel] = useState(() => ({ ...DEFAULT_LEVEL }));
  const [needScale, setNeedScale] = useState(() => ({ ...DEFAULT_NEED_SCALE }));
  const [needSemantics, setNeedSemantics] = useState(() => ({ ...DEFAULT_NEED_SEMANTICS }));
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    const c = getScaleConfig();
    setNeed(c.need);
    setLevel(c.level);
    setNeedScale(c.needScale || { ...DEFAULT_NEED_SCALE });
    setNeedSemantics(c.needSemantics || { ...DEFAULT_NEED_SEMANTICS });
  }, []);

  const handleNeedChange = (label, value) => {
    const n = parseInt(value, 10);
    if (Number.isNaN(n) || n < 1 || n > 5) return;
    setNeed((prev) => ({ ...prev, [label]: n }));
    setDirty(true);
  };

  const handleLevelChange = (label, value) => {
    const n = parseInt(value, 10);
    if (Number.isNaN(n) || n < 1 || n > 5) return;
    setLevel((prev) => ({ ...prev, [label]: n }));
    setDirty(true);
  };

  const handleNeedScaleChange = (label, value) => {
    if (value !== "linear" && value !== "log") return;
    setNeedScale((prev) => ({ ...prev, [label]: value }));
    setDirty(true);
  };

  const handleNeedSemanticsChange = (label, value) => {
    setNeedSemantics((prev) => ({ ...prev, [label]: value }));
    setDirty(true);
  };

  const handleAddNeed = () => {
    const key = window.prompt("New need label (e.g. 'optional')");
    if (!key || !key.trim()) return;
    const k = key.trim();
    if (need[k] != null) return;
    setNeed((prev) => ({ ...prev, [k]: 3 }));
    setNeedScale((prev) => ({ ...prev, [k]: "linear" }));
    setNeedSemantics((prev) => ({ ...prev, [k]: "" }));
    setDirty(true);
  };

  const handleAddLevel = () => {
    const key = window.prompt("New level label (e.g. 'Expert')");
    if (!key || !key.trim()) return;
    const k = key.trim();
    if (level[k] != null) return;
    setLevel((prev) => ({ ...prev, [k]: 3 }));
    setDirty(true);
  };

  const handleRemoveNeed = (label) => {
    setNeed((prev) => {
      const next = { ...prev };
      delete next[label];
      return next;
    });
    setNeedScale((prev) => {
      const next = { ...prev };
      delete next[label];
      return next;
    });
    setNeedSemantics((prev) => {
      const next = { ...prev };
      delete next[label];
      return next;
    });
    setDirty(true);
  };

  const handleRemoveLevel = (label) => {
    setLevel((prev) => {
      const next = { ...prev };
      delete next[label];
      return next;
    });
    setDirty(true);
  };

  const handleSave = () => {
    setSaving(true);
    const ns = {};
    const nsem = {};
    Object.keys(need).forEach((k) => {
      ns[k] = needScale[k] === "log" ? "log" : "linear";
      nsem[k] = (needSemantics[k] ?? "").trim();
    });
    const config = {
      need: { ...need },
      level: { ...level },
      needScale: ns,
      needSemantics: nsem,
    };
    setScaleConfig(config);
    setDirty(false);
    onSaved?.(config);
    setSaving(false);
  };

  const handleReset = () => {
    setNeed({ ...DEFAULT_NEED });
    setLevel({ ...DEFAULT_LEVEL });
    setNeedScale({ ...DEFAULT_NEED_SCALE });
    setNeedSemantics({ ...DEFAULT_NEED_SEMANTICS });
    setDirty(true);
  };

  const block = (title, map, onChange, onAdd, onRemove, needScaleMap, onNeedScaleChange, needSemanticsMap, onNeedSemanticsChange) => (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <strong style={{ color: "var(--text-color)" }}>{title}</strong>
        <button
          type="button"
          onClick={onAdd}
          style={{
            padding: "2px 8px",
            fontSize: 12,
            background: "var(--panel-bg)",
            color: "var(--text-color)",
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          + Add label
        </button>
      </div>
      {needScaleMap && onNeedScaleChange && (
        <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginBottom: 4 }}>
          Rating: linear = standard 1–5; log = logarithmic scaling for scoring.
        </div>
      )}
      {needSemanticsMap && onNeedSemanticsChange && (
        <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginBottom: 4 }}>
          Semantic: short description per category, shown to the model during extraction.
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {Object.entries(map).map(([label, val]) => (
          <div key={label} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                flexWrap: "wrap",
              }}
            >
              <span style={{ minWidth: 140, color: "var(--text-color)", fontSize: 13 }}>
                {label}
              </span>
              <input
                type="number"
                min={1}
                max={5}
                value={val}
                onChange={(e) => onChange(label, e.target.value)}
                style={{
                  width: 48,
                  padding: "4px 6px",
                  fontSize: 13,
                  background: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                }}
              />
              {needScaleMap && onNeedScaleChange && (
                <select
                  value={needScaleMap[label] === "log" ? "log" : "linear"}
                  onChange={(e) => onNeedScaleChange(label, e.target.value)}
                  style={{
                    padding: "4px 6px",
                    fontSize: 12,
                    background: "var(--input-bg)",
                    color: "var(--text-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: 4,
                    minWidth: 90,
                  }}
                >
                  <option value="linear">linear</option>
                  <option value="log">log</option>
                </select>
              )}
              <button
                type="button"
                onClick={() => onRemove(label)}
                style={{
                  padding: "2px 6px",
                  fontSize: 11,
                  background: "transparent",
                  color: "#dc2626",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                Remove
              </button>
            </div>
            {needSemanticsMap && onNeedSemanticsChange && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, paddingLeft: 148 }}>
                <span style={{ fontSize: 11, color: "var(--secondary-text-color)", flexShrink: 0 }}>
                  Semantic:
                </span>
                <input
                  type="text"
                  value={needSemanticsMap[label] ?? ""}
                  onChange={(e) => onNeedSemanticsChange(label, e.target.value)}
                  placeholder="e.g. central to the job"
                  style={{
                    flex: 1,
                    minWidth: 120,
                    padding: "4px 6px",
                    fontSize: 12,
                    background: "var(--input-bg)",
                    color: "var(--text-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: 4,
                  }}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div
      style={{
        marginBottom: 30,
        padding: 20,
        backgroundColor: "var(--bg-color)",
        border: "1px solid var(--border-color)",
        borderRadius: "4px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 15,
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <h3 style={{ margin: 0, color: "var(--text-color)" }}>
          Competence rating scales
        </h3>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={handleReset}
            style={{
              padding: "6px 12px",
              fontSize: 14,
              background: "var(--panel-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
              cursor: "pointer",
            }}
          >
            Reset to defaults
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !dirty}
            style={{
              padding: "6px 12px",
              fontSize: 14,
              backgroundColor: dirty ? "#3b82f6" : "var(--header-bg)",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: saving || !dirty ? "not-allowed" : "pointer",
              opacity: saving || !dirty ? 0.7 : 1,
            }}
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
      <p
        style={{
          marginTop: 0,
          marginBottom: 15,
          fontSize: "14px",
          color: "var(--secondary-text-color)",
        }}
      >
        Map need (job requirement) and level (candidate from CV) labels to
        numeric values 1–5. Used for sorting, stars, and weighted average.
        Need and level labels are sent to extraction: the model returns competences in these
        categories and grades CV fit using these level labels. Rating (linear/log) affects
        scoring only.
      </p>
      {block("Need (job requirement)", need, handleNeedChange, handleAddNeed, handleRemoveNeed, needScale, handleNeedScaleChange, needSemantics, handleNeedSemanticsChange)}
      {block("Level (candidate)", level, handleLevelChange, handleAddLevel, handleRemoveLevel)}
    </div>
  );
}
