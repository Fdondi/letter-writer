import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { DEFAULT_LANGUAGES } from "../utils/useTranslation";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import {
  defaultInstructionsForCode,
  defaultLevelForCode,
  normalizeLanguageEntry,
  normalizeLanguages,
} from "../utils/languageLevels";

const LanguageContext = createContext();

function withLanguageDefaults(languages) {
  return normalizeLanguages(languages).map((lang) => ({
    ...lang,
    level: lang.level || defaultLevelForCode(lang.code),
    instructions: lang.instructions ?? defaultInstructionsForCode(lang.code),
  }));
}

/**
 * Language configuration context provider
 * Manages translation languages, CEFR levels, and per-language instructions.
 */
export function LanguageProvider({ children }) {
  const [languages, setLanguages] = useState(withLanguageDefaults(DEFAULT_LANGUAGES));
  const [translationProvider, setTranslationProvider] = useState("google");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDefaults = async () => {
      try {
        const res = await fetch("/api/personal-data/");
        if (res.ok) {
          const data = await res.json();
          if (data.default_languages && Array.isArray(data.default_languages) && data.default_languages.length > 0) {
            setLanguages(withLanguageDefaults(data.default_languages));
          }
          if (data.translation_provider === "llm" || data.translation_provider === "google") {
            setTranslationProvider(data.translation_provider);
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
      const exists = prev.some((lang) => lang.code === normalizedCode);
      if (exists) {
        return prev.map((lang) =>
          lang.code === normalizedCode ? { ...lang, enabled: true } : lang
        );
      }
      const newLang = normalizeLanguageEntry({
        code: normalizedCode,
        label: label || normalizedCode.toUpperCase(),
        color: color || getDefaultColorForCode(normalizedCode),
        enabled: true,
        level: defaultLevelForCode(normalizedCode),
        instructions: defaultInstructionsForCode(normalizedCode),
      });
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

  const updateLanguageLevel = useCallback((code, level) => {
    updateLanguage(code, { level });
  }, []);

  const updateLanguageInstructions = useCallback((code, instructions) => {
    updateLanguage(code, { instructions });
  }, []);

  const saveDefaults = useCallback(async (newLanguages, providerOverride = null) => {
    try {
      const languagesToSave = withLanguageDefaults(newLanguages || languages);
      const provider = providerOverride ?? translationProvider;

      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({
          default_languages: languagesToSave,
          translation_provider: provider,
        }),
      });

      if (newLanguages) {
        setLanguages(languagesToSave);
      }
      if (providerOverride) {
        setTranslationProvider(providerOverride);
      }
      return true;
    } catch (e) {
      console.error("Failed to save default languages:", e);
      return false;
    }
  }, [languages, translationProvider]);

  const persistLanguages = useCallback(async (nextLanguages, provider = null) => {
    const languagesToSave = withLanguageDefaults(nextLanguages);
    setLanguages(languagesToSave);
    return saveDefaults(languagesToSave, provider);
  }, [saveDefaults]);

  const updateLanguageLevelAndSave = useCallback(async (code, level) => {
    const next = languages.map((lang) =>
      lang.code === code ? { ...lang, level } : lang
    );
    await persistLanguages(next);
  }, [languages, persistLanguages]);

  const getLevelForCode = useCallback(
    (code) => {
      const entry = languages.find((l) => l.code === code);
      return entry?.level || defaultLevelForCode(code);
    },
    [languages]
  );

  const getEnabledLanguages = () => languages.filter((lang) => lang.enabled);

  return (
    <LanguageContext.Provider
      value={{
        languages,
        enabledLanguages: getEnabledLanguages(),
        translationProvider,
        setTranslationProvider,
        addLanguage,
        removeLanguage,
        toggleLanguage,
        updateLanguage,
        updateLanguageLevel,
        updateLanguageInstructions,
        updateLanguageLevelAndSave,
        getLevelForCode,
        setLanguages,
        saveDefaults,
        loading,
      }}
    >
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguages() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguages must be used within LanguageProvider");
  }
  return context;
}

function getDefaultColorForCode(code) {
  const colors = [
    "#3b82f6",
    "#6366f1",
    "#f97316",
    "#8b5cf6",
    "#10b981",
    "#ef4444",
    "#f59e0b",
    "#06b6d4",
  ];
  let hash = 0;
  for (let i = 0; i < code.length; i++) {
    hash = code.charCodeAt(i) + ((hash << 5) - hash);
  }
  return colors[Math.abs(hash) % colors.length];
}
