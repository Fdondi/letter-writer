/**
 * Vendor-flow feedback: each category is a list of { id, observation, type, status?, context_field?, user_context?, user_instructions? }
 * with type ALREADY_GOOD | PLEASE_FIX. Legacy string feedback is normalized client-side.
 */

export const FEEDBACK_TYPES = {
  ALREADY_GOOD: "ALREADY_GOOD",
  PLEASE_FIX: "PLEASE_FIX",
};

export function newId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
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
        const cfItems = Array.isArray(cf?.items) ? cf.items.map((x) => String(x ?? "").trim()).filter(Boolean) : [];

        // Enforce invariants to keep UI logic simple.
        const contextItems = status === "NOT_NEEDED" ? [] : cfItems;
        if (status === "SUFFICIENT" && contextItems.length === 0) status = "NOT_NEEDED";

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

/** Only PLEASE_FIX items must be explicitly approved; ALREADY_GOOD is informational. */
export function categoryAllItemsApproved(items, itemApprovals) {
  if (items.length === 0) return true;
  return items.every((it) => {
    if (it.type !== FEEDBACK_TYPES.PLEASE_FIX) return true;
    if (String(it.status || "").toUpperCase() === "INPUT_NEEDED") {
      const filled = String(it.user_context || "").trim().length > 0;
      if (!filled) return false;
    }
    return itemApprovals[it.id] === true;
  });
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
    if (fixItems.some((it) => !itemApprovals[it.id])) return k;
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
    fixItems.length > 0 && fixItems.some((it) => itemApprovals[it.id] !== true);
  if (hasPending) return null;
  return findNextUnseenCategory(
    activeFeedbackKey,
    feedbackKeys,
    feedback,
    nextOverrides,
    itemApprovals,
  );
}
