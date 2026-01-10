import { fetchWithHeartbeat } from "./apiHelpers.js";

export async function translateText(text, targetLanguage = "de", sourceLanguage = null) {
  if (!text) return "";

  try {
    const result = await fetchWithHeartbeat("/api/translate/", {
      method: "POST",
      body: JSON.stringify({
        texts: [text],
        target_language: targetLanguage,
        // Let the API auto-detect if sourceLanguage is null.
        source_language: sourceLanguage,
      }),
    });

    const payload = result.data;
    return Array.isArray(payload.translations) ? payload.translations[0] : "";
  } catch (error) {
    // fetchWithHeartbeat already handles error parsing
    throw new Error(error.message || "Translation request failed");
  }
}

