import React, { createContext, useContext, useState, useEffect } from "react";
import { DEFAULT_LANGUAGES } from "../utils/useTranslation";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

const LanguageContext = createContext();

/**
 * Language configuration context provider
 * Manages the list of available languages for translation across the app
 */
export function LanguageProvider({ children }) {
  // Load from backend on mount, fallback to defaults
  const [languages, setLanguages] = useState(DEFAULT_LANGUAGES);
  const [loading, setLoading] = useState(true);

  // Fetch defaults from backend
  useEffect(() => {
    const fetchDefaults = async () => {
      try {
        const res = await fetch("/api/personal-data/");
        if (res.ok) {
          const data = await res.json();
          if (data.default_languages && Array.isArray(data.default_languages) && data.default_languages.length > 0) {
            setLanguages(data.default_languages);
          }
        }
      } catch (e) {
        console.warn("Failed to load default languages from backend:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchDefaults();
  }, []);

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
  
  // Save current languages as defaults to backend
  const saveDefaults = async (newLanguages) => {
    try {
      // Use provided languages or current state
      const languagesToSave = newLanguages || languages;
      
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({
          default_languages: languagesToSave,
        }),
      });
      
      // Update local state if new languages provided
      if (newLanguages) {
        setLanguages(newLanguages);
      }
      return true;
    } catch (e) {
      console.error("Failed to save default languages:", e);
      return false;
    }
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
        saveDefaults,
        loading,
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
