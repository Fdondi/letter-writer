import { fetchWithHeartbeat } from "./apiHelpers.js";

export async function translateText(text, targetLanguage = "de", sourceLanguage = null) {
  if (!text) return "";

  try {
    const result = await fetchWithHeartbeat("/api/translate/", {
      method: "POST",
      body: JSON.stringify({
        text,
        target_language: targetLanguage,
        source_language: sourceLanguage,
      }),
    });

    return result.data.translation ?? "";
  } catch (error) {
    // fetchWithHeartbeat already handles error parsing
    throw new Error(error.message || "Translation request failed");
  }
}

