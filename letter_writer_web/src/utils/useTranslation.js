import { useState, useEffect, useCallback } from "react";
import { translateText } from "./translate";
import { useLanguages } from "../contexts/LanguageContext";

export const DEFAULT_LANGUAGES = [
  { code: "de", label: "DE", color: "#3b82f6", enabled: true },
  { code: "en", label: "EN", color: "#6366f1", enabled: true },
  { code: "it", label: "IT", color: "#f97316", enabled: true },
  { code: "fr", label: "FR", color: "#8b5cf6", enabled: true },
];

/**
 * Hook for managing translation state for a card with multiple text fields
 * @param {Array} languages - Optional array of language objects {code, label, color}. If not provided, uses context.
 * @returns {Object} Translation state and controls
 */
export function useTranslation(languages = null) {
  // Use language context if available, otherwise use provided languages or defaults
  let languageContext;
  try {
    languageContext = useLanguages();
  } catch (e) {
    // Context not available, use provided languages or defaults
    languageContext = null;
  }
  
  const effectiveLanguages = languages || (languageContext?.enabledLanguages || DEFAULT_LANGUAGES);
  const [viewLanguage, setViewLanguage] = useState("source");
  const [translations, setTranslations] = useState({}); // Map of fieldId -> {langCode -> translatedText}
  const [isTranslating, setIsTranslating] = useState({}); // Map of fieldId -> boolean
  const [translationErrors, setTranslationErrors] = useState({}); // Map of fieldId -> error message
  const [sourceSnapshots, setSourceSnapshots] = useState({}); // Map of fieldId -> last source text

  /**
   * Reset translation cache for a field when its source text changes
   */
  const resetFieldTranslation = useCallback((fieldId, sourceText) => {
    if (sourceSnapshots[fieldId] !== sourceText) {
      setTranslations((prev) => {
        const next = { ...prev };
        delete next[fieldId];
        return next;
      });
      setSourceSnapshots((prev) => ({ ...prev, [fieldId]: sourceText }));
      if (viewLanguage !== "source") {
        setViewLanguage("source");
      }
    }
  }, [viewLanguage, sourceSnapshots]);

  /**
   * Translate a specific text field
   */
  const translateField = useCallback(async (fieldId, sourceText, targetLanguage) => {
    if (!sourceText || !sourceText.trim()) {
      return;
    }

    // Check if already cached
    if (translations[fieldId]?.[targetLanguage] && sourceSnapshots[fieldId] === sourceText) {
      return; // Already translated, no need to do anything
    }

    // Check if already translating this field
    if (isTranslating[fieldId]) {
      return;
    }

    setIsTranslating((prev) => ({ ...prev, [fieldId]: true }));
    setTranslationErrors((prev) => {
      const next = { ...prev };
      delete next[fieldId];
      return next;
    });

    try {
      const translated = await translateText(sourceText, targetLanguage, null);
      setTranslations((prev) => ({
        ...prev,
        [fieldId]: {
          ...(prev[fieldId] || {}),
          [targetLanguage]: translated,
        },
      }));
      setSourceSnapshots((prev) => ({ ...prev, [fieldId]: sourceText }));
    } catch (e) {
      setTranslationErrors((prev) => ({
        ...prev,
        [fieldId]: e.message || "Translation failed",
      }));
    } finally {
      setIsTranslating((prev) => {
        const next = { ...prev };
        delete next[fieldId];
        return next;
      });
    }
  }, [translations, sourceSnapshots, isTranslating]);

  /**
   * Get translated text for a field, or return source if not translated
   */
  const getTranslatedText = useCallback((fieldId, sourceText) => {
    if (viewLanguage === "source") {
      return sourceText;
    }
    return translations[fieldId]?.[viewLanguage] || sourceText;
  }, [viewLanguage, translations]);

  /**
   * Check if a field has a cached translation for the current language
   */
  const hasTranslation = useCallback((fieldId) => {
    return Boolean(translations[fieldId]?.[viewLanguage]);
  }, [viewLanguage, translations]);

  /**
   * Check if any field is currently being translated
   */
  const isAnyTranslating = Object.values(isTranslating).some(Boolean);

  return {
    viewLanguage,
    setViewLanguage,
    languages: effectiveLanguages,
    translateField,
    getTranslatedText,
    hasTranslation,
    resetFieldTranslation,
    isTranslating,
    isAnyTranslating,
    translationErrors,
  };
}
