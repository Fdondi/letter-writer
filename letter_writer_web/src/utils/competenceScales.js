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

/** Per need label: "linear" or "log" for scoring. Default "expected" → "log", others → "linear". */
export const DEFAULT_NEED_SCALE = {
  critical: "linear",
  "nice to have": "linear",
  expected: "log",
  useful: "linear",
  necessary: "linear",
  "marginally useful": "linear",
};

/** Short semantic descriptions for each need category, used in extraction prompts. */
export const DEFAULT_NEED_SEMANTICS = {
  critical: "central to the job",
  expected: "necessary, but not specific to the job",
  "nice to have": "desirable but not required",
  useful: "useful but not central",
  necessary: "required for the role",
  "marginally useful": "optional, slight plus",
};

function mergeNeedScale(need, stored) {
  const out = {};
  for (const k of Object.keys(need)) {
    if (stored && (stored[k] === "log" || stored[k] === "linear")) out[k] = stored[k];
    else if (DEFAULT_NEED_SCALE[k]) out[k] = DEFAULT_NEED_SCALE[k];
    else out[k] = "linear";
  }
  return out;
}

function mergeNeedSemantics(need, stored) {
  const out = {};
  for (const k of Object.keys(need)) {
    if (stored && k in stored && typeof stored[k] === "string") out[k] = stored[k].trim();
    else if (DEFAULT_NEED_SEMANTICS[k]) out[k] = DEFAULT_NEED_SEMANTICS[k];
    else out[k] = "";
  }
  return out;
}

export function getScaleConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return {
        need: { ...DEFAULT_NEED },
        level: { ...DEFAULT_LEVEL },
        needScale: { ...DEFAULT_NEED_SCALE },
        needSemantics: { ...DEFAULT_NEED_SEMANTICS },
      };
    }
    const parsed = JSON.parse(raw);
    const need = parsed.need && Object.keys(parsed.need).length ? parsed.need : { ...DEFAULT_NEED };
    const level = parsed.level && Object.keys(parsed.level).length ? parsed.level : { ...DEFAULT_LEVEL };
    const needScale = mergeNeedScale(need, parsed.needScale);
    const needSemantics = mergeNeedSemantics(need, parsed.needSemantics);
    return { need, level, needScale, needSemantics };
  } catch {
    return {
      need: { ...DEFAULT_NEED },
      level: { ...DEFAULT_LEVEL },
      needScale: { ...DEFAULT_NEED_SCALE },
      needSemantics: { ...DEFAULT_NEED_SEMANTICS },
    };
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

/** Map x in [1,5] to [1,5] via log(1+x). Used for "expected" importance. */
function logScaleImportance(x) {
  if (x == null || x < 1 || x > 5) return x;
  const ln = Math.log;
  const a = 4 / ln(3);
  const b = 1 - a * ln(2);
  const y = a * ln(1 + x) + b;
  return Math.max(1, Math.min(5, y));
}

/**
 * Build competence_ratings for profile save: { skill: cv_fit 1-5 } with user overrides applied.
 * Need is job-specific and not stored.
 */
export function buildCompetenceRatingsForProfile(competences, requirements, overrides, scaleConfig) {
  if (!competences || typeof competences !== "object") return {};
  const cfg = scaleConfig || getScaleConfig();
  const out = {};
  const skills = Array.isArray(requirements) ? requirements : Object.keys(competences);
  for (const skill of skills) {
    const s = (skill || "").trim();
    if (!s) continue;
    const val = competences[s];
    const o = overrides?.[s];
    let n;
    if (o?.presence != null && o.presence >= 1 && o.presence <= 5) {
      n = Math.round(o.presence);
    } else {
      const num = toNumeric(val, cfg);
      n = num.presence != null ? Math.round(num.presence) : 3;
    }
    out[s] = Math.max(1, Math.min(5, n));
  }
  return out;
}

/**
 * Importance for scoring (sort, weighted avg). Uses needScale: "log" → logarithmic, else linear.
 * Uses raw need label from competences[skill]; overrides only change the numeric value.
 */
export function getEffectiveImportance(skill, competences, scaleConfig, overrides) {
  const val = competences[skill];
  const needLabel = typeof val === "object" && val != null && "need" in val ? val.need : null;
  const { importance } = getEffectiveRating(skill, competences, scaleConfig, overrides);
  if (importance == null) return null;
  const scale = scaleConfig?.needScale?.[needLabel];
  if (scale === "log") {
    return logScaleImportance(importance);
  }
  return importance;
}
