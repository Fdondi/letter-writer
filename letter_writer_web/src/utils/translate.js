import { fetchWithHeartbeat } from "./apiHelpers.js";

/**
 * @param {string} text
 * @param {string} targetLanguage language code (e.g. "de")
 * @param {string|null} sourceLanguage
 * @param {object} [options]
 * @param {string} [options.target_level] CEFR level override (e.g. "B2")
 * @param {string} [options.language_instructions]
 * @param {string} [options.provider] "google" | "llm"
 */
export async function translateText(text, targetLanguage = "de", sourceLanguage = null, options = {}) {
  if (!text) return { translation: "", warning: null, levelApplied: null };

  const body = {
    text,
    target_language: targetLanguage,
    source_language: sourceLanguage,
  };
  if (options.target_level) body.target_level = options.target_level;
  if (options.language_instructions) body.language_instructions = options.language_instructions;
  if (options.provider) body.provider = options.provider;

  try {
    const result = await fetchWithHeartbeat("/api/translate/", {
      method: "POST",
      body: JSON.stringify(body),
    });

    return {
      translation: result.data.translation ?? "",
      warning: result.data.warning ?? null,
      levelApplied: result.data.level_applied ?? null,
      provider: result.data.provider ?? null,
    };
  } catch (error) {
    throw new Error(error.message || "Translation request failed");
  }
}
