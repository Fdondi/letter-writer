import React, { useState } from "react";
import { useLanguages } from "../contexts/LanguageContext";

/**
 * Language configuration component - reuses the existing pattern from LetterTabs
 * Shows enabled languages with X to remove, and input to add new ones
 */
export default function LanguageConfig() {
  const { enabledLanguages, addLanguage, toggleLanguage } = useLanguages();
  const [languageInput, setLanguageInput] = useState("");

  const addLanguageFromSearch = () => {
    const code = languageInput.trim().toLowerCase();
    if (!code) return;

    addLanguage(code);
    setLanguageInput("");
  };

  return (
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
      <div style={{ display: "flex", alignItems: "center", border: "1px solid var(--border-color)", borderRadius: 4, padding: "2px 6px", flexWrap: "wrap", gap: 4, background: 'var(--input-bg)' }}>
        {enabledLanguages.map((lang) => (
          <div
            key={lang.code}
            style={{
              background: "var(--header-bg)",
              padding: "2px 6px",
              borderRadius: 3,
              fontSize: 12,
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            {lang.label}
            <button
              onClick={() => toggleLanguage(lang.code)}
              style={{
                background: "none",
                border: "none",
                color: "var(--secondary-text-color)",
                cursor: "pointer",
                padding: 0,
                fontSize: 12,
              }}
            >
              X
            </button>
          </div>
        ))}
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
            background: 'transparent',
            color: 'var(--text-color)'
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
  );
}
