export async function translateText(text, targetLanguage = "de", sourceLanguage = null) {
  if (!text) return "";

  const response = await fetch("/api/translate/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      texts: [text],
      target_language: targetLanguage,
      // Let the API auto-detect if sourceLanguage is null.
      source_language: sourceLanguage,
    }),
  });

  if (!response.ok) {
    // Try to parse JSON error response (backend returns {"detail": "..."})
    const text = await response.text();
    let errorMessage = "Translation request failed";
    try {
      const json = JSON.parse(text);
      errorMessage = json.detail || json.message || text || errorMessage;
    } catch {
      errorMessage = text || errorMessage;
    }
    throw new Error(errorMessage);
  }

  const payload = await response.json();
  return Array.isArray(payload.translations) ? payload.translations[0] : "";
}

