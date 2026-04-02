/**
 * Vendor-flow feedback: each category is a list of { id, observation, type, status?, context_field?, user_context?, user_instructions? }
 * with type ALREADY_GOOD | PLEASE_FIX. Legacy string feedback is normalized client-side.
 */

export const FEEDBACK_TYPES = {
  ALREADY_GOOD: "ALREADY_GOOD",
  PLEASE_FIX: "PLEASE_FIX",
};

export const CONTEXT_SOURCES = ["CV", "EXAMPLE", "BACKGROUND_RESEARCH"];

export function newId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeContextSource(raw) {
  const s = String(raw ?? "").trim().toUpperCase();
  if (CONTEXT_SOURCES.includes(s)) return s;
  return "CV";
}

function normalizeContextItems(rawItems) {
  const arr = Array.isArray(rawItems) ? rawItems : [];
  const out = [];
  for (const it of arr) {
    if (typeof it === "string") {
      const text = String(it ?? "").trimEnd();
      if (text.trim()) out.push({ text, source: "CV" });
      continue;
    }
    if (it && typeof it === "object") {
      const text = String(it.text ?? "").trimEnd();
      if (!text.trim()) continue;
      out.push({ text, source: normalizeContextSource(it.source) });
    }
  }
  return out;
}

/**
 * @param {unknown} raw
 * @param {string} [categoryKey] - prefix for stable ids when server omitted id (legacy lists)
 * @returns {{ id: string, observation: string, type: string }[]}
 */
export function normalizeCategoryItems(raw, categoryKey = "") {
  if (raw == null) return [];
  if (Array.isArray(raw)) {
    return raw
      .map((it, idx) => {
        if (!it || typeof it !== "object") return null;
        const observation = String(it.observation ?? "").trim();
        const typ = String(it.type ?? "").toUpperCase();
        if (typ !== FEEDBACK_TYPES.ALREADY_GOOD && typ !== FEEDBACK_TYPES.PLEASE_FIX) return null;
        if (typ === FEEDBACK_TYPES.PLEASE_FIX && !observation) return null;
        if (typ === FEEDBACK_TYPES.ALREADY_GOOD && !observation) return null;
        const existing = String(it.id ?? "").trim();
        const id = existing || (categoryKey ? `${categoryKey}-${idx}` : newId());
        const statusRaw = String(it.status ?? "").toUpperCase().trim();
        let status =
          statusRaw === "NOT_NEEDED" || statusRaw === "SUFFICIENT" || statusRaw === "INPUT_NEEDED"
            ? statusRaw
            : "NOT_NEEDED";

        const cf = it.context_field && typeof it.context_field === "object" ? it.context_field : null;
        const rawCfItems = normalizeContextItems(cf?.items);

        // Server may send NOT_NEEDED while the user is adding rows in the UI (including empty placeholders).
        if (status === "NOT_NEEDED" && rawCfItems.length > 0) {
          status = "SUFFICIENT";
        }

        // Keep rows for SUFFICIENT / INPUT_NEEDED (including empty strings while editing).
        // NOT_NEEDED always clears context_field.
        let contextItems = [];
        if (status === "NOT_NEEDED") {
          contextItems = [];
        } else {
          contextItems = rawCfItems.map((x) => ({ text: String(x.text ?? "").trimEnd(), source: normalizeContextSource(x.source) }));
        }

        if (status === "SUFFICIENT" && contextItems.length === 0) {
          status = "NOT_NEEDED";
        }

        // Preserve exactly what the user typed; do not trim (otherwise trailing spaces disappear).
        const userContext = status === "INPUT_NEEDED" ? String(it.user_context ?? "") : "";
        const userInstructions = status === "INPUT_NEEDED" ? String(it.user_instructions ?? "").trim() : "";

        return {
          id,
          observation,
          type: typ,
          status,
          context_field: { items: contextItems },
          user_context: userContext,
          user_instructions: userInstructions,
        };
      })
      .filter(Boolean);
  }
  if (typeof raw === "string") {
    const t = raw.trim();
    if (!t) return [];
    const u = t.toUpperCase();
    if (u.endsWith("NO COMMENT") || u.endsWith("SKIP")) return [];
    if (u.endsWith("PLEASE FIX")) {
      const obs = t.slice(0, -"PLEASE FIX".length).trim();
      if (!obs) return [];
      return [
        {
          id: categoryKey ? `${categoryKey}-legacy-0` : newId(),
          observation: obs,
          type: FEEDBACK_TYPES.PLEASE_FIX,
        },
      ];
    }
    return [
      {
        id: categoryKey ? `${categoryKey}-legacy-0` : newId(),
        observation: t,
        type: FEEDBACK_TYPES.PLEASE_FIX,
      },
    ];
  }
  return [];
}

/**
 * @param {Record<string, unknown>} feedback
 * @param {Record<string, unknown>} overrides
 * @param {string} key
 */
export function mergeCategoryItems(feedback, overrides, key) {
  const raw = overrides[key] !== undefined ? overrides[key] : feedback[key];
  return normalizeCategoryItems(raw, key);
}

export function categoryHasPleaseFix(items) {
  return items.some((it) => it.type === FEEDBACK_TYPES.PLEASE_FIX);
}

function itemIsApproved(it, itemApprovals) {
  if (!it || it.type !== FEEDBACK_TYPES.PLEASE_FIX) return true;
  const status = String(it.status || "").toUpperCase();
  if (status === "INPUT_NEEDED") {
    // Once the user has provided the required info, treat the item as approved.
    // Approval is UI-local state and shouldn't block progress after reload.
    return String(it.user_context || "").trim().length > 0;
  }
  return itemApprovals[it.id] === true;
}

/** Only PLEASE_FIX items must be explicitly approved; ALREADY_GOOD is informational. */
export function categoryAllItemsApproved(items, itemApprovals) {
  if (items.length === 0) return true;
  return items.every((it) => itemIsApproved(it, itemApprovals));
}

export function findNextUnseenCategory(currentKey, feedbackKeys, feedback, overrides, itemApprovals) {
  if (feedbackKeys.length === 0) return null;
  const start = feedbackKeys.indexOf(currentKey);
  const base = start >= 0 ? start : 0;
  for (let i = 1; i <= feedbackKeys.length; i++) {
    const k = feedbackKeys[(base + i) % feedbackKeys.length];
    const items = mergeCategoryItems(feedback, overrides, k);
    const fixItems = items.filter((it) => it.type === FEEDBACK_TYPES.PLEASE_FIX);
    if (fixItems.length === 0) continue;
    if (fixItems.some((it) => !itemIsApproved(it, itemApprovals))) return k;
  }
  return null;
}

/**
 * If categoryKey has no pending PLEASE_FIX (none left, or all approved), return the next tab
 * that still has unapproved critiques. Pass nextItems + merged itemApprovals for the update
 * you just applied; overrides must reflect nextItems for categoryKey so this stays correct
 * before React re-renders (e.g. after remove/skip).
 */
export function selectNextTabIfCategoryDone(
  activeFeedbackKey,
  feedbackKeys,
  feedback,
  feedbackOverrides,
  categoryKey,
  nextItems,
  itemApprovals,
) {
  const nextOverrides = { ...feedbackOverrides, [categoryKey]: nextItems };
  const merged = mergeCategoryItems(feedback, nextOverrides, categoryKey);
  const fixItems = merged.filter((it) => it.type === FEEDBACK_TYPES.PLEASE_FIX);
  const hasPending =
    fixItems.length > 0 && fixItems.some((it) => !itemIsApproved(it, itemApprovals));
  if (hasPending) return null;
  return findNextUnseenCategory(
    activeFeedbackKey,
    feedbackKeys,
    feedback,
    nextOverrides,
    itemApprovals,
  );
}

/**
 * Build one personal_data.extra_info row from a normalized feedback item (user-supplied parts only).
 * @param {string} categoryKey
 * @param {{ id: string, observation?: string, user_context?: string, user_instructions?: string, context_field?: { items?: unknown[] } }} it
 * @returns {Record<string, unknown> | null}
 */
export function extractFeedbackEntryToExtraInfo(categoryKey, it) {
  const ucRaw = String(it.user_context ?? "");
  const uc = ucRaw.trim();
  const ui = String(it.user_instructions ?? "").trim();
  const rawLines = Array.isArray(it?.context_field?.items)
    ? it.context_field.items.map((x) => (typeof x === "string" ? String(x ?? "") : String(x?.text ?? "")))
    : [];
  const ctxLinesNonEmpty = rawLines.map((s) => s.trim()).filter(Boolean);
  if (!uc && !ui && ctxLinesNonEmpty.length === 0) {
    return null;
  }
  return {
    id: String(it.id),
    source: "feedback",
    category: categoryKey,
    observation: String(it.observation ?? "").trim(),
    user_context: ucRaw,
    user_instructions: ui,
    context_lines: rawLines,
    manual_text: "",
  };
}

/**
 * Merge feedback-derived rows into existing extra_info (manual rows keep stable ids; feedback upserts by item id).
 * @param {unknown[]} existing
 * @param {Record<string, unknown>} feedback
 * @param {Record<string, unknown>} overrides
 * @param {string[]} feedbackKeys
 */
export function mergeExtraInfoFromFeedback(existing, feedback, overrides, feedbackKeys) {
  const map = new Map((Array.isArray(existing) ? existing : []).map((e) => [String(e.id), { ...e }]));
  const seenFeedbackIds = new Set();
  for (const key of feedbackKeys) {
    const items = mergeCategoryItems(feedback, overrides, key);
    for (const it of items) {
      seenFeedbackIds.add(String(it.id));
      const extracted = extractFeedbackEntryToExtraInfo(key, it);
      if (extracted) {
        map.set(String(it.id), extracted);
      } else {
        const prev = map.get(String(it.id));
        if (prev && prev.source === "feedback") {
          map.delete(String(it.id));
        }
      }
    }
  }
  for (const [id, entry] of [...map.entries()]) {
    if (entry.source === "feedback" && !seenFeedbackIds.has(id)) {
      map.delete(id);
    }
  }
  return Array.from(map.values());
}
