import React, { useState } from "react";
import { useLanguages } from "../contexts/LanguageContext";
import { CEFR_LEVELS } from "../utils/languageLevels";

function PencilIcon({ size = 12, color = "currentColor" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  );
}

function PencilButton({ active, onClick, title, accentColor }) {
  const color = accentColor || "var(--secondary-text-color)";
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 20,
        height: 20,
        padding: 0,
        border: `1px solid ${active ? color : "transparent"}`,
        borderRadius: 3,
        background: active ? `${color}22` : "transparent",
        color,
        cursor: "pointer",
        lineHeight: 1,
      }}
    >
      <PencilIcon size={11} color={color} />
    </button>
  );
}

/**
 * Language configuration: enabled languages, CEFR level, and language-specific instructions.
 */
export default function LanguageConfig() {
  const {
    enabledLanguages,
    languages,
    addLanguage,
    toggleLanguage,
    updateLanguageInstructions,
    updateLanguageLevelAndSave,
  } = useLanguages();
  const [languageInput, setLanguageInput] = useState("");
  const [expandedCode, setExpandedCode] = useState(null);

  const addLanguageFromSearch = () => {
    const code = languageInput.trim().toLowerCase();
    if (!code) return;

    addLanguage(code);
    setLanguageInput("");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        alignItems: "center",
        background: "var(--bg-color)",
        padding: "6px 8px",
        borderRadius: 8,
        boxShadow: "0 2px 6px rgba(0,0,0,0.05)",
      }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>Languages:</span>
        <div style={{ display: "flex", alignItems: "center", border: "1px solid var(--border-color)", borderRadius: 4, padding: "2px 6px", flexWrap: "wrap", gap: 4, background: "var(--input-bg)" }}>
          {enabledLanguages.map((lang) => {
            const accent = lang.color || "#3b82f6";
            const lbl = lang.label || lang.code.toUpperCase();
            return (
              <div
                key={lang.code}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 2,
                  fontSize: 12,
                  borderRadius: 3,
                  border: `1px solid ${accent}`,
                  overflow: "hidden",
                }}
              >
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 3,
                    fontWeight: 600,
                    padding: "2px 4px",
                    background: accent,
                    color: "white",
                    lineHeight: 1.2,
                  }}
                >
                  {lbl}
                  <select
                    value={lang.level || "B2"}
                    onChange={(e) => updateLanguageLevelAndSave(lang.code, e.target.value)}
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      padding: 0,
                      margin: 0,
                      border: "none",
                      background: "transparent",
                      color: "white",
                      outline: "none",
                      cursor: "pointer",
                      lineHeight: 1.2,
                    }}
                    aria-label={`CEFR level for ${lbl}`}
                  >
                    {CEFR_LEVELS.map((lv) => (
                      <option key={lv} value={lv}>{lv === "native" ? "native" : lv}</option>
                    ))}
                  </select>
                </span>
                <PencilButton
                  active={expandedCode === lang.code}
                  accentColor={accent}
                  title="custom instructions for language"
                  onClick={() => setExpandedCode(expandedCode === lang.code ? null : lang.code)}
                />
                <button
                  type="button"
                  onClick={() => toggleLanguage(lang.code)}
                  title={`Remove ${lbl}`}
                  aria-label={`Remove ${lbl}`}
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--secondary-text-color)",
                    cursor: "pointer",
                    padding: "0 4px 0 0",
                    fontSize: 12,
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              </div>
            );
          })}
          <input
            type="text"
            value={languageInput}
            onChange={(e) => setLanguageInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                addLanguageFromSearch();
              }
            }}
            placeholder="Add language code (e.g., es)"
            style={{
              fontSize: 12,
              padding: "4px 0px",
              border: "none",
              outline: "none",
              minWidth: 120,
              flexGrow: 1,
              background: "transparent",
              color: "var(--text-color)",
            }}
          />
          <button
            onClick={addLanguageFromSearch}
            style={{
              padding: "4px 8px",
              fontSize: 12,
              background: "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            Add
          </button>
        </div>
      </div>

      {expandedCode && (() => {
        const expanded = languages.find((l) => l.code === expandedCode);
        const accent = expanded?.color || "#3b82f6";
        return (
        <textarea
          value={expanded?.instructions || ""}
          onChange={(e) => updateLanguageInstructions(expandedCode, e.target.value)}
          placeholder="Language-specific instructions for generation and LLM translation…"
          rows={2}
          style={{
            width: "100%",
            boxSizing: "border-box",
            fontSize: 12,
            padding: "6px 8px",
            borderRadius: 4,
            border: `2px solid ${accent}`,
            background: "var(--input-bg)",
            color: "var(--text-color)",
            resize: "vertical",
          }}
        />
        );
      })()}
    </div>
  );
}
