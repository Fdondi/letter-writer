import { useState, useEffect, useCallback } from "react";
import { translateText } from "./translate";
import { useLanguages } from "../contexts/LanguageContext";

export const DEFAULT_LANGUAGES = [
  { code: "de", label: "DE", color: "#3b82f6", enabled: true },
  { code: "en", label: "EN", color: "#6366f1", enabled: true },
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
  const [viewLanguage, setViewLanguage] = useState("source"); // Global view language (for backward compatibility)
  const [fieldViewLanguages, setFieldViewLanguages] = useState({}); // Map of fieldId -> viewLanguage
  const [translations, setTranslations] = useState({}); // Map of fieldId -> {langCode -> translatedText}
  const [isTranslating, setIsTranslating] = useState({}); // Map of fieldId -> boolean
  const [translationErrors, setTranslationErrors] = useState({}); // Map of fieldId -> error message
  const [sourceSnapshots, setSourceSnapshots] = useState({}); // Map of fieldId -> last source text

  /**
   * Get view language for a specific field (per-field or global fallback)
   */
  const getFieldViewLanguage = useCallback((fieldId) => {
    return fieldViewLanguages[fieldId] ?? viewLanguage;
  }, [fieldViewLanguages, viewLanguage]);

  /**
   * Set view language for a specific field
   */
  const setFieldViewLanguage = useCallback((fieldId, language) => {
    setFieldViewLanguages((prev) => ({
      ...prev,
      [fieldId]: language,
    }));
  }, []);

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
      // Reset field-specific view language to source
      setFieldViewLanguages((prev) => {
        const next = { ...prev };
        next[fieldId] = "source";
        return next;
      });
    }
  }, [sourceSnapshots]);

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
    const fieldViewLang = getFieldViewLanguage(fieldId);
    if (fieldViewLang === "source") {
      return sourceText;
    }
    return translations[fieldId]?.[fieldViewLang] || sourceText;
  }, [getFieldViewLanguage, translations]);

  /**
   * Check if a field has a cached translation for the current language
   */
  const hasTranslation = useCallback((fieldId, language = null) => {
    const lang = language ?? getFieldViewLanguage(fieldId);
    return Boolean(translations[fieldId]?.[lang]);
  }, [getFieldViewLanguage, translations]);

  /**
   * Check if any field is currently being translated
   */
  const isAnyTranslating = Object.values(isTranslating).some(Boolean);

  return {
    viewLanguage,
    setViewLanguage,
    getFieldViewLanguage,
    setFieldViewLanguage,
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
