/**
 * Pure helpers for autocomplete editor state (testable without React).
 */

export function truncateAutocompleteSuggestion(text, { maxWords, stopOnPeriod }) {
  if (!text) return { chunk: "", truncatedBy: null };
  let out = String(text).trim();
  if (!out) return { chunk: "", truncatedBy: null };
  let truncatedBy = null;
  if (stopOnPeriod) {
    const m = out.match(/\.(?:\s|$)/);
    if (m && m.index != null && m.index + m[0].length < out.length) {
      truncatedBy = "period";
      out = out.slice(0, m.index + m[0].length).trimEnd();
    }
  }
  const words = out.split(/\s+/).filter(Boolean);
  if (maxWords > 0 && words.length > maxWords) {
    out = words.slice(0, maxWords).join(" ");
    truncatedBy = truncatedBy ? `${truncatedBy},max_words` : "max_words";
  }
  if (out && stopOnPeriod && truncatedBy === "period" && !/[.!?]$/.test(out)) {
    out = `${out}.`;
  }
  return { chunk: out, truncatedBy };
}

/**
 * Next display chunk from a cached long completion (server uses the same rules).
 * @returns {{ chunk: string, newOffset: number, truncatedBy: string | null, hasMore: boolean }}
 */
export function sliceNextAutocompleteChunk(raw, offset, { maxWords, stopOnPeriod }) {
  const rawText = String(raw || "");
  const off = Math.max(0, offset || 0);
  if (off >= rawText.length) {
    return { chunk: "", newOffset: off, truncatedBy: null, hasMore: false };
  }
  const rest = rawText.slice(off);
  const leading = rest.length - rest.trimStart().length;
  const work = rest.trimStart();
  if (!work) {
    return { chunk: "", newOffset: off, truncatedBy: null, hasMore: false };
  }
  const { chunk, truncatedBy } = truncateAutocompleteSuggestion(work, {
    maxWords,
    stopOnPeriod,
  });
  if (!chunk) {
    return { chunk: "", newOffset: off, truncatedBy: null, hasMore: false };
  }
  let consumedInWork = chunk.length;
  if (!work.startsWith(chunk)) {
    consumedInWork = chunk.split(/\s+/).filter(Boolean).join(" ").length;
  }
  const newOffset = off + leading + consumedInWork;
  const hasMore = Boolean(rawText.slice(newOffset).trim());
  return { chunk, newOffset, truncatedBy, hasMore };
}

export function shouldExtendAutocompleteCache(consumedOffset, rawLength) {
  if (!rawLength || consumedOffset <= 0) return false;
  return consumedOffset >= Math.floor(rawLength * AUTOCOMPLETE_CACHE_EXTEND_THRESHOLD);
}

/** Cache entries seeded from the hidden section proposal (not the completion LLM). */
export const PROPOSAL_AUTOCOMPLETE_CACHE_SOURCE = "__proposal__";

export function isProposalAutocompleteCache(cache) {
  return cache?.modelKey === PROPOSAL_AUTOCOMPLETE_CACHE_SOURCE;
}

/** True when the user edited the paragraph after the last proposal-aligned insert. */
export function isSectionProposalStale(section) {
  if (!section?.proposal?.trim()) return false;
  const source = section.proposalSourceBody;
  if (source === undefined || source === null) return false;
  return String(section.body || "") !== String(source);
}

/** Hidden proposal can drive Tab chunks until the user edits the paragraph. */
export function canUseProposalAutocompleteBuffer(section) {
  return Boolean(section?.proposal?.trim()) && !isSectionProposalStale(section);
}

/** Smaller completion model runs only after a manual edit (or when no proposal exists). */
export function shouldUseCompletionModelForSection(section) {
  if (!section?.proposal?.trim()) return true;
  return isSectionProposalStale(section);
}

/**
 * Remaining hidden-proposal text to stream at the cursor (first autocomplete buffer).
 * @returns {string} Suffix after aligned body prefix, or "" if unusable / stale.
 */
export function buildSectionProposalAutocompleteBuffer(section, cursorInSection) {
  if (!canUseProposalAutocompleteBuffer(section)) return "";
  const proposal = String(section.proposal || "").trim();
  const body = String(section.body || "");
  const cur = Math.max(0, Math.min(cursorInSection ?? body.length, body.length));
  const typedPrefix = body.slice(0, cur);
  if (!typedPrefix) return proposal;
  if (proposal.startsWith(typedPrefix)) {
    return proposal.slice(typedPrefix.length).trimStart();
  }
  const trimmed = typedPrefix.replace(/\s+$/, "");
  if (trimmed && proposal.startsWith(trimmed)) {
    return proposal.slice(trimmed.length).trimStart();
  }
  return "";
}

export function createEmptyCompletionCache() {
  return { raw: "", offset: 0, prefixKey: "", modelKey: "" };
}

export function acceptSuggestion(text, cursor, suggestion) {
  const before = text.slice(0, cursor);
  const after = text.slice(cursor);
  const insert = suggestion || "";
  const needsSpace = insert.length > 0 && !insert.endsWith(" ");
  const addition = needsSpace ? `${insert} ` : insert;
  const nextText = before + addition + after;
  const nextCursor = before.length + addition.length;
  return { text: nextText, cursor: nextCursor, inserted: addition };
}

/**
 * Split a model suggestion into accepted vs rejected segments for history storage.
 * @param {string} suggestion - Full suggestion from the model (before user accept).
 * @param {string} acceptedInsert - Text actually inserted (may include trailing space).
 */
export function splitSuggestionAcceptance(suggestion, acceptedInsert) {
  const sug = String(suggestion ?? "");
  const acc = String(acceptedInsert ?? "");
  if (!sug.trim() && !acc.trim()) {
    return { accepted: "", rejected: [] };
  }
  if (!acc.trim()) {
    return { accepted: "", rejected: sug ? [sug] : [] };
  }
  const sugCore = sug.trimEnd();
  const accCore = acc.trimEnd();
  if (sugCore === accCore) {
    return { accepted: acc, rejected: [] };
  }
  if (sugCore.startsWith(accCore)) {
    const remainder = sugCore.slice(accCore.length).trimStart();
    return { accepted: acc, rejected: remainder ? [remainder] : [] };
  }
  return { accepted: acc, rejected: sug ? [sug] : [] };
}

/**
 * Tracks fixed LLM cache context once, then incremental suggestion accept/reject chunks.
 * Each chunk.text is the assembled letter body (section paragraphs) before that acceptance.
 */
export function createAutocompleteSuggestionHistory() {
  /** @type {string | null} */
  let fixedContext = null;
  /** @type {Array<{ text: string, accepted: string, rejected: string[], model?: string | null, cost?: number | null }>} */
  const chunks = [];
  /** @type {{ text: string, suggestion: string, model?: string | null, cost?: number | null } | null} */
  let pending = null;

  function setFixedContext(ctx) {
    const next = String(ctx || "").trim();
    if (!next || fixedContext) return;
    fixedContext = next;
  }

  function rejectPending() {
    if (!pending?.suggestion) {
      pending = null;
      return;
    }
    chunks.push({
      text: pending.text,
      accepted: "",
      rejected: [pending.suggestion],
      model: pending.model ?? null,
      cost: pending.cost ?? null,
    });
    pending = null;
  }

  function startPending({ text, suggestion, model, cost }) {
    rejectPending();
    const sug = String(suggestion ?? "").trim();
    if (!sug) return;
    pending = {
      text: String(text ?? ""),
      suggestion: sug,
      model: model ?? null,
      cost: typeof cost === "number" ? cost : null,
    };
  }

  function acceptPending(acceptedInsert) {
    if (!pending) return;
    const { accepted, rejected } = splitSuggestionAcceptance(pending.suggestion, acceptedInsert);
    if (accepted || rejected.length) {
      chunks.push({
        text: pending.text,
        accepted,
        rejected,
        model: pending.model ?? null,
        cost: pending.cost ?? null,
      });
    }
    pending = null;
  }

  function finalizeForSave() {
    rejectPending();
    return {
      fixed_context: fixedContext || "",
      chunks: chunks.map((c) => ({ ...c })),
    };
  }

  return { setFixedContext, startPending, acceptPending, rejectPending, finalizeForSave };
}

export function shouldAcceptOnSpace(hasSuggestion, shiftKey) {
  return Boolean(hasSuggestion) && !shiftKey;
}

/** True when the suggestion is already present at the cursor (e.g. memo replay after insert). */
export function suggestionAlreadyAtCursor(body, cursor, suggestion) {
  const text = String(body || "");
  const cur = Math.max(0, Math.min(cursor ?? text.length, text.length));
  const sug = String(suggestion || "").trim();
  if (!sug) return true;
  const after = text.slice(cur);
  if (after.startsWith(sug)) return true;
  if (after.startsWith(`${sug} `)) return true;
  return false;
}

export function resolveCompletionModel(completionModel, modelUsed, cycleModels) {
  const fromCycle = Array.isArray(cycleModels) ? cycleModels.find((m) => String(m || "").trim()) : "";
  return (
    String(completionModel || "").trim() ||
    String(modelUsed || "").trim() ||
    String(fromCycle || "").trim()
  );
}

export function parseCtrlLetterKey(event) {
  if (!event.ctrlKey || event.altKey || event.metaKey) {
    return null;
  }
  const key = event.key;
  if (key.length === 1 && /[a-zA-Z]/.test(key)) {
    return key.toUpperCase();
  }
  return null;
}

/** @deprecated use parseCtrlLetterKey */
export function parseShiftLetterKey(event) {
  if (!event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) {
    return null;
  }
  const key = event.key;
  if (key.length === 1 && /[a-zA-Z]/.test(key)) {
    return key.toUpperCase();
  }
  return null;
}

/** Ctrl+letter switches model any time (not only during an active suggestion). */
export function shouldHandleCtrlLetterShortcut(event) {
  return parseCtrlLetterKey(event) !== null;
}

/** @deprecated */
export function shouldHandleShiftLetterShortcut(hasSuggestion, event) {
  if (!hasSuggestion) return false;
  return parseShiftLetterKey(event) !== null;
}

export function nextCycleIndex(currentIndex, listLength) {
  if (!listLength) return 0;
  return (currentIndex + 1) % listLength;
}

export function parseModelKey(modelKey) {
  const raw = String(modelKey || "").trim();
  if (!raw) {
    return { vendor: "", modelId: "", reasoningEffort: "", composite: "" };
  }
  const slash = raw.indexOf("/");
  if (slash === -1) {
    return { vendor: raw.toLowerCase(), modelId: "", reasoningEffort: "", composite: raw.toLowerCase() };
  }
  const vendor = raw.slice(0, slash).toLowerCase();
  const rest = raw.slice(slash + 1);
  const at = rest.lastIndexOf("@");
  if (at >= 0) {
    const modelId = rest.slice(0, at);
    const reasoningEffort = rest.slice(at + 1);
    return {
      vendor,
      modelId,
      reasoningEffort,
      composite: formatModelKey(vendor, modelId, reasoningEffort),
    };
  }
  return {
    vendor,
    modelId: rest,
    reasoningEffort: "",
    composite: formatModelKey(vendor, rest, ""),
  };
}

export function formatModelKey(vendor, modelId, reasoningEffort) {
  const v = String(vendor || "").trim().toLowerCase();
  const m = String(modelId || "").trim();
  const effort = String(reasoningEffort || "").trim();
  if (!v) return "";
  if (!m) return v;
  const base = `${v}/${m}`;
  if (!effort || effort.toLowerCase() === "none" || effort.toLowerCase() === "off") {
    return base;
  }
  return `${base}@${effort}`;
}

export function buildGroupedModels(availableModels) {
  const grouped = {};
  const vendors = new Set();
  if (!availableModels || typeof availableModels !== "object") {
    return { grouped, vendors: [] };
  }
  Object.entries(availableModels).forEach(([vendorLabel, models]) => {
    if (!Array.isArray(models) || models.length === 0) return;
    const vendorKey = models[0].vendor_key || vendorLabel.toLowerCase().replace(/\s+/g, "");
    vendors.add(vendorKey);
    grouped[vendorKey] = models.map((m) => ({
      id: m.id,
      name: m.name || m.id,
      composite: `${m.vendor_key || vendorKey}/${m.id}`,
      vendorLabel,
      reasoningEfforts: Array.isArray(m.reasoning_efforts) ? m.reasoning_efforts : [],
      input: typeof m.input === "number" ? m.input : Number(m.input) || 0,
      output: typeof m.output === "number" ? m.output : Number(m.output) || 0,
    }));
  });
  return { grouped, vendors: [...vendors].sort() };
}

export function normalizeStoredModels(storedModels, roleDefaults) {
  const defaults = roleDefaults && typeof roleDefaults === "object" ? roleDefaults : {};
  const out = [];
  const seen = new Set();
  for (const entry of storedModels || []) {
    const raw = String(entry || "").trim();
    if (!raw) continue;
    const parsed = parseModelKey(raw.includes("/") ? raw : defaults[raw] || raw);
    const composite = parsed.modelId ? parsed.composite : defaults[parsed.vendor] || parsed.composite;
    if (composite && !seen.has(composite)) {
      seen.add(composite);
      out.push(composite);
    }
  }
  return out;
}

export function defaultCycleModels(roleDefaults) {
  const defaults = roleDefaults && typeof roleDefaults === "object" ? roleDefaults : {};
  return Object.values(defaults);
}

export function normalizeShortcutMap(rawMap, roleDefaults) {
  const defaults = roleDefaults && typeof roleDefaults === "object" ? roleDefaults : {};
  const out = {};
  if (!rawMap || typeof rawMap !== "object") return out;
  for (const [letter, model] of Object.entries(rawMap)) {
    const key = String(letter || "").trim().toUpperCase().slice(0, 1);
    const raw = String(model || "").trim();
    if (!key || !raw) continue;
    const parsed = parseModelKey(raw.includes("/") ? raw : defaults[raw] || raw);
    const composite = parsed.modelId ? parsed.composite : defaults[parsed.vendor] || parsed.composite;
    if (composite) out[key] = composite;
  }
  return out;
}

export const SHORTCUT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

export function assignShortcutLetters(cycleModels) {
  const used = new Set();
  const map = {};
  for (const composite of cycleModels || []) {
    const { vendor } = parseModelKey(composite);
    if (!vendor) continue;
    let idx = SHORTCUT_LETTERS.indexOf(vendor[0].toUpperCase());
    if (idx < 0) idx = 0;
    let letter = SHORTCUT_LETTERS[idx];
    while (used.has(letter) && idx < SHORTCUT_LETTERS.length - 1) {
      idx += 1;
      letter = SHORTCUT_LETTERS[idx];
    }
    if (used.has(letter)) continue;
    used.add(letter);
    map[letter] = composite;
  }
  return map;
}

/** Merge stored Ctrl+letter map with cycle models; vendor-initial letters fill gaps only. */
export function resolveShortcutMap(cycleModels, storedMap, roleDefaults) {
  const defaults = roleDefaults && typeof roleDefaults === "object" ? roleDefaults : {};
  const cycle = normalizeStoredModels(cycleModels || [], defaults);
  const normalizedStored = normalizeShortcutMap(storedMap, defaults);
  const derived = assignShortcutLetters(cycle);

  const modelToStoredLetter = {};
  for (const [letter, composite] of Object.entries(normalizedStored)) {
    if (cycle.includes(composite) && !modelToStoredLetter[composite]) {
      modelToStoredLetter[composite] = letter;
    }
  }

  const usedLetters = new Set();
  const out = {};

  for (const composite of cycle) {
    const letter = modelToStoredLetter[composite];
    if (letter && !usedLetters.has(letter)) {
      out[letter] = composite;
      usedLetters.add(letter);
    }
  }

  for (const composite of cycle) {
    if (Object.values(out).includes(composite)) continue;
    const defaultLetter = Object.entries(derived).find(([, model]) => model === composite)?.[0];
    if (defaultLetter && !usedLetters.has(defaultLetter)) {
      out[defaultLetter] = composite;
      usedLetters.add(defaultLetter);
      continue;
    }
    for (const letter of SHORTCUT_LETTERS) {
      if (!usedLetters.has(letter)) {
        out[letter] = composite;
        usedLetters.add(letter);
        break;
      }
    }
  }

  return out;
}

export function updateShortcutLetter(map, composite, newLetter) {
  const key = String(newLetter || "")
    .trim()
    .toUpperCase()
    .slice(0, 1);
  if (!key || !composite) return map || {};
  const next = { ...(map || {}) };
  const prevLetter = Object.entries(next).find(([, model]) => model === composite)?.[0];
  const occupant = next[key];
  if (prevLetter) delete next[prevLetter];
  if (occupant && occupant !== composite) {
    if (prevLetter) next[prevLetter] = occupant;
    else {
      const used = new Set(Object.keys(next));
      for (const letter of SHORTCUT_LETTERS) {
        if (!used.has(letter)) {
          next[letter] = occupant;
          break;
        }
      }
    }
  }
  next[key] = composite;
  return next;
}

export function shortcutMapsEqual(a, b) {
  const left = a && typeof a === "object" ? a : {};
  const right = b && typeof b === "object" ? b : {};
  const keysA = Object.keys(left).sort();
  const keysB = Object.keys(right).sort();
  if (keysA.length !== keysB.length) return false;
  return keysA.every((k) => left[k] === right[k]);
}

export function letterForCycleModel(composite, shortcutMap) {
  return Object.entries(shortcutMap || {}).find(([, model]) => model === composite)?.[0] || "";
}

export const SESSION_CYCLE_MODELS_KEY = "autocompleteFlowCycleModels";
export const SESSION_PLAN_MODEL_KEY = "autocompleteFlowPlanModel";
export const SESSION_CTRL_LETTER_MAP_KEY = "autocompleteFlowCtrlLetterMap";

export function readSessionCycleModels() {
  try {
    const raw = sessionStorage.getItem(SESSION_CYCLE_MODELS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeSessionCycleModels(models) {
  try {
    sessionStorage.setItem(SESSION_CYCLE_MODELS_KEY, JSON.stringify(models || []));
  } catch {
    /* ignore */
  }
}

export function readSessionPlanModel() {
  try {
    const raw = sessionStorage.getItem(SESSION_PLAN_MODEL_KEY);
    return raw ? String(raw).trim() : null;
  } catch {
    return null;
  }
}

export function readSessionCtrlLetterMap() {
  try {
    const raw = sessionStorage.getItem(SESSION_CTRL_LETTER_MAP_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function writeSessionCtrlLetterMap(map) {
  try {
    sessionStorage.setItem(SESSION_CTRL_LETTER_MAP_KEY, JSON.stringify(map || {}));
  } catch {
    /* ignore */
  }
}

export function writeSessionPlanModel(modelKey) {
  try {
    if (modelKey) sessionStorage.setItem(SESSION_PLAN_MODEL_KEY, String(modelKey));
    else sessionStorage.removeItem(SESSION_PLAN_MODEL_KEY);
  } catch {
    /* ignore */
  }
}

export function clearSessionCycleModels() {
  try {
    sessionStorage.removeItem(SESSION_CYCLE_MODELS_KEY);
  } catch {
    /* ignore */
  }
}

export function clearSessionPlanModel() {
  try {
    sessionStorage.removeItem(SESSION_PLAN_MODEL_KEY);
  } catch {
    /* ignore */
  }
}

export function clearStoredAutocompleteSections() {
  try {
    localStorage.removeItem(AUTOCOMPLETE_SECTIONS_KEY);
    localStorage.removeItem(LEGACY_AUTOCOMPLETE_TEXT_KEY);
  } catch {
    /* ignore */
  }
}

/** Clear browser autocomplete draft + session model picks (after letter saved). */
export function clearAutocompleteFlowCache() {
  clearStoredAutocompleteSections();
  clearSessionCycleModels();
  clearSessionPlanModel();
}

export function cycleModelsEqual(a, b) {
  const left = Array.isArray(a) ? a : [];
  const right = Array.isArray(b) ? b : [];
  if (left.length !== right.length) return false;
  return left.every((m, i) => m === right[i]);
}

export const AUTOCOMPLETE_CACHE_WORD_MULTIPLIER = 10;
export const AUTOCOMPLETE_CACHE_EXTEND_THRESHOLD = 0.8;

/** @typedef {{ id: string, title: string, description: string, body: string, plan?: string, proposal?: string, proposalSourceBody?: string }} AutocompleteSection */

export const DEFAULT_AUTOCOMPLETE_SECTIONS = [
  {
    id: "you-are-great",
    title: "You are great",
    description:
      "Show you understand what the company does and explain why you want to work with them.",
    body: "",
  },
  {
    id: "i-am-great",
    title: "I am great",
    description:
      "Show what you achieved that is relevant to the company and this position",
    body: "",
  },
  {
    id: "well-be-great",
    title: "We'll be great together",
    description: "Show specifically how your talents will help the company",
    body: "",
  },
  {
    id: "call-to-action",
    title: "Call to action",
    description: "Conclude with a brief nod to next steps.",
    body: "",
  },
];

export function createAutocompleteSection(overrides = {}) {
  const id =
    typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `section-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  return {
    id,
    title: "",
    description: "",
    body: "",
    plan: "",
    proposal: "",
    proposalSourceBody: "",
    ...overrides,
  };
}

export function cloneDefaultAutocompleteSections() {
  return DEFAULT_AUTOCOMPLETE_SECTIONS.map((s) => ({ ...s }));
}

const PREDEFINED_SECTION_IDS = new Set(
  DEFAULT_AUTOCOMPLETE_SECTIONS.map((s) => s.id)
);

/** True when the section is one of the built-in default letter sections. */
export function isPredefinedAutocompleteSection(section) {
  return PREDEFINED_SECTION_IDS.has(section?.id);
}

/** Indices of built-in default sections in the current sections array. */
export function getPredefinedSectionIndices(sections) {
  if (!Array.isArray(sections)) return [];
  return sections.reduce((indices, section, index) => {
    if (isPredefinedAutocompleteSection(section)) indices.push(index);
    return indices;
  }, []);
}

/** Final letter text for save / competence matching — bodies only. */
export function sectionsToBodyText(sections) {
  if (!Array.isArray(sections)) return "";
  return sections
    .map((s) => String(s?.body || "").trim())
    .filter(Boolean)
    .join("\n\n");
}

/** Full hidden-proposal text (one entry per section) for ai_letters storage. */
export function sectionsToProposalText(sections) {
  if (!Array.isArray(sections)) return "";
  return sections
    .map((s) => String(s?.proposal || "").trim())
    .filter(Boolean)
    .join("\n\n");
}

/**
 * Build one ai_letters entry for the autocomplete plan model + hidden proposal draft.
 * @returns {object | null}
 */
export function buildAutocompletePlanAiLetter(planModel, proposalText, planCost) {
  const text = String(proposalText || "").trim();
  const modelKey = String(planModel || "").trim();
  if (!text || !modelKey) return null;
  const { vendor, modelId, composite } = parseModelKey(modelKey);
  const vendorKey = vendor || "autocomplete";
  const model = modelId ? composite : modelKey;
  return {
    vendor: vendorKey,
    model,
    text,
    cost: typeof planCost === "number" && planCost > 0 ? planCost : null,
    rating: null,
    comment: "",
    chunks_used: 0,
    user_corrections: [],
  };
}

/** Markdown draft passed to autocomplete (titles/descriptions + partial bodies). */
export function buildAutocompleteDraftPrefix(sections, activeIndex, cursorInSection) {
  if (!sections?.length) return "";
  const idx = Math.max(0, Math.min(activeIndex, sections.length - 1));
  const blocks = ["Please continue:"];
  for (let i = 0; i <= idx; i += 1) {
    const sec = sections[i];
    const title = String(sec?.title || "").trim();
    const description = String(sec?.description || "").trim();
    const body = String(sec?.body || "");
    const bodySlice =
      i < idx ? body : body.slice(0, Math.max(0, Math.min(cursorInSection, body.length)));
    const lines = [];
    if (title) lines.push(`# ${title}`);
    if (description) lines.push(`## ${description}`);
    if (bodySlice) lines.push(bodySlice.replace(/\s+$/, ""));
    if (lines.length) blocks.push(lines.join("\n"));
  }
  return blocks.join("\n\n");
}

export const AUTOCOMPLETE_SECTIONS_KEY = "autocompleteFlowSections";
const LEGACY_AUTOCOMPLETE_TEXT_KEY = "autocompleteFlowText";

/** Stable key so autocomplete drafts do not leak across companies/jobs. */
export function buildAutocompleteDraftScope({
  companyName = "",
  jobTitle = "",
  jobText = "",
} = {}) {
  return [companyName, jobTitle, jobText]
    .map((part) => String(part || "").trim())
    .join("\x1e");
}

function normalizeStoredSections(parsed) {
  if (!Array.isArray(parsed) || parsed.length === 0) return null;
  return parsed.map((s) => ({
    id: s.id || createAutocompleteSection().id,
    title: s.title ?? "",
    description: s.description ?? "",
    body: s.body ?? "",
    plan: s.plan ?? "",
    proposal: s.proposal ?? "",
    proposalSourceBody: s.proposalSourceBody ?? "",
  }));
}

export function readStoredAutocompleteSections(draftScope) {
  const scope = String(draftScope ?? "");
  try {
    const raw = localStorage.getItem(AUTOCOMPLETE_SECTIONS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        if (parsed.scope === scope && Array.isArray(parsed.sections)) {
          const normalized = normalizeStoredSections(parsed.sections);
          if (normalized) return normalized;
        }
      } else if (!scope) {
        const normalized = normalizeStoredSections(parsed);
        if (normalized) return normalized;
      }
    }
    if (!scope) {
      const legacy = localStorage.getItem(LEGACY_AUTOCOMPLETE_TEXT_KEY);
      if (legacy) {
        const sections = cloneDefaultAutocompleteSections();
        sections[0] = { ...sections[0], body: legacy };
        return sections;
      }
    }
  } catch {
    /* ignore */
  }
  return cloneDefaultAutocompleteSections();
}

export function writeStoredAutocompleteSections(sections, draftScope) {
  try {
    const scope = String(draftScope ?? "");
    localStorage.setItem(
      AUTOCOMPLETE_SECTIONS_KEY,
      JSON.stringify({ scope, sections: sections || [] })
    );
  } catch {
    /* ignore */
  }
}
