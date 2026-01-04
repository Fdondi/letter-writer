import React, { createContext, useContext, useState, useEffect } from "react";
import { DEFAULT_LANGUAGES } from "../utils/useTranslation";

const LanguageContext = createContext();

/**
 * Language configuration context provider
 * Manages the list of available languages for translation across the app
 */
export function LanguageProvider({ children }) {
  // Load from localStorage or use defaults
  const [languages, setLanguages] = useState(() => {
    try {
      const saved = localStorage.getItem("translationLanguages");
      if (saved) {
        const parsed = JSON.parse(saved);
        // Ensure all languages have the enabled property (migration for old data)
        return parsed.map((lang) => ({
          ...lang,
          enabled: lang.enabled !== undefined ? lang.enabled : true,
        }));
      }
    } catch (e) {
      console.error("Failed to load languages from localStorage:", e);
    }
    return DEFAULT_LANGUAGES;
  });

  // Save to localStorage whenever languages change
  useEffect(() => {
    try {
      localStorage.setItem("translationLanguages", JSON.stringify(languages));
    } catch (e) {
      console.error("Failed to save languages to localStorage:", e);
    }
  }, [languages]);

  const addLanguage = (code, label = null, color = null) => {
    const normalizedCode = code.trim().toLowerCase();
    if (!normalizedCode) return;

    setLanguages((prev) => {
      // Check if language already exists
      const exists = prev.some((lang) => lang.code === normalizedCode);
      if (exists) {
        // Enable it if it was disabled
        return prev.map((lang) =>
          lang.code === normalizedCode ? { ...lang, enabled: true } : lang
        );
      }
      // Add new language
      const newLang = {
        code: normalizedCode,
        label: label || normalizedCode.toUpperCase(),
        color: color || getDefaultColorForCode(normalizedCode),
        enabled: true,
      };
      return [...prev, newLang];
    });
  };

  const removeLanguage = (code) => {
    setLanguages((prev) => prev.filter((lang) => lang.code !== code));
  };

  const toggleLanguage = (code) => {
    setLanguages((prev) =>
      prev.map((lang) =>
        lang.code === code ? { ...lang, enabled: !lang.enabled } : lang
      )
    );
  };

  const updateLanguage = (code, updates) => {
    setLanguages((prev) =>
      prev.map((lang) =>
        lang.code === code ? { ...lang, ...updates } : lang
      )
    );
  };

  const getEnabledLanguages = () => languages.filter((lang) => lang.enabled);

  return (
    <LanguageContext.Provider
      value={{
        languages,
        enabledLanguages: getEnabledLanguages(),
        addLanguage,
        removeLanguage,
        toggleLanguage,
        updateLanguage,
        setLanguages,
      }}
    >
      {children}
    </LanguageContext.Provider>
  );
}

/**
 * Hook to use language context
 */
export function useLanguages() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguages must be used within LanguageProvider");
  }
  return context;
}

/**
 * Get a default color for a language code
 */
function getDefaultColorForCode(code) {
  // Simple hash-based color generation for consistency
  const colors = [
    "#3b82f6", // blue
    "#6366f1", // indigo
    "#f97316", // orange
    "#8b5cf6", // purple
    "#10b981", // green
    "#ef4444", // red
    "#f59e0b", // amber
    "#06b6d4", // cyan
  ];
  let hash = 0;
  for (let i = 0; i < code.length; i++) {
    hash = code.charCodeAt(i) + ((hash << 5) - hash);
  }
  return colors[Math.abs(hash) % colors.length];
}
