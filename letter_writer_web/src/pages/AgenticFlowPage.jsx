import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useNavigate, useLocation, Navigate } from "react-router-dom";
import AgenticFlow from "../components/AgenticFlow";
import LetterTabs from "../components/LetterTabs";
import JobDescriptionColumn from "../components/JobDescriptionColumn";
import LanguageConfig from "../components/LanguageConfig";
import { useJobSession } from "../contexts/JobSessionContext";
import { useLanguages } from "../contexts/LanguageContext";
import { fetchWithHeartbeat, publishUserMonthlyCost } from "../utils/apiHelpers";
import { splitIntoParagraphs } from "../utils/split";
import { persistLetterDocument, buildAgenticAiLetters } from "../utils/persistLetterDocument";
import { showNotification } from "../utils/apiNotifications";

const AGENTIC_TOPICS = ["instruction", "company_fit", "goal_fit", "precision", "user_fit", "human", "accuracy"];

const REFERENCE_SIDEBAR_VIEWPORT_STYLE = {
  alignSelf: "flex-start",
  position: "sticky",
  top: 20,
  height: "calc(100vh - 40px)",
  maxHeight: "calc(100vh - 40px)",
  boxSizing: "border-box",
};

export default function AgenticFlowPage() {
  const navigate = useNavigate();
  const navLocation = useLocation();
  const session = useJobSession();
  const { enabledLanguages } = useLanguages();

  const [agenticStage, setAgenticStage] = useState("agentic");
  const [agenticState, setAgenticState] = useState(null);
  const [agenticLoading, setAgenticLoading] = useState(false);
  const [agenticError, setAgenticError] = useState(null);
  const [agenticMaxRounds, setAgenticMaxRounds] = useState(3);
  const [agenticSubCommentRounds, setAgenticSubCommentRounds] = useState(0);
  const [agenticSavingFinal, setAgenticSavingFinal] = useState(false);
  const [agenticSaveError, setAgenticSaveError] = useState(null);
  const [agenticFinalParagraphs, setAgenticFinalParagraphs] = useState([]);
  const [referenceSidebarCollapsed, setReferenceSidebarCollapsed] = useState(false);

  const bestKnownThreadsRef = useRef(null);
  const agenticPhasesRef = useRef(null);
  const startedRef = useRef(false);
  const agenticOngoingRef = useRef(undefined);

  const vendorsList = Array.from(session.selectedVendors);
  const hasAgenticAssembly = agenticState?.status === "done";
  const toggleX = "40%";

  const extractErrorMessage = useCallback((error) => {
    if (!error) return "Unknown error";
    const errorStr = typeof error === "string" ? error : (error.message || String(error));
    try { const parsed = JSON.parse(errorStr); if (parsed.detail) return parsed.detail; if (parsed.message) return parsed.message; } catch (_) {}
    return errorStr.replace(/^Error:\s*/, "").trim() || "Unknown error";
  }, []);

  const normalizeAgenticThreads = useCallback((threadsPayload = {}, topicMetaPayload = {}) => {
    const threadsOut = AGENTIC_TOPICS.reduce((acc, topic) => ({ ...acc, [topic]: [] }), {});
    const topicMetaOut = { ...(topicMetaPayload && typeof topicMetaPayload === "object" ? topicMetaPayload : {}) };
    const assignTopic = (topicKey, rawValue) => {
      if (!topicKey || typeof topicKey !== "string") return;
      const topic = topicKey.trim();
      if (!topic) return;
      if (!(topic in threadsOut)) threadsOut[topic] = [];
      if (Array.isArray(rawValue)) { threadsOut[topic] = rawValue; return; }
      if (!rawValue || typeof rawValue !== "object") { threadsOut[topic] = []; return; }
      const candidateThread = Array.isArray(rawValue.thread) ? rawValue.thread : Array.isArray(rawValue.comments) ? rawValue.comments : Array.isArray(rawValue.messages) ? rawValue.messages : [];
      threadsOut[topic] = candidateThread;
      const round = rawValue.round;
      const done = rawValue.done;
      const messages = rawValue.messages_count ?? rawValue.count ?? rawValue.messages;
      if (round != null || done != null || messages != null || "waiting_for" in rawValue) {
        const nextMeta = { ...(topicMetaOut[topic] || {}), ...(round != null && { round }), ...(messages != null && { messages: Number.isFinite(Number(messages)) ? Number(messages) : candidateThread.length }), ...(done != null && { done: done === true }) };
        if ("waiting_for" in rawValue) {
          const wf = rawValue.waiting_for;
          if (wf != null && typeof wf === "object") nextMeta.waiting_for = wf;
          else if (wf != null && String(wf).trim() !== "") nextMeta.waiting_for = String(wf).trim();
          else delete nextMeta.waiting_for;
        }
        topicMetaOut[topic] = nextMeta;
      }
    };
    if (Array.isArray(threadsPayload)) {
      threadsPayload.forEach((entry) => { if (!entry || typeof entry !== "object") return; assignTopic(entry.topic || entry.key || entry.name, entry.thread ?? entry.comments ?? entry.messages ?? entry); });
    } else if (threadsPayload && typeof threadsPayload === "object") {
      Object.entries(threadsPayload).forEach(([topic, value]) => assignTopic(topic, value));
    }
    return { threads: threadsOut, topicMeta: topicMetaOut };
  }, []);

  const stripAgenticThreadFields = useCallback((state) => {
    if (!state || typeof state !== "object") return state;
    const next = { ...state }; delete next.threads; delete next.topic_meta; return next;
  }, []);

  const mergeAgenticUpdate = useCallback((prevState, update) => {
    const cleanUpdate = stripAgenticThreadFields(update);
    if (!cleanUpdate || typeof cleanUpdate !== "object") return prevState || null;
    return { ...(prevState || {}), ...cleanUpdate };
  }, [stripAgenticThreadFields]);

  const syncAgenticMaxRoundsFromServer = useCallback((value) => {
    if (value == null || value === "") return; const n = Number(value); if (!Number.isFinite(n)) return; setAgenticMaxRounds(n);
  }, []);

  const syncAgenticSubCommentRoundsFromServer = useCallback((value) => {
    if (value == null || value === "") return; const n = Number(value); if (!Number.isFinite(n)) return; setAgenticSubCommentRounds(Math.max(0, Math.min(8, Math.floor(n))));
  }, []);

  useEffect(() => {
    const ongoing = agenticState?.ongoing;
    const status = agenticState?.status;
    const wasOngoing = agenticOngoingRef.current;
    agenticOngoingRef.current = ongoing;
    if (status === "feedback" && ongoing === false && wasOngoing !== false) showNotification("Agentic feedback completed");
  }, [agenticState?.status, agenticState?.ongoing]);

  useEffect(() => {
    if (agenticState?.status === "done") setAgenticStage("assembly");
  }, [agenticState?.status]);

  useEffect(() => {
    if (agenticState?.status !== "done") setAgenticFinalParagraphs([]);
  }, [agenticState?.status]);

  useEffect(() => {
    if (startedRef.current) return;
    if (!navLocation.state?.start) return;
    startedRef.current = true;
    const { maxRounds, subCommentRounds } = navLocation.state;
    if (maxRounds != null) setAgenticMaxRounds(maxRounds);
    if (subCommentRounds != null) setAgenticSubCommentRounds(subCommentRounds);
    navigate(navLocation.pathname, { replace: true, state: {} });

    setAgenticLoading(true);
    setAgenticError(null);
    setAgenticState(null);
    bestKnownThreadsRef.current = null;
    setAgenticStage("agentic");

    (async () => {
      try {
        const body = {};
        if (session.selectedCompanyReport) body.company_report = session.selectedCompanyReport;
        if (vendorsList.length > 0) body.draft_vendors = vendorsList;
        body.max_rounds = maxRounds ?? 3;
        body.sub_comment_rounds = subCommentRounds ?? 0;
        const res = await fetchWithHeartbeat("/api/phases/agentic/draft/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        if (res.isHeartbeat) { setAgenticLoading(false); return; }
        const nextAgentic = stripAgenticThreadFields(res.data?.agentic_state ?? null);
        setAgenticState(nextAgentic);
        if (nextAgentic?.max_rounds != null) syncAgenticMaxRoundsFromServer(nextAgentic.max_rounds);
        if (nextAgentic?.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(nextAgentic.sub_comment_rounds);
      } catch (e) {
        console.error("Agentic draft error", e);
        setAgenticError(extractErrorMessage(e));
      } finally {
        setAgenticLoading(false);
      }
    })();
  }, [navLocation.state?.start]);

  if (!navLocation.state?.start && !session.phaseSessionId && !startedRef.current) {
    return <Navigate to="/" replace />;
  }

  const fetchAgenticPoll = async () => {
    try {
      const res = await fetch("/api/phases/agentic/feedback/poll/", { credentials: "include" });
      if (!res.ok) return false;
      const data = await res.json();
      publishUserMonthlyCost(data);
      const normalized = normalizeAgenticThreads(data.threads || {}, data.topic_meta || {});
      const best = bestKnownThreadsRef.current || {};
      let bestUpdated = false;
      for (const topic of AGENTIC_TOPICS) {
        const incoming = normalized.threads[topic] || [];
        if (incoming.length > (best[topic]?.length || 0)) { best[topic] = incoming; bestUpdated = true; }
      }
      if (bestUpdated) bestKnownThreadsRef.current = { ...best };
      setAgenticState((prev) => {
        const threads = {};
        for (const topic of AGENTIC_TOPICS) {
          const prevList = prev?.threads?.[topic] || [];
          const nextList = normalized.threads[topic] || [];
          const refList = bestKnownThreadsRef.current?.[topic] || [];
          threads[topic] = [prevList, nextList, refList].reduce((a, b) => (b.length > a.length ? b : a), []);
        }
        return {
          ...(prev || {}), threads, status: data.status ?? prev?.status, ongoing: data.ongoing,
          feedback_suspended: data.feedback_suspended, topic_meta: normalized.topicMeta,
          ...(data.max_rounds != null && { max_rounds: data.max_rounds }),
          ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }),
        };
      });
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
      return data.ongoing === true;
    } catch (e) { console.warn("Failed to poll agentic feedback:", e); return false; }
  };

  const handleAgenticFeedbackStart = async () => {
    if (!vendorsList.length) return;
    setAgenticLoading(true); setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/feedback/start/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ feedback_vendors: vendorsList }), credentials: "include" });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || res.statusText); }
      const data = await res.json(); publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, { status: data.status ?? "feedback", ongoing: data.ongoing, feedback_suspended: data.feedback_suspended, ...(data.max_rounds != null && { max_rounds: data.max_rounds }), ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }) }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) { setAgenticError(e?.message || String(e)); } finally { setAgenticLoading(false); }
  };

  const handleAgenticSuspend = async () => {
    setAgenticLoading(true); setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/feedback/suspend/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ all: true }), credentials: "include" });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || res.statusText); }
      const data = await res.json(); publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, { status: data.status ?? prev?.status, ongoing: data.ongoing, feedback_suspended: data.feedback_suspended, ...(data.max_rounds != null && { max_rounds: data.max_rounds }), ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }) }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) { setAgenticError(e?.message || String(e)); } finally { setAgenticLoading(false); }
  };

  const handleAgenticResume = async () => {
    setAgenticLoading(true); setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/feedback/resume/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ all: true }), credentials: "include" });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || res.statusText); }
      const data = await res.json(); publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, { status: data.status ?? prev?.status, ongoing: data.ongoing, feedback_suspended: data.feedback_suspended, ...(data.max_rounds != null && { max_rounds: data.max_rounds }), ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }) }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) { setAgenticError(e?.message || String(e)); } finally { setAgenticLoading(false); }
  };

  const handleAgenticAddRound = async (all = true, topic = null) => {
    setAgenticLoading(true); setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/rounds/add/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(all ? { all: true } : { topic }), credentials: "include" });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || res.statusText); }
      const data = await res.json(); publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, { status: data.status ?? prev?.status, ongoing: data.ongoing, feedback_suspended: data.feedback_suspended, ...(data.max_rounds != null && { max_rounds: data.max_rounds }), ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }) }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) { setAgenticError(e?.message || String(e)); } finally { setAgenticLoading(false); }
  };

  const handleAgenticVote = async () => {
    if (!vendorsList.length) return;
    setAgenticLoading(true); setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/vote/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ voting_vendors: vendorsList }), credentials: "include" });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || res.statusText); }
      const data = await res.json(); publishUserMonthlyCost(data);
      if (data?.agentic_update != null) setAgenticState((prev) => mergeAgenticUpdate(prev, data.agentic_update));
    } catch (e) { setAgenticError(e?.message || String(e)); } finally { setAgenticLoading(false); }
  };

  const handleAgenticRefine = async (threadsOverride = null, options = {}) => {
    setAgenticLoading(true); setAgenticError(null);
    try {
      const opts = { method: "POST" };
      const body = {};
      if (threadsOverride != null && typeof threadsOverride === "object") body.threads = threadsOverride;
      const n = options.refine_sample_count;
      if (n != null && Number.isFinite(Number(n))) body.refine_sample_count = Math.max(1, Math.min(20, Math.floor(Number(n))));
      if (Object.keys(body).length > 0) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
      const res = await fetchWithHeartbeat("/api/phases/agentic/refine/", opts);
      if (res.isHeartbeat) return;
      if (res.data?.agentic_update != null) setAgenticState((prev) => mergeAgenticUpdate(prev, res.data.agentic_update));
    } catch (e) { setAgenticError(e?.message || String(e)); } finally { setAgenticLoading(false); }
  };

  const handlePersistAgenticLetter = useCallback(async (letterText) => {
    if (!letterText?.trim()) { setAgenticSaveError("No letter text to save"); throw new Error("No letter text to save"); }
    if (!session.jobText?.trim()) { setAgenticSaveError("Job description is required to save"); throw new Error("Job description is required to save"); }
    const aiLetters = buildAgenticAiLetters({
      agenticState, vendorFeedback: session.vendorFeedback, finalParagraphs: agenticFinalParagraphs, letterText,
    });
    try {
      setAgenticSaveError(null); setAgenticSavingFinal(true); session.setDocumentSaveNotice(null);
      const result = await persistLetterDocument({
        letterText, jobFields: { companyName: session.companyName, jobTitle: session.jobTitle, location: session.location, language: session.language, salary: session.salary, requirements: session.requirements, jobText: session.jobText },
        documentId: session.documentId, aiLetters,
      });
      if (result.warnings.length > 0) session.setDocumentSaveNotice(result.warnings.join(" "));
      if (result.documentId && !session.documentId) session.setDocumentId(result.documentId);
    } catch (e) {
      const msg = e.message || "Failed to save letter"; setAgenticSaveError(msg); throw new Error(msg);
    } finally { setAgenticSavingFinal(false); }
  }, [agenticState, session, agenticFinalParagraphs]);

  const goBackToJobIntake = async () => navigate("/");

  const handleCloseSessionAndRestart = async () => {
    const hasUnsaved = agenticState?.draft_letter || agenticState?.final_letter || Object.values(agenticState?.draft_letters || {}).some(t => t?.trim()) || Object.values(agenticState?.final_letters || {}).some(t => t?.trim());
    if (hasUnsaved && !window.confirm("Your unsaved work will be discarded. Continue?")) return;
    try { await fetchWithHeartbeat("/api/phases/clear/", { method: "POST" }); } catch (e) {
      console.error("Failed to clear session:", e); session.setError("Failed to close session. Please try again."); return;
    }
    session.resetIntake(); navigate("/");
  };

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 12, width: "100%", flex: 1, boxSizing: "border-box", overflow: "hidden" }}>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10, position: "relative", flexWrap: "wrap" }}>
          <button onClick={goBackToJobIntake} style={{ padding: "8px 16px", backgroundColor: "var(--button-bg)", color: "var(--button-text)", border: "1px solid var(--border-color)", borderRadius: "4px", cursor: "pointer" }}>← Back to job details</button>
          <button type="button" onClick={handleCloseSessionAndRestart} style={{ padding: "8px 16px", backgroundColor: "#b91c1c", color: "white", border: "1px solid #991b1b", borderRadius: "4px", cursor: "pointer" }} title="Clear current session and restart with a blank input form">Close session and restart</button>
          {agenticStage === "assembly" && (
            <div style={{ position: "absolute", left: toggleX, transform: "translateX(-50%)" }}>
              <button type="button" onClick={() => agenticPhasesRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} style={{ padding: "10px 14px", border: "1px solid var(--border-color)", borderRadius: "999px", backgroundColor: "var(--button-bg)", color: "var(--button-text)", cursor: "pointer", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" }}>↑ Back to feedback</button>
            </div>
          )}
          <div style={{ marginLeft: "auto" }}><LanguageConfig /></div>
        </div>
        {session.error && <p style={{ color: "var(--error-text)" }}>{session.error}</p>}
        {session.documentSaveNotice && (
          <p role="status" style={{ color: "var(--secondary-text-color)", background: "var(--warning-bg)", border: "1px solid var(--warning-border)", padding: "10px 12px", borderRadius: 4 }}>{session.documentSaveNotice}</p>
        )}

        <div ref={agenticPhasesRef}>
          <AgenticFlow
            agenticState={agenticState}
            onFeedbackStart={handleAgenticFeedbackStart}
            onVote={handleAgenticVote}
            onRefine={handleAgenticRefine}
            onSuspend={handleAgenticSuspend}
            onResume={handleAgenticResume}
            onAddRound={handleAgenticAddRound}
            feedbackVendors={vendorsList}
            vendorColors={session.vendorColors}
            loading={agenticLoading}
            error={agenticError}
            onPollState={fetchAgenticPoll}
            pollIntervalMs={1000}
          />
        </div>

        {agenticStage === "assembly" && (
          <div style={{ position: "relative", paddingTop: 4 }}>
            <LetterTabs
              vendorsList={Object.keys(agenticState?.final_letters || {}).filter(Boolean)}
              vendorParagraphs={agenticState?.final_letters ? Object.fromEntries(Object.entries(agenticState.final_letters).map(([v, text]) => [v, splitIntoParagraphs(text || "", v)])) : {}}
              vendorCosts={(() => { const cost = agenticState?.cost ?? 0; const vs = Object.keys(agenticState?.final_letters || {}); return vs.length ? Object.fromEntries(vs.map((v) => [v, cost / vs.length])) : {}; })()}
              vendorRefineCosts={Object.keys(agenticState?.final_letters || {}).reduce((acc, v) => ({ ...acc, [v]: agenticState?.cost ?? 0 }), {})}
              finalParagraphs={agenticFinalParagraphs}
              setFinalParagraphs={setAgenticFinalParagraphs}
              originalText={session.jobText}
              requirements={session.requirements}
              competences={session.competences}
              competenceScaleConfig={session.competenceScaleConfig}
              competenceOverrides={session.competenceOverrides}
              vendorColors={session.vendorColors}
              failedVendors={{}}
              onRetry={async () => {}}
              onAddParagraph={(paraObj) => setAgenticFinalParagraphs((prev) => [...prev, { ...paraObj }])}
              onSave={handlePersistAgenticLetter}
              savingFinal={agenticSavingFinal}
              vendorFeedback={session.vendorFeedback}
              setVendorFeedback={session.setVendorFeedback}
              refineSamples={agenticState?.refine_samples || {}}
              vendorDraftParagraphs={agenticState?.draft_letters ? Object.fromEntries(Object.entries(agenticState.draft_letters).map(([v, text]) => [v, splitIntoParagraphs(text || "", v)])) : undefined}
              selectedKeyTerm={session.competenceHighlightTerm}
              onTermClick={session.handleCompetenceTermClick}
              onHighlightContextChange={session.handleAssemblyHighlightCtx}
            />
          </div>
        )}
      </div>

      {referenceSidebarCollapsed ? (
        <button type="button" onClick={() => setReferenceSidebarCollapsed(false)} aria-label="Expand job and fit reference panel" title="Job offer, key competences, company report, extracted goal" style={{ flexShrink: 0, width: 44, ...REFERENCE_SIDEBAR_VIEWPORT_STYLE, marginTop: 0, padding: "10px 6px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-start", gap: 10, border: "1px solid var(--border-color)", borderRadius: 8, background: "var(--card-bg)", color: "var(--text-color)", cursor: "pointer", boxShadow: "0 1px 3px rgba(0,0,0,0.1)", boxSizing: "border-box" }}>
          <span style={{ fontSize: 16, lineHeight: 1, flexShrink: 0 }} aria-hidden>‹</span>
          {["Job offer", "Key fit", "Report", ...(session.selectedPocReport ? ["POC"] : [])].map((label) => (
            <span key={label} style={{ writingMode: "vertical-rl", textOrientation: "mixed", transform: "rotate(180deg)", fontSize: 11, fontWeight: 600, letterSpacing: "0.05em", color: "var(--secondary-text-color)", lineHeight: 1.2, whiteSpace: "nowrap" }}>{label}</span>
          ))}
        </button>
      ) : (
        <div style={{ width: 340, flexShrink: 0, ...REFERENCE_SIDEBAR_VIEWPORT_STYLE, display: "flex", flexDirection: "column", border: "1px solid var(--border-color)", borderRadius: 8, overflow: "hidden", background: "var(--card-bg)" }}>
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
            competenceCounts={session.assemblyHighlightCtx.competenceCounts || {}}
            finalAssemblyText={session.assemblyHighlightCtx.finalAssemblyTextNormalized || ""}
            hireProblem={session.hireProblem}
            onHireProblemChange={session.setHireProblem}
            onCollapsePanel={() => setReferenceSidebarCollapsed(true)}
          />
        </div>
      )}

      {agenticStage !== "assembly" && hasAgenticAssembly && (
        <div style={{ position: "fixed", bottom: 0, left: toggleX, zIndex: 20, pointerEvents: "none", transform: "translateX(-50%)" }}>
          <button onClick={() => { setAgenticStage("assembly"); }} style={{ padding: "8px 20px", border: "1px solid var(--border-color)", borderBottom: "none", borderRadius: "12px 12px 0 0", backgroundColor: "var(--button-bg)", color: "var(--button-text)", cursor: "pointer", boxShadow: "0 -2px 10px rgba(0,0,0,0.1)", pointerEvents: "auto", fontSize: "14px", fontWeight: "500" }}>↓ To final assembly</button>
        </div>
      )}
    </div>
  );
}
