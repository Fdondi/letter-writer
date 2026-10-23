import {
  PARAGRAPH_FEEDBACK_TOPICS,
  buildParagraphAiLetters,
  buildParagraphHistory,
  distributeLetterFeedback,
  focusedLetter,
  insertVariant,
  isStrongNote,
  letterDraftReady,
  newContinuationDraft,
  newLetterDraft,
  pickNextVendor,
  pickRandomVendors,
  regenerationContext,
  settleRestoredState,
  strongNoteCount,
  timelineEntry,
} from "../paragraphFlow";
import { applyRestoredSessionState } from "../applySessionRestore";
import { harnessRestorePath } from "../harnessFixtureBoot";

function readyLetter(vendor = "openai") {
  return letterDraftReady(newLetterDraft(vendor), {
    model: "m1",
    letter: "Dear team,\n\nI build things.\n\nBye",
    cost: 0.5,
    paragraphs: [
      { id: "p0", text: "Dear team," },
      { id: "p1", text: "I build things." },
      { id: "p2", text: "Bye" },
    ],
  });
}

describe("vendor picking", () => {
  test("picks distinct random vendors, capped at the selection", () => {
    const picked = pickRandomVendors(["a", "b", "c", "d"], 3, () => 0.5);
    expect(new Set(picked).size).toBe(3);
    expect(pickRandomVendors(["a", "b"], 3)).toHaveLength(2);
  });

  test("next vendor prefers unused, then anything but the last", () => {
    expect(pickNextVendor(["a", "b", "c"], ["a", "b"], "b")).toBe("c");
    for (let i = 0; i < 10; i += 1) {
      expect(pickNextVendor(["a", "b"], ["a", "b"], "b")).toBe("a");
    }
    expect(pickNextVendor([], [], null)).toBeNull();
  });
});

describe("feedback distribution", () => {
  test("letter feedback lands on the quoted paragraph; unquoted goes whole-letter", () => {
    const draft = readyLetter();
    const out = distributeLetterFeedback(draft, "precision", [
      { id: "f1", type: "PLEASE_FIX", observation: "vague", quote: "build things" },
      { id: "f2", type: "PLEASE_FIX", observation: "overall tone", quote: "" },
    ]);
    const p1 = out.paragraphs.find((p) => p.id === "p1");
    expect(p1.feedback.precision.map((it) => it.id)).toEqual(["f1"]);
    expect(p1.feedbackPending).not.toContain("precision");
    expect(out.wholeLetterNotes.precision.map((it) => it.id)).toEqual(["f2"]);
    expect(strongNoteCount(p1)).toBe(1);
  });

  test("strong means PLEASE_FIX not flagged by Laya", () => {
    expect(isStrongNote({ type: "PLEASE_FIX" })).toBe(true);
    expect(isStrongNote({ type: "ALREADY_GOOD" })).toBe(false);
    expect(isStrongNote({ type: "PLEASE_FIX", laya_verdict: "invalid" })).toBe(false);
  });
});

describe("regeneration context", () => {
  test("variant keeps the slot and the rest of the letter", () => {
    let draft = readyLetter();
    draft = insertVariant(draft, "p1", { id: "v1", text: "I ship products.", extra: { vendor: "gemini" } });
    expect(draft.paragraphs.map((p) => p.id)).toEqual(["p0", "p1", "v1", "p2"]);
    expect(draft.paragraphs[2]).toMatchObject({ parentId: "p1", vendor: "gemini" });
    expect(draft.paragraphs[2].feedbackPending).toEqual(PARAGRAPH_FEEDBACK_TOPICS);

    const ctx = regenerationContext(draft, "v1");
    expect(ctx).toEqual({ paragraphs: ["Dear team,", "I ship products.", "Bye"], index: 1, rootId: "p1" });

    const focus = focusedLetter(draft, "p1", "I ship products.");
    expect(focus.letterText).toBe("Dear team,\n\nI ship products.\n\nBye");
    expect(focus.letterText.slice(focus.focusStart, focus.focusEnd)).toBe("I ship products.");
  });

  test("continuation regenerates after the letter so far", () => {
    const draft = {
      ...newContinuationDraft("mistral", "Hello.\n\nMiddle."),
      status: "ready",
      paragraphs: [{ id: "c1", text: "Next.", feedback: {}, status: "active" }],
    };
    expect(regenerationContext(draft, "c1")).toEqual({ paragraphs: ["Hello.", "Middle.", "Next."], index: 2, rootId: "c1" });
    const focus = focusedLetter(draft, "c1", "Other.");
    expect(focus.letterText.slice(focus.focusStart, focus.focusEnd)).toBe("Other.");
  });
});

describe("persistence", () => {
  test("restored loading work becomes retryable errors", () => {
    const state = settleRestoredState({
      drafts: [{ ...newLetterDraft("openai") }, { ...readyLetter() }],
    });
    expect(state.drafts[0].status).toBe("error");
    expect(state.drafts[1].paragraphs[0].feedbackPending).toEqual([]);
    expect(Object.keys(state.drafts[1].paragraphs[0].feedbackErrors)).toEqual(PARAGRAPH_FEEDBACK_TOPICS);
  });

  test("history and ai_letters record picks and edits", () => {
    const draft = readyLetter();
    const state = { drafts: [draft], totalCost: 0.7 };
    const finals = [{ id: "f", sourceId: "p1", vendor: "openai", originalText: "I build things.", text: "I build great things." }];
    const history = buildParagraphHistory(state, [{ action: "use", paragraph_id: "p1" }], finals);
    expect(history.final_paragraphs[0]).toMatchObject({ source_paragraph_id: "p1", source_draft_id: draft.id });
    expect(history.drafts[0].paragraphs).toHaveLength(3);
    expect(history.total_cost).toBe(0.7);
    const [ai] = buildParagraphAiLetters(state, finals);
    expect(ai).toMatchObject({ vendor: "openai", chunks_used: 1, text: draft.letter });
    expect(ai.user_corrections.length).toBeGreaterThan(0);
  });

  test("timeline rows keep server profile, usage and dropped notes; history sums cost per draft", () => {
    const base = { id: "t1", kind: "feedback", vendor: "openai", topic: "precision", draft_id: "d1", queue_ms: 40 };
    const data = {
      items: [{ id: "a" }],
      dropped_items: [{ id: "b", observation: "weak" }],
      raw_count: 3,
      cost: 0.02,
      usage: { paragraph_feedback: { cost: 0.015 }, paragraph_feedback_review: { cost: 0.005 } },
      timing: { total_ms: 900, stages: { check: 700, laya: 50, review: 150 } },
    };
    const row = timelineEntry(base, data, 1000);
    expect(row).toMatchObject({ ok: true, round_trip_ms: 1000, queue_ms: 40, cost: 0.02, kept_count: 1, raw_count: 3 });
    expect(row.dropped_items).toEqual([{ id: "b", observation: "weak" }]);
    expect(row.server.stages.laya).toBe(50);
    const draftRow = timelineEntry({ id: "t0", kind: "draft", draft_id: "d1" }, { cost: 0.1, model: "m" }, 5000);
    expect(draftRow.dropped_items).toBeUndefined();

    const draft = { ...readyLetter(), id: "d1" };
    const history = buildParagraphHistory({ drafts: [draft], timeline: [draftRow, row], runStartedAt: "2026-10-20T10:00:00Z" }, [], []);
    expect(history.timeline).toHaveLength(2);
    expect(history.drafts[0].request_cost).toBeCloseTo(0.12);
    expect(history.run_started_at).toBe("2026-10-20T10:00:00Z");
  });

  test("session restore routes paragraph state to the paragraph flow", () => {
    const setters = new Proxy({}, { get: () => () => {} });
    const result = applyRestoredSessionState(
      { paragraph: { drafts: [readyLetter()] }, vendors: { openai: { top_docs: [{ id: 1 }] } } },
      setters,
    );
    expect(result.paragraph.state.drafts).toHaveLength(1);
    expect(result.vendor).toBeNull();
    expect(harnessRestorePath(result)).toBe("/flows/paragraph");
  });
});
