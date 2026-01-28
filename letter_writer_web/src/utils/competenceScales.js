/**
 * Competence rating scales: need (job requirement) and level (candidate from CV).
 * User can override label → numeric mapping in settings; we use these as defaults.
 */

const STORAGE_KEY = "competenceScales";

export const DEFAULT_NEED = {
  critical: 5,
  "nice to have": 2,
  expected: 4,
  useful: 3,
  necessary: 4,
  "marginally useful": 1,
};

export const DEFAULT_LEVEL = {
  Newbie: 1,
  Amateur: 2,
  "Brief experience": 3,
  Professional: 4,
  "Senior professional": 5,
};

export function getScaleConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { need: { ...DEFAULT_NEED }, level: { ...DEFAULT_LEVEL } };
    const parsed = JSON.parse(raw);
    const need = parsed.need && Object.keys(parsed.need).length ? parsed.need : { ...DEFAULT_NEED };
    const level = parsed.level && Object.keys(parsed.level).length ? parsed.level : { ...DEFAULT_LEVEL };
    return { need, level };
  } catch {
    return { need: { ...DEFAULT_NEED }, level: { ...DEFAULT_LEVEL } };
  }
}

export function setScaleConfig(config) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch (e) {
    console.warn("Failed to save competence scales:", e);
  }
}

/**
 * Convert a single competence value to numeric { presence, importance }.
 * - New format: { need, level } (strings) → use scale config.
 * - Legacy: { presence, importance } (numbers) → pass through.
 * - Legacy: number (presence only) → importance 3.
 */
export function toNumeric(val, scaleConfig) {
  if (val == null) return { presence: null, importance: null };
  if (typeof val === "number") {
    return { presence: val, importance: 3 };
  }
  if (typeof val !== "object") return { presence: null, importance: null };

  if ("presence" in val && "importance" in val) {
    return { presence: val.presence, importance: val.importance };
  }

  const cfg = scaleConfig || getScaleConfig();
  const need = val.need != null ? cfg.need[val.need] : null;
  const level = val.level != null ? cfg.level[val.level] : null;
  return { presence: level ?? null, importance: need ?? null };
}

/**
 * Effective numeric rating for a skill, merging user overrides.
 * overrides: { [skill]: { presence?: number, importance?: number } }
 */
export function getEffectiveRating(skill, competences, scaleConfig, overrides) {
  const base = toNumeric(competences[skill], scaleConfig);
  const o = overrides?.[skill];
  return {
    presence: o?.presence != null ? o.presence : base.presence,
    importance: o?.importance != null ? o.importance : base.importance,
  };
}
