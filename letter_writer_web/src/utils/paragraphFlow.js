/**
 * Paragraph flow state helpers (pure; the page owns React state).
 *
 * A "draft" is one option source: a whole unplanned letter (kind "letter") or one
 * "Generate another" continuation (kind "continuation"). Each draft holds paragraphs;
 * a regenerated paragraph is a sibling with `parentId` pointing at the slot's root.
 */
import { v4 as uuidv4 } from "uuid";
import { createTextDiff } from "./diff";
import { resolveQuoteSpan } from "./resolveQuoteSpan";
import { splitIntoParagraphs } from "./split";
import { AGENTIC_TOPICS } from "../constants/feedbackTopics";
import { FEEDBACK_TYPES, isLayaHidden } from "../components/phases/feedbackItemUtils";

export const PARAGRAPH_FEEDBACK_TOPICS = AGENTIC_TOPICS;
export const PARAGRAPH_STATE_VERSION = 1;

export function emptyParagraphState() {
  return { version: PARAGRAPH_STATE_VERSION, drafts: [], totalCost: 0, letterComplete: false, timeline: [] };
}

function shuffled(list, rng = Math.random) {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** `count` distinct random vendors (all of them when fewer are selected). */
export function pickRandomVendors(vendors, count, rng = Math.random) {
  return shuffled(vendors || [], rng).slice(0, Math.max(0, count));
}

/** A vendor not used yet in this run; once all are used, any but the most recent. */
export function pickNextVendor(vendors, usedVendors, lastVendor, rng = Math.random) {
  const all = vendors || [];
  if (all.length === 0) return null;
  const used = new Set(usedVendors || []);
  const fresh = all.filter((v) => !used.has(v));
  if (fresh.length > 0) return shuffled(fresh, rng)[0];
  const others = all.filter((v) => v !== lastVendor);
  return shuffled(others.length ? others : all, rng)[0];
}

export function usedVendorsOf(state) {
  return (state?.drafts || []).map((d) => d.vendor).filter(Boolean);
}

function newParagraph(text, extra = {}) {
  return {
    id: extra.id || uuidv4(),
    text: text || "",
    status: "active",
    feedback: {},
    feedbackPending: [...PARAGRAPH_FEEDBACK_TOPICS],
    feedbackErrors: {},
    ...extra,
  };
}

export function newLetterDraft(vendor) {
  return {
    id: uuidv4(),
    kind: "letter",
    vendor,
    model: "",
    status: "loading",
    letter: "",
    knownWeaknesses: [],
    contextBefore: [],
    paragraphs: [],
    wholeLetterNotes: {},
    cost: 0,
    createdAt: new Date().toISOString(),
  };
}

export function newContinuationDraft(vendor, letterSoFar, instructions = "") {
  return {
    id: uuidv4(),
    kind: "continuation",
    vendor,
    model: "",
    status: "loading",
    letterSoFar: letterSoFar || "",
    instructions: instructions || "",
    contextBefore: splitIntoParagraphs(letterSoFar || "", vendor).map((p) => p.text),
    paragraphs: [],
    wholeLetterNotes: {},
    cost: 0,
    createdAt: new Date().toISOString(),
  };
}

export function letterDraftReady(draft, data) {
  return {
    ...draft,
    status: "ready",
    model: data.model || "",
    letter: data.letter || "",
    knownWeaknesses: data.known_weaknesses || [],
    paragraphs: (data.paragraphs || []).map((p) => newParagraph(p.text, { id: p.id })),
    cost: (draft.cost || 0) + (data.cost || 0),
  };
}

export function continuationDraftReady(draft, data) {
  return {
    ...draft,
    status: "ready",
    model: data.model || "",
    letterComplete: Boolean(data.letter_complete),
    paragraphs: [newParagraph(data.paragraph?.text || "", { id: data.paragraph?.id })],
    cost: (draft.cost || 0) + (data.cost || 0),
  };
}

export function updateDraft(state, draftId, fn) {
  return { ...state, drafts: state.drafts.map((d) => (d.id === draftId ? fn(d) : d)) };
}

export function updateParagraph(draft, paragraphId, fn) {
  return { ...draft, paragraphs: draft.paragraphs.map((p) => (p.id === paragraphId ? fn(p) : p)) };
}

export function findParagraph(state, paragraphId) {
  for (const draft of state?.drafts || []) {
    const paragraph = draft.paragraphs.find((p) => p.id === paragraphId);
    if (paragraph) return { draft, paragraph };
  }
  return null;
}

/** Slot roots (original paragraphs) in letter order. */
export function baseParagraphs(draft) {
  return (draft?.paragraphs || []).filter((p) => !p.parentId);
}

function slotOf(draft, paragraph) {
  const rootId = paragraph.parentId || paragraph.id;
  return baseParagraphs(draft).findIndex((p) => p.id === rootId);
}

/** Paragraph list + index for the regenerate endpoint (rest of the letter as context). */
export function regenerationContext(draft, paragraphId) {
  const paragraph = draft.paragraphs.find((p) => p.id === paragraphId);
  if (!paragraph) return null;
  const slot = slotOf(draft, paragraph);
  const texts = baseParagraphs(draft).map((p, i) => (i === slot ? paragraph.text : p.text));
  const before = draft.contextBefore || [];
  return { paragraphs: [...before, ...texts], index: before.length + slot, rootId: paragraph.parentId || paragraph.id };
}

/** Whole letter with `text` in the slot of `paragraphId`, plus that paragraph's char range. */
export function focusedLetter(draft, paragraphId, text) {
  const paragraph = draft.paragraphs.find((p) => p.id === paragraphId);
  const slot = paragraph ? slotOf(draft, paragraph) : -1;
  const parts = [...(draft.contextBefore || []), ...baseParagraphs(draft).map((p, i) => (i === slot ? text : p.text))];
  const index = (draft.contextBefore || []).length + slot;
  let offset = 0;
  for (let i = 0; i < index; i += 1) offset += parts[i].length + 2;
  return { letterText: parts.join("\n\n"), focusStart: offset, focusEnd: offset + (text || "").length };
}

/** Insert a regenerated variant right after the last variant of the same slot. */
export function insertVariant(draft, rootId, paragraph) {
  const list = [...draft.paragraphs];
  let at = -1;
  list.forEach((p, i) => {
    if (p.id === rootId || p.parentId === rootId) at = i;
  });
  list.splice(at + 1, 0, { ...newParagraph(paragraph.text, { id: paragraph.id }), parentId: rootId, ...paragraph.extra });
  return { ...draft, paragraphs: list };
}

/**
 * Spread one topic's whole-letter feedback over the draft's paragraphs by quote.
 * Items quoting nothing found in a paragraph become whole-letter notes.
 */
export function distributeLetterFeedback(draft, topic, items) {
  const perParagraph = {};
  const whole = [];
  for (const it of items || []) {
    const target = baseParagraphs(draft).find((p) => resolveQuoteSpan(p.text, it.quote, it.matched_text));
    if (target) (perParagraph[target.id] = perParagraph[target.id] || []).push(it);
    else whole.push(it);
  }
  return {
    ...draft,
    wholeLetterNotes: { ...(draft.wholeLetterNotes || {}), [topic]: whole },
    paragraphs: draft.paragraphs.map((p) => {
      if (p.parentId) return p;
      return {
        ...p,
        feedback: { ...p.feedback, [topic]: perParagraph[p.id] || [] },
        feedbackPending: (p.feedbackPending || []).filter((t) => t !== topic),
      };
    }),
  };
}

/** Focused feedback (one paragraph) for one topic. */
export function setParagraphTopicFeedback(paragraph, topic, items) {
  return {
    ...paragraph,
    feedback: { ...paragraph.feedback, [topic]: items || [] },
    feedbackPending: (paragraph.feedbackPending || []).filter((t) => t !== topic),
  };
}

export function setParagraphTopicError(paragraph, topic, message) {
  return {
    ...paragraph,
    feedbackPending: (paragraph.feedbackPending || []).filter((t) => t !== topic),
    feedbackErrors: { ...(paragraph.feedbackErrors || {}), [topic]: message },
  };
}

/** Strong = a PLEASE_FIX the Laya judge did not flag; everything else is drawn faint. */
export function isStrongNote(item) {
  return item?.type === FEEDBACK_TYPES.PLEASE_FIX && !isLayaHidden(item);
}

export function feedbackItems(paragraph) {
  const out = [];
  for (const topic of PARAGRAPH_FEEDBACK_TOPICS) {
    for (const it of paragraph?.feedback?.[topic] || []) out.push({ ...it, topic });
  }
  return out;
}

export function strongNoteCount(paragraph) {
  return feedbackItems(paragraph).filter(isStrongNote).length;
}

/** Mark loading leftovers from an interrupted session so the user can retry. */
export function settleRestoredState(state) {
  if (!state || !Array.isArray(state.drafts)) return emptyParagraphState();
  return {
    ...emptyParagraphState(),
    ...state,
    drafts: state.drafts.map((d) => ({
      ...d,
      status: d.status === "loading" ? "error" : d.status,
      error: d.status === "loading" ? "Interrupted (page reloaded). Retry or discard." : d.error,
      paragraphs: (d.paragraphs || []).map((p) => {
        const pending = p.feedbackPending || [];
        if (!pending.length) return p;
        const errors = { ...(p.feedbackErrors || {}) };
        for (const t of pending) errors[t] = "Interrupted";
        return { ...p, feedbackPending: [], feedbackErrors: errors };
      }),
    })),
  };
}

/**
 * One timeline row for a finished request. `server` is the backend's own profile
 * (started_at_ms, total_ms, route_ms, per-stage ms such as prepare/llm/check/laya/review).
 * Feedback rows keep the notes the reviewer dropped, which are never shown.
 */
export function timelineEntry(base, data, roundTripMs) {
  const entry = {
    ...base,
    ok: true,
    round_trip_ms: roundTripMs,
    model: data?.model || base.model || "",
    cost: Number(data?.cost) || 0,
    usage: data?.usage || null,
    server: data?.timing || null,
  };
  if (base.kind === "feedback") {
    entry.raw_count = data?.raw_count ?? null;
    entry.kept_count = (data?.items || []).length;
    entry.dropped_items = data?.dropped_items || [];
  }
  return entry;
}

/** Cost of every request tied to a draft (its generation plus all feedback and regenerations). */
export function costByDraft(timeline) {
  const out = {};
  for (const row of timeline || []) {
    if (!row.draft_id) continue;
    out[row.draft_id] = (out[row.draft_id] || 0) + (Number(row.cost) || 0);
  }
  return out;
}

export function assembledText(finalParagraphs) {
  return (finalParagraphs || []).map((p) => (p.text || "").trim()).filter(Boolean).join("\n\n");
}

/** Firestore `paragraph_history` (see letter_writer/firestore_store.py). */
export function buildParagraphHistory(state, events, finalParagraphs) {
  const requestCost = costByDraft(state?.timeline);
  return {
    drafts: (state?.drafts || []).map((d) => ({
      id: d.id,
      kind: d.kind,
      vendor: d.vendor,
      model: d.model || "",
      status: d.status,
      text: d.kind === "letter" ? d.letter || "" : d.paragraphs[0]?.text || "",
      letter_so_far: d.letterSoFar || "",
      instructions: d.instructions || "",
      letter_complete: Boolean(d.letterComplete),
      cost: d.cost || 0,
      request_cost: requestCost[d.id] || 0,
      whole_letter_notes: d.wholeLetterNotes || {},
      paragraphs: d.paragraphs.map((p) => ({
        id: p.id,
        parent_id: p.parentId || null,
        text: p.text,
        status: p.status,
        vendor: p.vendor || d.vendor,
        model: p.model || d.model || "",
        user_feedback: p.userFeedback || "",
        ai_note_ids: p.aiNoteIds || [],
        feedback: p.feedback || {},
      })),
    })),
    events: events || [],
    final_paragraphs: (finalParagraphs || []).map((p) => ({
      source_paragraph_id: p.sourceId || null,
      source_draft_id: findDraftIdForParagraph(state, p.sourceId),
      vendor: p.vendor || null,
      original_text: p.originalText ?? "",
      text: p.text || "",
    })),
    timeline: state?.timeline || [],
    run_started_at: state?.runStartedAt || null,
    total_cost: state?.totalCost || 0,
  };
}

function findDraftIdForParagraph(state, paragraphId) {
  if (!paragraphId) return null;
  return findParagraph(state, paragraphId)?.draft.id || null;
}

/** `ai_letters` rows so the existing RLHF `feedbacks` export keeps working. */
export function buildParagraphAiLetters(state, finalParagraphs) {
  return (state?.drafts || [])
    .filter((d) => d.status === "ready")
    .map((d) => {
      const ids = new Set(d.paragraphs.map((p) => p.id));
      const used = (finalParagraphs || []).filter((p) => ids.has(p.sourceId));
      const corrections = [];
      for (const p of used) {
        if (p.originalText !== undefined && p.text !== p.originalText) {
          const diffs = createTextDiff(p.originalText || "", p.text || "");
          if (Array.isArray(diffs)) corrections.push(...diffs);
        }
      }
      return {
        vendor: d.vendor,
        model: d.model || "",
        text: d.kind === "letter" ? d.letter || "" : d.paragraphs.map((p) => p.text).join("\n\n"),
        cost: d.cost || 0,
        rating: null,
        comment: "",
        chunks_used: used.length,
        user_corrections: corrections,
      };
    });
}
