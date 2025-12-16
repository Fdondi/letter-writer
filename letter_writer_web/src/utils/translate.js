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
    const message = await response.text();
    throw new Error(message || "Translation request failed");
  }

  const payload = await response.json();
  return Array.isArray(payload.translations) ? payload.translations[0] : "";
}

