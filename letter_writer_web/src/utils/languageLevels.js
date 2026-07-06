export const CEFR_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2", "native"];

export const DEFAULT_LEVEL_BY_CODE = {
  de: "B2",
  en: "C2",
};

export const DEFAULT_INSTRUCTIONS_BY_CODE = {
  de: "Verwende echte Umlaute (ä, ö, ü, ß) — niemals ae, oe, ue oder ss als Ersatz.",
};

export function defaultLevelForCode(code) {
  const c = String(code || "").trim().toLowerCase();
  return DEFAULT_LEVEL_BY_CODE[c] || "B2";
}

export function defaultInstructionsForCode(code) {
  const c = String(code || "").trim().toLowerCase();
  return DEFAULT_INSTRUCTIONS_BY_CODE[c] || "";
}

export function normalizeLanguageEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const code = String(raw.code || "").trim().toLowerCase();
  if (!code) return null;
  const levelRaw = String(raw.level || "").trim();
  const level = levelRaw.toLowerCase() === "native" ? "native" : (CEFR_LEVELS.includes(levelRaw.toUpperCase()) ? levelRaw.toUpperCase() : defaultLevelForCode(code));
  let instructions = String(raw.instructions ?? "");
  if (!instructions.trim()) {
    instructions = defaultInstructionsForCode(code);
  }
  return {
    code,
    label: String(raw.label || code.toUpperCase()),
    color: raw.color,
    enabled: raw.enabled !== false,
    level,
    instructions,
  };
}

export function normalizeLanguages(list) {
  if (!Array.isArray(list)) return [];
  return list.map(normalizeLanguageEntry).filter(Boolean);
}

/** Params sent with each translate API call so level is honored immediately. */
export function getLanguageTranslateParams(languages, targetCode, translationProvider = null) {
  const code = String(targetCode || "").trim().toLowerCase();
  if (!code || code === "source") return {};
  const entry = (languages || []).find((l) => l.code === code);
  const params = {};
  if (entry?.level) params.target_level = entry.level;
  if (entry?.instructions) params.language_instructions = entry.instructions;
  if (translationProvider === "llm" || translationProvider === "google") {
    params.provider = translationProvider;
  }
  return params;
}
