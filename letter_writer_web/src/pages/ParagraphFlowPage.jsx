import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { v4 as uuidv4 } from "uuid";
import { HoverProvider } from "../contexts/HoverContext";
import { useJobSession } from "../contexts/JobSessionContext";
import { useLanguages } from "../contexts/LanguageContext";
import JobDescriptionColumn from "../components/JobDescriptionColumn";
import LanguageConfig from "../components/LanguageConfig";
import LetterAssemblyPane from "../components/letter-tabs/LetterAssemblyPane";
import DraftColumn from "../components/paragraph-flow/DraftColumn";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { persistLetterDocument } from "../utils/persistLetterDocument";
import { FLOW_LEAVE_PROMPT, useFlowHistoryGuard } from "../hooks/useFlowHistoryGuard";
import {
  PARAGRAPH_FEEDBACK_TOPICS,
  assembledText,
  buildParagraphAiLetters,
  buildParagraphHistory,
  continuationDraftReady,
  distributeLetterFeedback,
  emptyParagraphState,
  focusedLetter,
  insertVariant,
  letterDraftReady,
  newContinuationDraft,
  newLetterDraft,
  pickNextVendor,
  pickRandomVendors,
  regenerationContext,
  setParagraphTopicError,
  setParagraphTopicFeedback,
  settleRestoredState,
  timelineEntry,
  updateDraft,
  updateParagraph,
  usedVendorsOf,
} from "../utils/paragraphFlow";

const MAX_PARALLEL_FEEDBACK = 8;
const PERSIST_DEBOUNCE_MS = 1200;

const toolbarButton = {
  padding: "8px 16px",
  backgroundColor: "var(--button-bg)",
  color: "var(--button-text)",
  border: "1px solid var(--border-color)",
  borderRadius: "4px",
  cursor: "pointer",
};

function createLimiter(max) {
  let active = 0;
  const queue = [];
  const next = () => {
    if (active >= max || queue.length === 0) return;
    active += 1;
    const { fn, resolve, reject } = queue.shift();
    Promise.resolve()
      .then(fn)
      .then(resolve, reject)
      .finally(() => {
        active -= 1;
        next();
      });
  };
  return (fn) =>
    new Promise((resolve, reject) => {
      queue.push({ fn, resolve, reject });
      next();
    });
}

function errorMessage(e) {
  const raw = (e && (e.message || String(e))) || "Unknown error";
  try {
    const parsed = JSON.parse(raw);
    if (parsed?.detail) return String(parsed.detail);
  } catch {
    /* not JSON */
  }
  return raw.replace(/^Error:\s*/, "");
}

async function postJson(url, body) {
  const result = await fetchWithHeartbeat(url, { method: "POST", body: JSON.stringify(body || {}) });
  if (result.isHeartbeat) throw new Error("Request still processing; try again in a moment.");
  return result.data || {};
}

function findDraft(state, draftId) {
  return (state?.drafts || []).find((d) => d.id === draftId) || null;
}

export default function ParagraphFlowPage() {
  const navigate = useNavigate();
  const navLocation = useLocation();
  const session = useJobSession();
  const { enabledLanguages } = useLanguages();

  const [pstate, setPstate] = useState(emptyParagraphState);
  const [finalParagraphs, setFinalParagraphs] = useState([]);
  const [regeneratingIds, setRegeneratingIds] = useState(() => new Set());
  const [continueInstructions, setContinueInstructions] = useState("");
  const [flowError, setFlowError] = useState(null);
  const [referenceSidebarCollapsed, setReferenceSidebarCollapsed] = useState(true);
  const [assemblyTextNormalized, setAssemblyTextNormalized] = useState("");
  const handleAssemblyTextChange = useCallback(({ normalized }) => setAssemblyTextNormalized(normalized), []);

  const stateRef = useRef(pstate);
  stateRef.current = pstate;
  const finalRef = useRef(finalParagraphs);
  finalRef.current = finalParagraphs;
  const eventsRef = useRef([]);
  const pendingEventsRef = useRef([]);
  const activeRef = useRef(false);
  const startedRef = useRef(false);
  const lastVendorRef = useRef(null);
  const prevSourceIdsRef = useRef(new Set());
  const persistTimerRef = useRef(null);
  const limiter = useMemo(() => createLimiter(MAX_PARALLEL_FEEDBACK), []);

  const vendorsList = Array.from(session.selectedVendors);
  const companyReport = session.selectedCompanyReport || undefined;

  // ─── Persistence (server session + event log) ────────────────────────────

  const persistNow = useCallback(async () => {
    if (!activeRef.current) return;
    const events = pendingEventsRef.current;
    pendingEventsRef.current = [];
    const body = {
      state: { ...stateRef.current, finalParagraphs: finalRef.current, events: eventsRef.current },
      events,
    };
    try {
      await fetchWithHeartbeat("/api/paragraph/state/", { method: "POST", body: JSON.stringify(body) });
    } catch (e) {
      pendingEventsRef.current = [...events, ...pendingEventsRef.current];
      console.warn("Paragraph flow: failed to persist state", e);
    }
  }, []);

  const schedulePersist = useCallback(() => {
    if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    persistTimerRef.current = setTimeout(persistNow, PERSIST_DEBOUNCE_MS);
  }, [persistNow]);

  useEffect(() => {
    if (activeRef.current) schedulePersist();
  }, [pstate, finalParagraphs, schedulePersist]);

  useEffect(() => () => persistTimerRef.current && clearTimeout(persistTimerRef.current), []);

  const logEvent = useCallback(
    (action, fields = {}) => {
      const ev = { ts: new Date().toISOString(), action, ...fields };
      eventsRef.current = [...eventsRef.current, ev];
      pendingEventsRef.current = [...pendingEventsRef.current, ev];
      schedulePersist();
    },
    [schedulePersist],
  );

  // Picks into / out of the letter, whether via "Use", drag-and-drop or the assembly's delete.
  useEffect(() => {
    const now = new Set(finalParagraphs.map((p) => p.sourceId).filter(Boolean));
    const before = prevSourceIdsRef.current;
    prevSourceIdsRef.current = now;
    if (!activeRef.current) return;
    for (const id of now) if (!before.has(id)) logEvent("use", { paragraph_id: id });
    for (const id of before) if (!now.has(id)) logEvent("remove_from_letter", { paragraph_id: id });
  }, [finalParagraphs, logEvent]);

  const addCost = (s, cost) => ({ ...s, totalCost: (s.totalCost || 0) + (Number(cost) || 0) });

  // ─── Timeline (one entry per LLM request: queue + round trip + server stages, cost, tokens) ──

  const timedPost = useCallback(async (meta, url, body, queuedAt = Date.now()) => {
    const startedAt = Date.now();
    const base = {
      id: uuidv4(),
      ...meta,
      queued_at: new Date(queuedAt).toISOString(),
      queue_ms: startedAt - queuedAt,
    };
    const record = (entry) => setPstate((s) => ({ ...s, timeline: [...(s.timeline || []), entry] }));
    try {
      const data = await postJson(url, body);
      record(timelineEntry(base, data, Date.now() - startedAt));
      return data;
    } catch (e) {
      record({ ...base, ok: false, round_trip_ms: Date.now() - startedAt, error: errorMessage(e) });
      throw e;
    }
  }, []);

  // ─── Feedback (one request per topic, rendered as each lands) ─────────────

  const runLetterFeedback = useCallback(
    (draft, topics = PARAGRAPH_FEEDBACK_TOPICS) => {
      for (const topic of topics) {
        const queuedAt = Date.now();
        limiter(() =>
          timedPost(
            { kind: "feedback", vendor: draft.vendor, topic, draft_id: draft.id, paragraph_id: null },
            `/api/paragraph/feedback/${draft.vendor}/${topic}/`,
            {
              letter_text: draft.letter,
              known_weaknesses: draft.knownWeaknesses,
              draft_id: draft.id,
              company_report: companyReport,
            },
            queuedAt,
          ),
        )
          .then((data) => {
            setPstate((s) => addCost(updateDraft(s, draft.id, (d) => distributeLetterFeedback(d, topic, data.items)), data.cost));
          })
          .catch((e) => {
            const msg = errorMessage(e);
            setPstate((s) =>
              updateDraft(s, draft.id, (d) => ({
                ...d,
                paragraphs: d.paragraphs.map((p) => (p.parentId ? p : setParagraphTopicError(p, topic, msg))),
              })),
            );
          });
      }
    },
    [limiter, companyReport, timedPost],
  );

  const runFocusedFeedback = useCallback(
    (draft, slotParagraphId, paragraphId, text, topics = PARAGRAPH_FEEDBACK_TOPICS) => {
      const { letterText, focusStart, focusEnd } = focusedLetter(draft, slotParagraphId, text);
      for (const topic of topics) {
        const queuedAt = Date.now();
        limiter(() =>
          timedPost(
            { kind: "feedback", vendor: draft.vendor, topic, draft_id: draft.id, paragraph_id: paragraphId },
            `/api/paragraph/feedback/${draft.vendor}/${topic}/`,
            {
              letter_text: letterText,
              focus_start: focusStart,
              focus_end: focusEnd,
              known_weaknesses: draft.knownWeaknesses || [],
              draft_id: draft.id,
              paragraph_id: paragraphId,
              company_report: companyReport,
            },
            queuedAt,
          ),
        )
          .then((data) => {
            setPstate((s) =>
              addCost(
                updateDraft(s, draft.id, (d) => updateParagraph(d, paragraphId, (p) => setParagraphTopicFeedback(p, topic, data.items))),
                data.cost,
              ),
            );
          })
          .catch((e) => {
            const msg = errorMessage(e);
            setPstate((s) => updateDraft(s, draft.id, (d) => updateParagraph(d, paragraphId, (p) => setParagraphTopicError(p, topic, msg))));
          });
      }
    },
    [limiter, companyReport, timedPost],
  );

  // ─── Drafts ────────────────────────────────────────────────────────────────

  const runLetterDraft = useCallback(
    async (draft) => {
      try {
        const data = await timedPost(
          { kind: "draft", vendor: draft.vendor, draft_id: draft.id },
          `/api/paragraph/draft/${draft.vendor}/`,
          { company_report: companyReport },
        );
        const ready = letterDraftReady(draft, data);
        setPstate((s) => addCost(updateDraft(s, draft.id, () => ready), data.cost));
        logEvent("draft_received", { draft_id: draft.id, vendor: draft.vendor, model: ready.model, paragraphs: ready.paragraphs.length });
        runLetterFeedback(ready);
      } catch (e) {
        const msg = errorMessage(e);
        setPstate((s) => updateDraft(s, draft.id, (d) => ({ ...d, status: "error", error: msg })));
        logEvent("draft_failed", { draft_id: draft.id, vendor: draft.vendor, error: msg });
      }
    },
    [companyReport, logEvent, runLetterFeedback, timedPost],
  );

  const runContinuation = useCallback(
    async (draft) => {
      try {
        const data = await timedPost(
          { kind: "continue", vendor: draft.vendor, draft_id: draft.id },
          `/api/paragraph/continue/${draft.vendor}/`,
          {
            letter_so_far: draft.letterSoFar,
            instructions: draft.instructions,
            company_report: companyReport,
          },
        );
        const ready = continuationDraftReady(draft, data);
        setPstate((s) => addCost({ ...updateDraft(s, draft.id, () => ready), letterComplete: ready.letterComplete }, data.cost));
        const para = ready.paragraphs[0];
        logEvent("continuation_received", {
          draft_id: draft.id,
          paragraph_id: para.id,
          vendor: draft.vendor,
          model: ready.model,
          text: para.text,
          letter_complete: ready.letterComplete,
        });
        runFocusedFeedback(ready, para.id, para.id, para.text);
      } catch (e) {
        const msg = errorMessage(e);
        setPstate((s) => updateDraft(s, draft.id, (d) => ({ ...d, status: "error", error: msg })));
        logEvent("continuation_failed", { draft_id: draft.id, vendor: draft.vendor, error: msg });
      }
    },
    [companyReport, logEvent, runFocusedFeedback, timedPost],
  );

  const startRun = useCallback(
    (count) => {
      const chosen = pickRandomVendors(vendorsList, count || 3);
      if (chosen.length === 0) {
        setFlowError("Select at least one vendor on the job page.");
        return;
      }
      const drafts = chosen.map(newLetterDraft);
      activeRef.current = true;
      eventsRef.current = [];
      pendingEventsRef.current = [];
      prevSourceIdsRef.current = new Set();
      lastVendorRef.current = chosen[chosen.length - 1];
      setFinalParagraphs([]);
      setPstate({ ...emptyParagraphState(), drafts, runStartedAt: new Date().toISOString() });
      logEvent("start", { vendors: chosen, draft_count: count, selected_vendors: vendorsList });
      drafts.forEach((d) => runLetterDraft(d));
    },
    [vendorsList, logEvent, runLetterDraft],
  );

  const generateAnother = useCallback(() => {
    const vendor = pickNextVendor(vendorsList, usedVendorsOf(stateRef.current), lastVendorRef.current);
    if (!vendor) {
      setFlowError("Select at least one vendor on the job page.");
      return;
    }
    lastVendorRef.current = vendor;
    activeRef.current = true;
    const draft = newContinuationDraft(vendor, assembledText(finalRef.current), continueInstructions.trim());
    setPstate((s) => ({ ...s, drafts: [...s.drafts, draft] }));
    logEvent("generate_another", {
      draft_id: draft.id,
      vendor,
      letter_so_far: draft.letterSoFar,
      instructions: draft.instructions,
    });
    setContinueInstructions("");
    runContinuation(draft);
  }, [vendorsList, continueInstructions, logEvent, runContinuation]);

  // ─── Per-paragraph actions ─────────────────────────────────────────────────

  const handleUse = useCallback((draft, p) => {
    setFinalParagraphs((prev) => [
      ...prev,
      { id: uuidv4(), sourceId: p.id, text: p.text, vendor: p.vendor || draft.vendor, originalText: p.text },
    ]);
  }, []);

  const setParagraphStatus = useCallback(
    (draft, p, status) => {
      setPstate((s) => updateDraft(s, draft.id, (d) => updateParagraph(d, p.id, (x) => ({ ...x, status }))));
      logEvent(status === "discarded" ? "discard" : "restore", { draft_id: draft.id, paragraph_id: p.id, vendor: p.vendor || draft.vendor });
    },
    [logEvent],
  );

  const handleRegenerate = useCallback(
    async (draft, p, { userFeedback, aiNotes, vendor }) => {
      const latest = findDraft(stateRef.current, draft.id) || draft;
      const ctx = regenerationContext(latest, p.id);
      if (!ctx) return;
      const regenVendor = vendor || p.vendor || draft.vendor;
      setRegeneratingIds((prev) => new Set(prev).add(p.id));
      logEvent("regenerate_request", {
        draft_id: draft.id,
        paragraph_id: p.id,
        vendor: regenVendor,
        user_feedback: userFeedback,
        ai_note_ids: aiNotes.map((n) => n.id),
        ai_notes: aiNotes,
        previous_text: p.text,
      });
      try {
        const data = await timedPost(
          { kind: "regenerate", vendor: regenVendor, draft_id: draft.id, paragraph_id: p.id },
          `/api/paragraph/regenerate/${regenVendor}/`,
          {
            paragraphs: ctx.paragraphs,
            index: ctx.index,
            user_feedback: userFeedback,
            ai_notes: aiNotes,
            draft_id: draft.id,
            paragraph_id: p.id,
            company_report: companyReport,
          },
        );
        const newId = data.paragraph?.id || uuidv4();
        const text = data.paragraph?.text || "";
        const variant = {
          id: newId,
          text,
          extra: {
            vendor: data.vendor || regenVendor,
            model: data.model || "",
            userFeedback,
            aiNoteIds: aiNotes.map((n) => n.id),
            regeneratedFrom: p.id,
          },
        };
        setPstate((s) => addCost(updateDraft(s, draft.id, (d) => insertVariant(d, ctx.rootId, variant)), data.cost));
        logEvent("regenerate_received", { draft_id: draft.id, paragraph_id: newId, regenerated_from: p.id, vendor: variant.extra.vendor, model: variant.extra.model, text });
        runFocusedFeedback({ ...latest, vendor: variant.extra.vendor }, ctx.rootId, newId, text);
      } catch (e) {
        const msg = errorMessage(e);
        setFlowError(`Regenerate failed (${regenVendor}): ${msg}`);
        logEvent("regenerate_failed", { draft_id: draft.id, paragraph_id: p.id, vendor: regenVendor, error: msg });
      } finally {
        setRegeneratingIds((prev) => {
          const next = new Set(prev);
          next.delete(p.id);
          return next;
        });
      }
    },
    [companyReport, logEvent, runFocusedFeedback, timedPost],
  );

  const handleRetryFeedback = useCallback(
    (draft, p, topics) => {
      const latest = findDraft(stateRef.current, draft.id) || draft;
      const clear = (x) => {
        const errors = { ...(x.feedbackErrors || {}) };
        topics.forEach((t) => delete errors[t]);
        return { ...x, feedbackErrors: errors, feedbackPending: [...new Set([...(x.feedbackPending || []), ...topics])] };
      };
      if (latest.kind === "letter" && !p.parentId) {
        setPstate((s) => updateDraft(s, draft.id, (d) => ({ ...d, paragraphs: d.paragraphs.map((x) => (x.parentId ? x : clear(x))) })));
        runLetterFeedback(latest, topics);
        return;
      }
      setPstate((s) => updateDraft(s, draft.id, (d) => updateParagraph(d, p.id, clear)));
      const feedbackVendor = p.vendor || latest.vendor;
      runFocusedFeedback({ ...latest, vendor: feedbackVendor }, p.parentId || p.id, p.id, p.text, topics);
    },
    [runLetterFeedback, runFocusedFeedback],
  );

  const handleRetryDraft = useCallback(
    (draft) => {
      const fresh = { ...draft, status: "loading", error: null };
      setPstate((s) => updateDraft(s, draft.id, () => fresh));
      if (draft.kind === "letter") runLetterDraft(fresh);
      else runContinuation(fresh);
    },
    [runLetterDraft, runContinuation],
  );

  const handleDismissDraft = useCallback(
    (draft) => {
      setPstate((s) => ({ ...s, drafts: s.drafts.filter((d) => d.id !== draft.id) }));
      logEvent("dismiss_draft", { draft_id: draft.id, vendor: draft.vendor });
    },
    [logEvent],
  );

  // ─── Start / restore ──────────────────────────────────────────────────────

  useEffect(() => {
    if (startedRef.current) return;
    if (navLocation.state?.start) {
      startedRef.current = true;
      const count = navLocation.state?.draftCount || 3;
      navigate(navLocation.pathname, { replace: true, state: {} });
      startRun(count);
      return;
    }
    const pending = session.pendingParagraphRestore;
    if (pending?.state) {
      startedRef.current = true;
      const restored = settleRestoredState(pending.state);
      const { finalParagraphs: restoredFinal = [], events = [], ...rest } = restored;
      eventsRef.current = Array.isArray(events) ? events : [];
      prevSourceIdsRef.current = new Set((restoredFinal || []).map((p) => p.sourceId).filter(Boolean));
      lastVendorRef.current = rest.drafts[rest.drafts.length - 1]?.vendor || null;
      setPstate(rest);
      setFinalParagraphs(Array.isArray(restoredFinal) ? restoredFinal : []);
      activeRef.current = true;
      session.clearPendingParagraphRestore();
    }
  }, [navLocation.state?.start, session.pendingParagraphRestore]);

  // ─── Leave / save ─────────────────────────────────────────────────────────

  const leaveToIntake = useCallback(() => {
    persistNow();
    navigate("/");
  }, [persistNow, navigate]);

  const allowHistoryLeave = useFlowHistoryGuard({ enabled: true, onLeave: leaveToIntake });

  const goBackToJobIntake = useCallback(() => {
    if (!window.confirm(FLOW_LEAVE_PROMPT)) return;
    allowHistoryLeave();
    leaveToIntake();
  }, [allowHistoryLeave, leaveToIntake]);

  const handleCloseSessionAndRestart = useCallback(async () => {
    if (finalRef.current.length > 0 && !window.confirm("Your unsaved work will be discarded. Continue?")) return;
    activeRef.current = false;
    try {
      await fetchWithHeartbeat("/api/phases/clear/", { method: "POST" });
    } catch (e) {
      console.error("Failed to clear session:", e);
      session.setError("Failed to close session. Please try again.");
      return;
    }
    session.resetIntake();
    allowHistoryLeave();
    navigate("/");
  }, [session, navigate, allowHistoryLeave]);

  const handlePersistFinalLetter = useCallback(
    async (finalText) => {
      if (!finalText) {
        session.setError("No letter text to save");
        throw new Error("No letter text to save");
      }
      logEvent("save", { paragraphs: finalRef.current.length });
      try {
        session.setSavingFinal(true);
        session.setDocumentSaveNotice(null);
        const result = await persistLetterDocument({
          letterText: finalText,
          jobFields: {
            companyName: session.companyName,
            jobTitle: session.jobTitle,
            location: session.location,
            language: session.language,
            salary: session.salary,
            sourceUrl: session.sourceUrl,
            requirements: session.requirements,
            jobText: session.jobText,
          },
          documentId: session.documentId,
          aiLetters: buildParagraphAiLetters(stateRef.current, finalRef.current),
          paragraphHistory: buildParagraphHistory(stateRef.current, eventsRef.current, finalRef.current),
        });
        if (result.warnings.length > 0) session.setDocumentSaveNotice(result.warnings.join(" "));
        if (result.documentId && !session.documentId) session.setDocumentId(result.documentId);
      } catch (e) {
        const msg = `Failed to save letter: ${e.message || e}`;
        session.setError(msg);
        throw new Error(msg);
      } finally {
        session.setSavingFinal(false);
      }
    },
    [session, logEvent],
  );

  // ─── Render ───────────────────────────────────────────────────────────────

  if (
    !navLocation.state?.start &&
    !navLocation.state?.rehydrated &&
    !session.phaseSessionId &&
    !startedRef.current &&
    !session.pendingParagraphRestore
  ) {
    return <Navigate to="/" replace />;
  }

  const letterDrafts = pstate.drafts.filter((d) => d.kind === "letter");
  const continuationDrafts = pstate.drafts.filter((d) => d.kind === "continuation");
  const usedIds = new Set(finalParagraphs.map((p) => p.sourceId).filter(Boolean));
  const continuing = continuationDrafts.some((d) => d.status === "loading");
  const nextVendorPreview = pickNextVendor(vendorsList, usedVendorsOf(pstate), lastVendorRef.current, () => 0);
  const columnHandlers = {
    usedIds,
    vendors: vendorsList,
    regeneratingIds,
    onRetryDraft: handleRetryDraft,
    onDismissDraft: handleDismissDraft,
    onUse: handleUse,
    onDiscard: (d, p) => setParagraphStatus(d, p, "discarded"),
    onRestore: (d, p) => setParagraphStatus(d, p, "active"),
    onRegenerate: handleRegenerate,
    onRetryFeedback: handleRetryFeedback,
  };

  return (
    <HoverProvider>
      <div data-testid="paragraph-flow" style={{ display: "flex", flexDirection: "row", alignItems: "stretch", gap: 12, width: "100%", flex: 1, minHeight: 0, boxSizing: "border-box", overflow: "hidden" }}>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap", flexShrink: 0 }}>
            <button type="button" onClick={goBackToJobIntake} style={toolbarButton}>← Back to job details</button>
            <button type="button" onClick={handleCloseSessionAndRestart} style={{ ...toolbarButton, backgroundColor: "#b91c1c", color: "white", border: "1px solid #991b1b" }} title="Clear current session and restart with a blank input form">
              Close session and restart
            </button>
            <input
              type="text"
              value={continueInstructions}
              onChange={(e) => setContinueInstructions(e.target.value)}
              placeholder="Optional hint for the next paragraph"
              aria-label="Instructions for the next paragraph"
              style={{ flex: "1 1 220px", minWidth: 160, maxWidth: 420, padding: "7px 10px", borderRadius: 4, border: "1px solid var(--border-color)", background: "var(--bg-color)", color: "var(--text-color)" }}
            />
            <button
              type="button"
              data-testid="paragraph-generate-another"
              onClick={generateAnother}
              disabled={continuing || vendorsList.length === 0}
              title={nextVendorPreview ? `Continues the letter on the right; next vendor not yet used: ${nextVendorPreview}…` : "Continues the letter on the right"}
              style={{ ...toolbarButton, backgroundColor: "#c2410c", color: "white", border: "1px solid #9a3412", opacity: continuing ? 0.6 : 1 }}
            >
              {continuing ? "Writing…" : "Generate another"}
            </button>
            <span style={{ fontSize: 12, color: "var(--secondary-text-color)" }} title="Spent in this paragraph flow">
              ${Number(pstate.totalCost || 0).toFixed(3)}
            </span>
            <div style={{ marginLeft: "auto" }}><LanguageConfig /></div>
          </div>
          {(flowError || session.error) && (
            <p style={{ color: "var(--error-text)", margin: "0 0 8px" }}>
              {flowError || session.error}
              {flowError && (
                <button type="button" onClick={() => setFlowError(null)} style={{ marginLeft: 8, fontSize: 12 }}>dismiss</button>
              )}
            </p>
          )}
          {session.documentSaveNotice && (
            <p role="status" style={{ color: "var(--secondary-text-color)", background: "var(--warning-bg)", border: "1px solid var(--warning-border)", padding: "10px 12px", borderRadius: 4 }}>{session.documentSaveNotice}</p>
          )}
          {pstate.letterComplete && (
            <p role="status" style={{ fontSize: 12, color: "var(--secondary-text-color)", margin: "0 0 8px" }}>
              The last suggestion says the letter looks complete. You can still generate more or edit freely.
            </p>
          )}
          <div style={{ display: "flex", gap: 10, flex: 1, minHeight: 0 }}>
            <div style={{ flex: 1, minWidth: 0, display: "flex", gap: 10, overflowX: "auto", minHeight: 0, paddingBottom: 4 }}>
              {letterDrafts.map((draft) => (
                <DraftColumn
                  key={draft.id}
                  title={draft.vendor}
                  subtitle={draft.model}
                  color={session.vendorColors?.[draft.vendor]}
                  drafts={[draft]}
                  {...columnHandlers}
                />
              ))}
              <DraftColumn
                title="More options"
                subtitle={continuationDrafts.length ? `${continuationDrafts.length}` : ""}
                drafts={continuationDrafts}
                emptyHint={
                  <div style={{ fontSize: 12, color: "var(--secondary-text-color)" }}>
                    Pick paragraphs into the letter, then use <strong>Generate another</strong>: a vendor not used yet writes the next paragraph after what you picked.
                  </div>
                }
                {...columnHandlers}
              />
            </div>
            <div style={{ width: 380, flexShrink: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
              <LetterAssemblyPane
                finalParagraphs={finalParagraphs}
                setFinalParagraphs={setFinalParagraphs}
                vendorColors={session.vendorColors}
                requirements={session.requirements}
                selectedKeyTerm={session.competenceHighlightTerm}
                languageOptions={enabledLanguages}
                onSave={handlePersistFinalLetter}
                savingFinal={session.savingFinal}
                columnWidth="100%"
                minColumnWidth={300}
                onAssemblyTextChange={handleAssemblyTextChange}
              />
            </div>
          </div>
        </div>

        {referenceSidebarCollapsed ? (
          <button
            type="button"
            onClick={() => setReferenceSidebarCollapsed(false)}
            aria-label="Expand job and fit reference panel"
            title="Job offer, key competences, company report, extracted goal"
            style={{ flexShrink: 0, width: 44, alignSelf: "stretch", padding: "10px 6px", display: "flex", flexDirection: "column", alignItems: "center", gap: 10, border: "1px solid var(--border-color)", borderRadius: 8, background: "var(--card-bg)", color: "var(--text-color)", cursor: "pointer" }}
          >
            <span style={{ fontSize: 16, lineHeight: 1 }} aria-hidden>‹</span>
            {["Job offer", "Key fit", "Report"].map((label) => (
              <span key={label} style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", fontSize: 11, fontWeight: 600, color: "var(--secondary-text-color)", whiteSpace: "nowrap" }}>{label}</span>
            ))}
          </button>
        ) : (
          <div style={{ width: 340, flexShrink: 0, alignSelf: "stretch", minHeight: 0, display: "flex", flexDirection: "column", border: "1px solid var(--border-color)", borderRadius: 8, overflow: "hidden", background: "var(--card-bg)" }}>
            <JobDescriptionColumn
              jobText={session.jobText}
              companyReport={session.selectedCompanyReport}
              pocReport={session.selectedPocReport}
              requirements={session.requirements}
              competences={session.competences}
              scaleConfig={session.competenceScaleConfig}
              overrides={session.competenceOverrides}
              width="100%"
              minWidth="0"
              languages={enabledLanguages}
              selectedKeyTerm={session.competenceHighlightTerm}
              onTermClick={session.handleCompetenceTermClick}
              competenceCounts={{}}
              finalAssemblyText={assemblyTextNormalized}
              hireProblem={session.hireProblem}
              onHireProblemChange={session.setHireProblem}
              onCollapsePanel={() => setReferenceSidebarCollapsed(true)}
            />
          </div>
        )}
      </div>
    </HoverProvider>
  );
}
