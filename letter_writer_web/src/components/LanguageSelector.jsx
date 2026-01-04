import React, { useState } from "react";

/**
 * Reusable language selector component
 * @param {Object} props
 * @param {Array} props.languages - Array of language objects {code, label, color}
 * @param {string} props.viewLanguage - Currently selected language code or "source"
 * @param {Function} props.onLanguageChange - Callback when language changes: (code) => void
 * @param {Function} props.hasTranslation - Optional function to check if translation is cached: (code) => boolean
 * @param {boolean} props.disabled - Whether the selector is disabled
 * @param {boolean} props.isTranslating - Whether translation is in progress
 * @param {string} props.size - Size variant: "small" | "medium" | "large" (default: "medium")
 */
export default function LanguageSelector({
  languages = [],
  viewLanguage = "source",
  onLanguageChange,
  hasTranslation = () => false,
  disabled = false,
  isTranslating = false,
  size = "medium",
}) {
  const fontSize = size === "small" ? "11px" : size === "large" ? "14px" : "12px";
  const padding = size === "small" ? "3px 6px" : size === "large" ? "6px 10px" : "4px 8px";

  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
      <button
        onClick={() => onLanguageChange("source")}
        disabled={disabled || isTranslating}
        style={{
          padding,
          fontSize,
          background: viewLanguage === "source" ? "#10b981" : "var(--button-bg)",
          color: viewLanguage === "source" ? "white" : "var(--button-text)",
          border: "2px solid #10b981",
          borderRadius: 4,
          cursor: disabled || isTranslating ? "not-allowed" : "pointer",
          opacity: isTranslating ? 0.7 : 1,
        }}
        title="Show original text"
      >
        OR
      </button>
      {languages.map(({ code, label, color }) => {
        const isActive = viewLanguage === code;
        const bg = color || "#3b82f6";
        const lbl = label || code.toUpperCase();
        const cached = hasTranslation(code);
        
        return (
          <button
            key={code}
            onClick={() => onLanguageChange(code)}
            disabled={disabled || isTranslating}
            style={{
              padding,
              fontSize,
              background: isActive ? "#10b981" : bg,
              color: "white",
              border: isActive ? "2px solid #10b981" : (cached ? "2px solid #10b981" : "2px solid transparent"),
              borderRadius: 4,
              cursor: disabled || isTranslating ? "not-allowed" : "pointer",
              opacity: (isActive ? 1 : (cached ? 1 : 0.6)) * (isTranslating ? 0.7 : 1),
            }}
            title={`Translate to ${lbl}`}
          >
            {isTranslating && isActive ? "…" : lbl}
          </button>
        );
      })}
    </div>
  );
}
