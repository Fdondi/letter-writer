export function normalizeForMatch(input) {
  const s = (input ?? "").toString();
  if (!s.trim()) return "";
  // NFD splits accents into combining marks; strip them for robust matching across translations/edits.
  const noDiacritics = s.normalize("NFD").replace(/\p{Diacritic}/gu, "");
  return noDiacritics
    .toLowerCase()
    .replace(/['’`]/g, "") // common apostrophes
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function textMentionsPhrase(haystack, phrase) {
  const h = normalizeForMatch(haystack);
  const p = normalizeForMatch(phrase);
  if (!h || !p) return false;
  const paddedHay = ` ${h} `;
  const paddedNeedle = ` ${p} `;
  return paddedHay.includes(paddedNeedle);
}
