import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useNavigate, useLocation, Navigate } from "react-router-dom";
import PhaseFlow from "../components/PhaseFlow";
import LetterTabs from "../components/LetterTabs";
import JobDescriptionColumn from "../components/JobDescriptionColumn";
import LanguageConfig from "../components/LanguageConfig";
import { useJobSession } from "../contexts/JobSessionContext";
import { useLanguages } from "../contexts/LanguageContext";
import { fetchWithHeartbeat, retryApiCall } from "../utils/apiHelpers";
import { splitIntoParagraphs } from "../utils/split";
import { phases as phaseModules } from "../components/phases";
import { mergeAgentContextFromFeedback, mergeExtraInfoFromFeedback } from "../components/phases/feedbackItemUtils";
import { persistLetterDocument, buildVendorAiLetters } from "../utils/persistLetterDocument";

const REFERENCE_SIDEBAR_VIEWPORT_STYLE = {
  alignSelf: "flex-start",
  position: "sticky",
  top: 20,
  height: "calc(100vh - 40px)",
  maxHeight: "calc(100vh - 40px)",
  boxSizing: "border-box",
};

export default function VendorFlowPage() {
  const navigate = useNavigate();
  const navLocation = useLocation();
  const session = useJobSession();
  const { enabledLanguages } = useLanguages();

  const [vendorStage, setVendorStage] = useState("phases");
  const [vendorParagraphs, setVendorParagraphs] = useState({});
  const [finalParagraphs, setFinalParagraphs] = useState([]);
  const [letters, setLetters] = useState({});
  const [vendorCosts, setVendorCosts] = useState({});
  const [vendorRefineCosts, setVendorRefineCosts] = useState({});
  const [failedVendors, setFailedVendors] = useState({});
  const [phaseErrors, setPhaseErrors] = useState({});
  const [phaseSessions, setPhaseSessions] = useState({});
  const [phaseFlowResetKey, setPhaseFlowResetKey] = useState(0);
  const [assemblyVisible, setAssemblyVisible] = useState(true);
  const [referenceSidebarCollapsed, setReferenceSidebarCollapsed] = useState(false);

  const phaseRegistryRef = useRef(null);
  const draftFeedbackRegistryRef = useRef({});
  const pendingShelfEntriesRef = useRef(null);
  const startedRef = useRef(false);

  const vendorsList = Array.from(session.selectedVendors);
  const hasVendorAssembly = vendorsList.some((v) => letters[v]);
  const toggleX = "40%";

  const extractErrorMessage = useCallback((error) => {
    if (!error) return "Unknown error";
    const errorStr = typeof error === "string" ? error : (error.message || String(error));
    if (error instanceof TypeError && error.message.includes("fetch")) {
      return "Network error: Unable to connect to server. Please check your connection.";
    }
    const providerMessageMatch = errorStr.match(/(?:'message'|"message")\s*:\s*'((?:[^'\\]|\\.)*)'/);
    if (providerMessageMatch) return providerMessageMatch[1].replace(/\\'/g, "'").trim() || errorStr;
    const providerMessageDouble = errorStr.match(/(?:'message'|"message")\s*:\s*"((?:[^"\\]|\\.)*)"/);
    if (providerMessageDouble) return providerMessageDouble[1].replace(/\\"/g, '"').trim() || errorStr;
    try {
      if (errorStr.includes("API error occurred:")) {
        const bodyMatch = errorStr.match(/Body:\s*({[\s\S]*})/);
        if (bodyMatch) { const body = JSON.parse(bodyMatch[1]); return body.detail || body.message || errorStr; }
        const detailMatch = errorStr.match(/"detail"\s*:\s*"([^"]+)"/);
        if (detailMatch) return detailMatch[1];
      }
      const parsed = JSON.parse(errorStr);
      if (parsed.detail) return parsed.detail;
      if (parsed.message) return parsed.message;
      if (parsed.error?.message) return parsed.error.message;
    } catch (_) { /* not JSON */ }
    return errorStr.replace(/^Error:\s*/, "").trim() || "Unknown error";
  }, []);

  const getStateForRestore = useCallback(() => ({
    jobText: session.jobText || "",
    cvText: "",
    extractedData: session.extractedData,
    phaseRegistry: phaseRegistryRef.current,
  }), [session.jobText, session.extractedData]);

  useEffect(() => {
    session.registerRestoreStateGetter(getStateForRestore);
    return () => {
      session.registerRestoreStateGetter(() => ({
        jobText: session.jobText || "",
        cvText: "",
        extractedData: session.extractedData,
        phaseRegistry: null,
      }));
    };
  }, [session, getStateForRestore]);

  const phaseErrorKey = (phase, vendor) => `${phase}:${vendor}`;

  const setPhaseVendorError = (phase, vendor, message) => {
    setPhaseErrors((prev) => ({ ...prev, [phaseErrorKey(phase, vendor)]: message }));
  };

  const clearPhaseVendorError = (phase, vendor) => {
    setPhaseErrors((prev) => {
      const key = phaseErrorKey(phase, vendor);
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const setPhaseCardFetchError = useCallback((phaseName, vendor, message) => {
    if (!phaseRegistryRef.current) return;
    const phase = phaseRegistryRef.current.find((p) => p.phase === phaseName);
    if (!phase) return;
    if (!phase.cardErrors) phase.cardErrors = {};
    if (message) phase.cardErrors[vendor] = message;
    else delete phase.cardErrors[vendor];
  }, []);

  const populatePhaseShelf = useCallback((phaseName, vendor, data) => {
    if (phaseRegistryRef.current) {
      const phase = phaseRegistryRef.current.find((p) => p.phase === phaseName);
      if (phase) {
        phase.cardData[vendor] = data;
        if (phaseName === "plan" && phase.approvedVendors) phase.approvedVendors.delete(vendor);
        if (phase.cardErrors && Object.prototype.hasOwnProperty.call(phase.cardErrors, vendor)) delete phase.cardErrors[vendor];
        clearPhaseVendorError(phaseName, vendor);
      }
    }
  }, []);

  const applyShelfEntries = useCallback((entries) => {
    if (!Array.isArray(entries) || entries.length === 0) return false;
    if (!phaseRegistryRef.current) { pendingShelfEntriesRef.current = entries; return false; }
    entries.forEach(({ phaseName, vendor, data }) => populatePhaseShelf(phaseName, vendor, data));
    pendingShelfEntriesRef.current = null;
    return true;
  }, [populatePhaseShelf]);

  useEffect(() => {
    const restore = session.pendingVendorRestore;
    if (!restore) return;
    startedRef.current = true;
    setVendorStage(restore.vendorStage || "phases");
    if (restore.assemblyVisible) setAssemblyVisible(true);
    if (restore.shelfEntries?.length) {
      applyShelfEntries(restore.shelfEntries);
      setTimeout(() => applyShelfEntries(restore.shelfEntries), 0);
      setTimeout(() => applyShelfEntries(restore.shelfEntries), 50);
    }
    if (restore.letters && Object.keys(restore.letters).length > 0) {
      setLetters((prev) => ({ ...prev, ...restore.letters }));
      const paragraphs = {};
      Object.entries(restore.letters).forEach(([vendor, text]) => {
        paragraphs[vendor] = splitIntoParagraphs(text || "", vendor);
      });
      setVendorParagraphs((prev) => ({ ...prev, ...paragraphs }));
      setFinalParagraphs((prev) => (prev?.length ? prev : Object.values(paragraphs)[0] || prev));
    }
    session.clearPendingVendorRestore();
  }, [session.pendingVendorRestore, applyShelfEntries, session]);

  const clearPhaseRegistryForNewRun = () => {
    const phases = phaseRegistryRef.current;
    if (!phases) return;
    for (const phase of phases) {
      phase.approvedVendors?.clear?.();
      if (phase.cardData) { for (const v of Object.keys(phase.cardData)) delete phase.cardData[v]; }
      if (phase.phase === "plan" && phase.planApproveRunners) phase.planApproveRunners.clear();
    }
  };

  const startInitialVendorPhase = useCallback(async (vendor, sessionId) => {
    const phaseName = session.includePlanStep ? "plan" : "draft";
    const url = session.includePlanStep ? `/api/phases/plan/${vendor}/` : `/api/phases/draft/${vendor}/`;
    const body = { session_id: sessionId };
    if (session.selectedCompanyReport) body.company_report = session.selectedCompanyReport;
    const result = await fetchWithHeartbeat(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, { getState: getStateForRestore });
    if (result.isHeartbeat) return null;
    populatePhaseShelf(phaseName, vendor, result.data);
    setPhaseSessions((prev) => ({ ...prev, [vendor]: sessionId }));
    if (!session.documentId && result.data?.document?.id) session.setDocumentId(result.data.document.id);
    return result.data;
  }, [session.includePlanStep, session.selectedCompanyReport, session.documentId, getStateForRestore, populatePhaseShelf, session]);

  const approvePhase = useCallback(async (phase, vendor, edits = {}) => {
    if (phase === "plan") {
      const sessionId = phaseSessions[vendor] || session.phaseSessionId;
      const payload = { session_id: sessionId, letter_plan: edits.letter_plan };
      if (session.selectedCompanyReport) payload.company_report = session.selectedCompanyReport;
      try {
        const result = await fetchWithHeartbeat(`/api/phases/draft/${vendor}/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, { getState: getStateForRestore });
        if (result.isHeartbeat) return null;
        populatePhaseShelf("draft", vendor, result.data);
        return result.data;
      } catch (e) {
        console.error("Draft phase error after plan approval", e);
        setPhaseVendorError("plan", vendor, extractErrorMessage(e));
        throw new Error(extractErrorMessage(e));
      }
    }
    if (phase === "draft") {
      const sessionId = phaseSessions[vendor] || session.phaseSessionId;
      const payload = { session_id: sessionId };
      if (edits.draft_letter) payload.draft_letter = edits.draft_letter;
      if (edits.company_report) payload.company_report = edits.company_report;
      if (edits.feedback_overrides) payload.feedback_override = edits.feedback_overrides;
      try {
        const result = await fetchWithHeartbeat(`/api/phases/refine/${vendor}/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }, { getState: getStateForRestore });
        if (result.isHeartbeat) return null;
        const data = result.data;
        const currentDraft = phaseRegistryRef.current?.find(p => p.phase === "draft");
        const currentData = currentDraft?.cardData[vendor] || {};
        const updatedDraftData = { ...currentData, ...edits };
        if (edits.feedback_overrides) updatedDraftData.feedback = { ...(currentData.feedback || {}), ...edits.feedback_overrides };
        populatePhaseShelf("draft", vendor, updatedDraftData);
        const finalText = data.final_letter || edits.draft_letter || "";
        setLetters((prev) => ({ ...prev, [vendor]: finalText }));
        setVendorParagraphs((prev) => ({ ...prev, [vendor]: splitIntoParagraphs(finalText, vendor) }));
        setVendorCosts((prev) => ({ ...prev, [vendor]: data.cost ?? prev[vendor] ?? 0 }));
        const allDone = vendorsList.every((v) => letters[v] || (v === vendor && finalText));
        if (allDone) { setVendorStage("assembly"); setAssemblyVisible(true); }
        return data;
      } catch (e) {
        console.error("Refine generation error", e);
        setPhaseVendorError("draft", vendor, extractErrorMessage(e));
        throw new Error(extractErrorMessage(e));
      }
    }
  }, [phaseSessions, session.phaseSessionId, session.selectedCompanyReport, getStateForRestore, populatePhaseShelf, extractErrorMessage, vendorsList, letters]);

  const approveAllPhase = useCallback(async (phase) => {
    await Promise.all(vendorsList.map((v) => approvePhase(phase, v, {})));
  }, [vendorsList, approvePhase]);

  const createRetryForPhase = useCallback((phaseName, vendor) => {
    const phaseModule = phaseModules[phaseName];
    if (!phaseModule || !phaseModule.getApiConfig) throw new Error(`Phase module "${phaseName}" not found`);
    const apiConfig = phaseModule.getApiConfig(vendor, session.phaseSessionId, null);
    if (!apiConfig) throw new Error(`API config not available for phase "${phaseName}"`);
    const onResult = (data) => {
      populatePhaseShelf(phaseName, vendor, data);
      if (phaseModule.handleRetryResult) {
        phaseModule.handleRetryResult(data, {
          vendor, sessionId: session.phaseSessionId,
          setDocumentId: (id) => { if (!session.documentId) session.setDocumentId(id); },
          setPhaseSessions, setUiStage: setVendorStage, setShowInput: () => setVendorStage("input"),
          setLetters, setVendorParagraphs, setVendorCosts, splitIntoParagraphs,
        });
      }
    };
    return () => retryApiCall(apiConfig.url, apiConfig.body, onResult);
  }, [session.phaseSessionId, session.documentId, populatePhaseShelf, session]);

  const onClearPhaseFetchError = useCallback((phaseName, vendor) => setPhaseCardFetchError(phaseName, vendor, null), [setPhaseCardFetchError]);

  const onRetryPhaseFetch = useCallback(async (phaseName, vendor) => {
    const expectedPhase = session.includePlanStep ? "plan" : "draft";
    if (phaseName !== expectedPhase) return;
    const sessionId = phaseSessions[vendor] || session.phaseSessionId;
    if (!sessionId) { setPhaseCardFetchError(expectedPhase, vendor, "No session ID. Return to job intake and start the vendor flow again."); return; }
    setPhaseCardFetchError(expectedPhase, vendor, null);
    try {
      const body = { session_id: sessionId };
      if (session.selectedCompanyReport) body.company_report = session.selectedCompanyReport;
      const url = session.includePlanStep ? `/api/phases/plan/${vendor}/` : `/api/phases/draft/${vendor}/`;
      const result = await fetchWithHeartbeat(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, { getState: getStateForRestore });
      if (result.isHeartbeat) return;
      populatePhaseShelf(expectedPhase, vendor, result.data);
      setPhaseSessions((prev) => ({ ...prev, [vendor]: sessionId }));
      const docId = result.data?.document?.id;
      if (docId) session.setDocumentId((prev) => prev || docId);
    } catch (e) {
      console.error(`Retry ${expectedPhase} fetch failed for ${vendor}:`, e);
      setPhaseCardFetchError(expectedPhase, vendor, extractErrorMessage(e));
    }
  }, [session.includePlanStep, phaseSessions, session.phaseSessionId, session.selectedCompanyReport, getStateForRestore, setPhaseCardFetchError, populatePhaseShelf, extractErrorMessage, session]);

  const goBackToJobIntake = useCallback(async () => {
    navigate("/");
  }, [navigate]);

  const handleCloseSessionAndRestart = useCallback(async () => {
    const hasUnsaved = Object.values(letters || {}).some((text) => typeof text === "string" && text.trim().length > 0);
    if (hasUnsaved && !window.confirm("Your unsaved work will be discarded. Continue?")) return;
    try {
      await fetchWithHeartbeat("/api/phases/clear/", { method: "POST" });
    } catch (e) {
      console.error("Failed to clear session:", e);
      session.setError("Failed to close session. Please try again.");
      return;
    }
    session.resetIntake();
    navigate("/");
  }, [letters, session, navigate]);

  const handlePersistFinalLetter = useCallback(async (finalText) => {
    if (!finalText) {
      session.setError("No letter text to save");
      throw new Error("No letter text to save");
    }
    const aiLetters = buildVendorAiLetters({
      letters,
      vendorCosts,
      vendorFeedback: session.vendorFeedback,
      finalParagraphs,
    });
    let feedbackExtraInfo = null;
    let feedbackAgentContext = null;
    const draftPhase = phaseRegistryRef.current?.find((p) => p.phase === "draft");
    const reg = draftFeedbackRegistryRef.current || {};
    let acc = [];
    let agentAcc = [];
    for (const v of vendorsList) {
      let merged = false;
      if (typeof reg[v] === "function") {
        const snap = reg[v]();
        if (snap?.feedbackKeys?.length) {
          acc = mergeExtraInfoFromFeedback(acc, snap.feedback, snap.feedback_overrides || {}, snap.feedbackKeys);
          agentAcc = mergeAgentContextFromFeedback(agentAcc, snap.feedback, snap.feedback_overrides || {}, snap.feedbackKeys);
          merged = true;
        }
      }
      if (!merged) {
        const shelfData = draftPhase?.cardData?.[v];
        const fromShelf = shelfData ? phaseModules.draft.initializeFeedbackFromData(shelfData) : null;
        if (fromShelf?.feedbackKeys?.length) {
          acc = mergeExtraInfoFromFeedback(acc, fromShelf.feedback, {}, fromShelf.feedbackKeys);
          agentAcc = mergeAgentContextFromFeedback(agentAcc, fromShelf.feedback, {}, fromShelf.feedbackKeys);
        }
      }
    }
    feedbackExtraInfo = acc.length > 0 ? acc : [];
    feedbackAgentContext = agentAcc.length > 0 ? agentAcc : [];
    try {
      session.setSavingFinal(true);
      session.setDocumentSaveNotice(null);
      const result = await persistLetterDocument({
        letterText: finalText,
        jobFields: {
          companyName: session.companyName, jobTitle: session.jobTitle, location: session.location,
          language: session.language, salary: session.salary, requirements: session.requirements, jobText: session.jobText,
        },
        documentId: session.documentId,
        aiLetters,
        feedbackExtras: { feedback_extra_info: feedbackExtraInfo, feedback_agent_context: feedbackAgentContext },
      });
      if (result.warnings.length > 0) session.setDocumentSaveNotice(result.warnings.join(" "));
      if (result.documentId && !session.documentId) session.setDocumentId(result.documentId);
    } catch (e) {
      const errorMsg = `Failed to save letter: ${e.message || e}`;
      session.setError(errorMsg);
      throw new Error(errorMsg);
    } finally {
      session.setSavingFinal(false);
    }
  }, [letters, vendorCosts, session, finalParagraphs, vendorsList]);

  const onAddParagraph = (paraObj) => setFinalParagraphs((prev) => [...prev, { ...paraObj }]);

  const approveExtraction = useCallback(async (vendor) => {
    if (!session.phaseSessionId || !vendor) return;
    session.setError(null);
    try {
      await fetchWithHeartbeat("/api/phases/session/", { method: "POST", body: JSON.stringify(session.buildJobSessionPayload(session.phaseSessionId)) });
      await startInitialVendorPhase(vendor, session.phaseSessionId);
    } catch (e) {
      console.error(`${session.includePlanStep ? "Plan" : "Draft"} phase error after extraction approval:`, e);
      setPhaseCardFetchError(session.includePlanStep ? "plan" : "draft", vendor, extractErrorMessage(e));
    }
  }, [session, startInitialVendorPhase, setPhaseCardFetchError, extractErrorMessage]);

  useEffect(() => {
    if (startedRef.current) return;
    if (!navLocation.state?.start) return;
    startedRef.current = true;
    navigate(navLocation.pathname, { replace: true, state: {} });

    setPhaseErrors({});
    setLetters({});
    setVendorCosts({});
    setFailedVendors({});
    setVendorParagraphs({});
    setFinalParagraphs([]);
    setPhaseSessions({});
    clearPhaseRegistryForNewRun();
    setPhaseFlowResetKey((k) => k + 1);
    setVendorStage("phases");

    const vList = Array.from(session.selectedVendors);
    const sid = session.phaseSessionId;
    if (!sid) return;
    vList.forEach((vendor) => {
      (async () => {
        try {
          await startInitialVendorPhase(vendor, sid);
        } catch (e) {
          console.error(`${session.includePlanStep ? "Plan" : "Draft"} phase error for ${vendor}:`, e);
          setPhaseCardFetchError(session.includePlanStep ? "plan" : "draft", vendor, extractErrorMessage(e));
        }
      })();
    });
  }, [navLocation.state?.start]);

  if (
    !navLocation.state?.start &&
    !navLocation.state?.rehydrated &&
    !session.phaseSessionId &&
    !startedRef.current &&
    !session.pendingVendorRestore
  ) {
    return <Navigate to="/" replace />;
  }

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 12, width: "100%", flex: 1, boxSizing: "border-box", overflow: "hidden" }}>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10, position: "relative", flexWrap: "wrap" }}>
          <button onClick={goBackToJobIntake} style={{ padding: "8px 16px", backgroundColor: "var(--button-bg)", color: "var(--button-text)", border: "1px solid var(--border-color)", borderRadius: "4px", cursor: "pointer" }}>← Back to job details</button>
          <button type="button" onClick={handleCloseSessionAndRestart} style={{ padding: "8px 16px", backgroundColor: "#b91c1c", color: "white", border: "1px solid #991b1b", borderRadius: "4px", cursor: "pointer" }} title="Clear current session and restart with a blank input form">Close session and restart</button>
          {vendorStage === "assembly" && assemblyVisible && (
            <div style={{ position: "absolute", left: toggleX, transform: "translateX(-50%)" }}>
              <button onClick={() => setAssemblyVisible(false)} style={{ padding: "10px 14px", border: "1px solid var(--border-color)", borderRadius: "999px", backgroundColor: "var(--button-bg)", color: "var(--button-text)", cursor: "pointer", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" }}>↑ Show phases</button>
            </div>
          )}
          <div style={{ marginLeft: "auto" }}><LanguageConfig /></div>
        </div>
        {session.error && <p style={{ color: "var(--error-text)" }}>{session.error}</p>}
        {session.documentSaveNotice && (
          <p role="status" style={{ color: "var(--secondary-text-color)", background: "var(--warning-bg)", border: "1px solid var(--warning-border)", padding: "10px 12px", borderRadius: 4 }}>{session.documentSaveNotice}</p>
        )}
        <div style={{ display: (vendorStage === "assembly" && assemblyVisible) ? "none" : "flex", flex: 1, minHeight: 0, flexDirection: "column", overflow: "auto" }}>
          <PhaseFlow
            vendorsList={vendorsList}
            flowResetKey={phaseFlowResetKey}
            includePlanStep={session.includePlanStep}
            onEditChange={() => {}}
            onApprove={approvePhase}
            onApproveAll={approveAllPhase}
            sessionId={session.phaseSessionId}
            documentId={session.documentId}
            draftFeedbackRegistryRef={draftFeedbackRegistryRef}
            onClearPhaseFetchError={onClearPhaseFetchError}
            onRetryPhaseFetch={onRetryPhaseFetch}
            onRegisterPhases={(phases) => {
              phaseRegistryRef.current = phases;
              if (pendingShelfEntriesRef.current) applyShelfEntries(pendingShelfEntriesRef.current);
            }}
            onPhaseComplete={() => {}}
          />
        </div>

        {vendorStage === "assembly" && (
          <div style={{ position: "relative", paddingTop: 4, display: assemblyVisible ? "block" : "none" }}>
            <LetterTabs
              vendorsList={vendorsList}
              vendorParagraphs={vendorParagraphs}
              vendorCosts={vendorCosts}
              vendorRefineCosts={vendorRefineCosts}
              finalParagraphs={finalParagraphs}
              setFinalParagraphs={setFinalParagraphs}
              originalText={session.jobText}
              requirements={session.requirements}
              competences={session.competences}
              competenceScaleConfig={session.competenceScaleConfig}
              competenceOverrides={session.competenceOverrides}
              vendorColors={session.vendorColors}
              failedVendors={failedVendors}
              onRetry={async (vendor) => {
                setFailedVendors((prev) => { const next = { ...prev }; delete next[vendor]; return next; });
                try { await approvePhase("draft", vendor, {}); } catch (e) {
                  console.error("Retry error:", e);
                  setFailedVendors((prev) => ({ ...prev, [vendor]: extractErrorMessage(e) }));
                }
              }}
              onAddParagraph={onAddParagraph}
              onSave={handlePersistFinalLetter}
              savingFinal={session.savingFinal}
              vendorFeedback={session.vendorFeedback}
              setVendorFeedback={session.setVendorFeedback}
              refineSamples={{}}
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

      {Object.keys(failedVendors).length > 0 && (
        <div style={{ marginTop: 10, padding: 10, background: "var(--warning-bg)", border: "1px solid var(--warning-border)", color: "var(--text-color)", borderRadius: "4px" }}>
          <h3 style={{ marginTop: 0 }}>Failed Vendors:</h3>
          {Object.entries(failedVendors).map(([vendor, errorMsg]) => (
            <div key={vendor} style={{ marginBottom: 10 }}>
              <strong style={{ color: "var(--text-color)" }}>{vendor}:</strong> {errorMsg}
              <button onClick={async () => {
                setFailedVendors((prev) => { const next = { ...prev }; delete next[vendor]; return next; });
                try { const retryFn = createRetryForPhase("draft", vendor); await retryFn(); } catch (e) {
                  console.error("Retry error:", e);
                  setFailedVendors((prev) => ({ ...prev, [vendor]: extractErrorMessage(e) }));
                }
              }} style={{ marginLeft: 10, padding: "4px 8px", backgroundColor: "var(--button-bg)", color: "var(--button-text)", border: "1px solid var(--border-color)", borderRadius: "4px", cursor: "pointer" }}>Retry</button>
            </div>
          ))}
        </div>
      )}

      {vendorStage !== "assembly" && hasVendorAssembly && (
        <div style={{ position: "fixed", bottom: 0, left: toggleX, zIndex: 20, pointerEvents: "none", transform: "translateX(-50%)" }}>
          <button onClick={() => { setVendorStage("assembly"); setAssemblyVisible(true); }} style={{ padding: "8px 20px", border: "1px solid var(--border-color)", borderBottom: "none", borderRadius: "12px 12px 0 0", backgroundColor: "var(--button-bg)", color: "var(--button-text)", cursor: "pointer", boxShadow: "0 -2px 10px rgba(0,0,0,0.1)", pointerEvents: "auto", fontSize: "14px", fontWeight: "500" }}>↓ To final assembly</button>
        </div>
      )}
      {vendorStage === "assembly" && !assemblyVisible && (
        <div style={{ position: "fixed", bottom: 0, left: toggleX, transform: "translateX(-50%)", zIndex: 20, pointerEvents: "none" }}>
          <button onClick={() => setAssemblyVisible(true)} style={{ padding: "8px 20px", border: "1px solid var(--border-color)", borderBottom: "none", borderRadius: "12px 12px 0 0", backgroundColor: "var(--button-bg)", color: "var(--button-text)", cursor: "pointer", boxShadow: "0 -2px 10px rgba(0,0,0,0.1)", pointerEvents: "auto", fontSize: "14px", fontWeight: "500" }}>↓ Back to assembly</button>
        </div>
      )}
    </div>
  );
}
