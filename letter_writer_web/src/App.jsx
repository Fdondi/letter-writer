import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import VendorSelector from "./components/VendorSelector";
import LetterTabs from "./components/LetterTabs";
import JobDescriptionColumn from "./components/JobDescriptionColumn";
import StyleInstructionsBlade from "./components/StyleInstructionsBlade";
import PhaseFlow from "./components/PhaseFlow";
import AgenticFlow from "./components/AgenticFlow";
import DocumentsPage from "./components/DocumentsPage";
import PersonalDataPage from "./components/PersonalDataPage";
import SettingsPage from "./components/SettingsPage";
import OverlayPanel from "./components/OverlayPanel";
import LanguageConfig from "./components/LanguageConfig";
import LanguageSelector from "./components/LanguageSelector";
import AuthButton from "./components/AuthButton";
import AppVersionLabel from "./components/AppVersionLabel";
import CostDisplay from "./components/CostDisplay";
import CostsPage from "./components/CostsPage";
import LocalPricingWarningModal, { dismissLocalPricingWarningForSession } from "./components/LocalPricingWarningModal.jsx";
import SessionExpiredModal from "./components/SessionExpiredModal.jsx";
import CompetencesList from "./components/CompetencesList";
import ResearchComponent from "./components/ResearchComponent";
import SimilarOffersCarousel from "./components/SimilarOffersCarousel";
import AutocompleteFlow from "./components/AutocompleteFlow";
import AutocompletePlanModelSelect from "./components/AutocompletePlanModelSelect";
import { splitIntoParagraphs } from "./utils/split";
import { fetchWithHeartbeat, retryApiCall, initializeCsrfToken, getCsrfToken, publishUserMonthlyCost } from "./utils/apiHelpers";
import { COST_TRACKING_ERROR_EVENT } from "./utils/costTracking";
import { scheduleGoogleOAuthRedirect, clearOAuthRedirectCooldown } from "./utils/googleOAuthRedirect";
import {
  AUTH_SESSION_EXPIRED_EVENT,
  AUTH_SESSION_RESTORED_EVENT,
  fetchAuthStatus,
  markInitialAuthCheckComplete,
  reportSessionExpired,
} from "./utils/authSession.js";
import { syncStateToServer } from "./utils/localState.js";
import { showNotification } from "./utils/apiNotifications";
import { phases as phaseModules } from "./components/phases";
import { translateText } from "./utils/translate";
import { useLanguages } from "./contexts/LanguageContext";
import { createTextDiff } from "./utils/diff";
import { getScaleConfig, getEffectiveRating, getEffectiveImportance, buildCompetenceRatingsForProfile } from "./utils/competenceScales";
import { mergeAgentContextFromFeedback, mergeExtraInfoFromFeedback } from "./components/phases/feedbackItemUtils";
import {
  buildAutocompletePlanAiLetter,
  clearAutocompleteFlowCache,
  sectionsToProposalText,
} from "./utils/autocompleteEditor";

function generateColors(vendors) {
  const step = 360 / vendors.length;
  const isDarkMode =
    window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return vendors.reduce((acc, v, idx) => {
    const hue = Math.round(idx * step);
    acc[v] = isDarkMode ? `hsl(${hue}, 40%, 30%)` : `hsl(${hue}, 70%, 85%)`;
    return acc;
  }, {});
}

const AGENTIC_TOPICS = ["instruction", "company_fit", "goal_fit", "precision", "user_fit", "human", "accuracy"];

export default function App({ flow = "intake" }) {
  const navigate = useNavigate();
  const navLocation = useLocation();
  // ALL hooks must be declared before any conditional returns (React rules)
  // Authentication state
  const [isAuthenticated, setIsAuthenticated] = useState(null); // null = checking, true = authenticated, false = not authenticated
  const [checkingAuth, setCheckingAuth] = useState(true); // Start checking on mount
  const [showSessionExpiredModal, setShowSessionExpiredModal] = useState(false);
  const [authRefreshGeneration, setAuthRefreshGeneration] = useState(0);

  // All other state hooks (must be before conditional returns)
  const [vendors, setVendors] = useState([]);
  const [vendorColors, setVendorColors] = useState({});
  const [vendorParagraphs, setVendorParagraphs] = useState({});
  const [finalParagraphs, setFinalParagraphs] = useState([]);
  const [jobText, setJobText] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [location, setLocation] = useState("");
  const [language, setLanguage] = useState("");
  const [salary, setSalary] = useState("");
  const [requirements, setRequirements] = useState([]);
  const [competences, setCompetences] = useState({}); // { skill: { need, level } } or legacy
  const [hireProblem, setHireProblem] = useState("");
  const [competenceOverrides, setCompetenceOverrides] = useState({}); // { skill: { presence?, importance? } } user-edited ratings
  const [competenceScaleConfig, setCompetenceScaleConfig] = useState(getScaleConfig);
  const competencesScrollRef = useRef(null);
  const [canScrollCompetencesUp, setCanScrollCompetencesUp] = useState(false);
  const [canScrollCompetencesDown, setCanScrollCompetencesDown] = useState(false);
  const [pointOfContact, setPointOfContact] = useState({
    name: "",
    role: "",
    contact_details: "",
    notes: "",
    company: "",
  });
  const [showPointOfContact, setShowPointOfContact] = useState(false);
  const [additionalUserInfo, setAdditionalUserInfo] = useState("");
  const [additionalCompanyInfo, setAdditionalCompanyInfo] = useState("");
  const [structureInstructions, setStructureInstructions] = useState("");
  const [showAdditionalInfo, setShowAdditionalInfo] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractionError, setExtractionError] = useState(null);
  const [documentId, setDocumentId] = useState(null);
  const [selectedVendors, setSelectedVendors] = useState(new Set());
  const [letters, setLetters] = useState({}); // vendor -> text
  const [vendorCosts, setVendorCosts] = useState({}); // vendor -> cost (total cumulative)
  const [vendorRefineCosts, setVendorRefineCosts] = useState({}); // vendor -> refine phase cost (final letter cost)
  const [failedVendors, setFailedVendors] = useState({}); // vendor -> error message
  const [phaseErrors, setPhaseErrors] = useState({}); // `${phase}:${vendor}` -> error message
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [documentSaveNotice, setDocumentSaveNotice] = useState(null);
  const [costTrackingError, setCostTrackingError] = useState(null);
  const [showStyleBlade, setShowStyleBlade] = useState(false);
  const [vendorStage, setVendorStage] = useState("input"); // vendor flow: input | phases | assembly
  const [agenticStage, setAgenticStage] = useState("input"); // agentic flow: input | agentic | assembly
  const [phaseSessionId, setPhaseSessionId] = useState(null);
  const [phaseSessions, setPhaseSessions] = useState({}); // vendor -> session_id
  const [phaseFlowResetKey, setPhaseFlowResetKey] = useState(0);
  const [savingFinal, setSavingFinal] = useState(false);
  const [activeTab, setActiveTab] = useState("compose"); // legacy, kept for CostDisplay/localState; main content is always compose
  const [showCvOverlay, setShowCvOverlay] = useState(false);
  const [showDocumentsOverlay, setShowDocumentsOverlay] = useState(false);
  const [showSettingsOverlay, setShowSettingsOverlay] = useState(false);
  const [showCostsOverlay, setShowCostsOverlay] = useState(false);
  const [localPricingConfigured, setLocalPricingConfigured] = useState(true);
  const [localPricingModalOpen, setLocalPricingModalOpen] = useState(false);
  const [localPricingDismissChecked, setLocalPricingDismissChecked] = useState(false);
  const pendingLocalEnableActionRef = useRef(null);
  const [assemblyVisible, setAssemblyVisible] = useState(true); // vendor flow: when in assembly stage, show assembly or phases
  const [extractedData, setExtractedData] = useState(null); // Track extracted data to detect modifications
  const [vendorFeedback, setVendorFeedback] = useState({}); // vendor -> { rating, comment }

  const showInput =
    flow === "vendor"
      ? vendorStage === "input"
      : flow === "agentic"
        ? agenticStage === "input"
        : false;
  const showJobIntake = flow === "intake";
  const hasPointOfContactData = useMemo(() => (
    Boolean(pointOfContact.name?.trim()) ||
    Boolean(pointOfContact.role?.trim()) ||
    Boolean(pointOfContact.contact_details?.trim()) ||
    Boolean(pointOfContact.notes?.trim()) ||
    Boolean(pointOfContact.company?.trim())
  ), [pointOfContact]);

  // Agentic (per-topic) flow state
  const [agenticState, setAgenticState] = useState(null);
  const [agenticLoading, setAgenticLoading] = useState(false);
  const [agenticError, setAgenticError] = useState(null);
  const [agenticMaxRounds, setAgenticMaxRounds] = useState(3);
  const [agenticSubCommentRounds, setAgenticSubCommentRounds] = useState(0);
  const [agenticSavingFinal, setAgenticSavingFinal] = useState(false);
  const [agenticSaveError, setAgenticSaveError] = useState(null);
  const [agenticFinalParagraphs, setAgenticFinalParagraphs] = useState([]);
  const rehydrationAttemptedRef = useRef(false);
  const latestFormSnapshotRef = useRef(null);
  // Best-known threads ref: updated whenever we receive non-empty threads.
  // Used as a last-resort fallback so the UI never loses comments it has already seen.
  const bestKnownThreadsRef = useRef(null);

  const normalizeAgenticThreads = useCallback((threadsPayload = {}, topicMetaPayload = {}) => {
    const threadsOut = AGENTIC_TOPICS.reduce((acc, topic) => ({ ...acc, [topic]: [] }), {});
    const topicMetaOut = {
      ...(topicMetaPayload && typeof topicMetaPayload === "object" ? topicMetaPayload : {}),
    };

    const assignTopic = (topicKey, rawValue) => {
      if (!topicKey || typeof topicKey !== "string") return;
      const topic = topicKey.trim();
      if (!topic) return;
      if (!(topic in threadsOut)) threadsOut[topic] = [];

      if (Array.isArray(rawValue)) {
        threadsOut[topic] = rawValue;
        return;
      }

      if (!rawValue || typeof rawValue !== "object") {
        threadsOut[topic] = [];
        return;
      }

      const candidateThread = Array.isArray(rawValue.thread)
        ? rawValue.thread
        : Array.isArray(rawValue.comments)
          ? rawValue.comments
          : Array.isArray(rawValue.messages)
            ? rawValue.messages
            : [];
      threadsOut[topic] = candidateThread;

      const round = rawValue.round;
      const done = rawValue.done;
      const messages = rawValue.messages_count ?? rawValue.count ?? rawValue.messages;
      if (round != null || done != null || messages != null || "waiting_for" in rawValue) {
        const nextMeta = {
          ...(topicMetaOut[topic] || {}),
          ...(round != null && { round }),
          ...(messages != null && { messages: Number.isFinite(Number(messages)) ? Number(messages) : candidateThread.length }),
          ...(done != null && { done: done === true }),
        };
        if ("waiting_for" in rawValue) {
          const wf = rawValue.waiting_for;
          if (wf != null && typeof wf === "object") {
            // Structured progress object from phase_progress — pass through as-is.
            nextMeta.waiting_for = wf;
          } else if (wf != null && String(wf).trim() !== "") {
            // Legacy string fallback.
            nextMeta.waiting_for = String(wf).trim();
          } else {
            delete nextMeta.waiting_for;
          }
        }
        topicMetaOut[topic] = nextMeta;
      }
    };

    if (Array.isArray(threadsPayload)) {
      threadsPayload.forEach((entry) => {
        if (!entry || typeof entry !== "object") return;
        const topic = entry.topic || entry.key || entry.name;
        const value = entry.thread ?? entry.comments ?? entry.messages ?? entry;
        assignTopic(topic, value);
      });
    } else if (threadsPayload && typeof threadsPayload === "object") {
      Object.entries(threadsPayload).forEach(([topic, value]) => assignTopic(topic, value));
    }

    return { threads: threadsOut, topicMeta: topicMetaOut };
  }, []);

  const stripAgenticThreadFields = useCallback((state) => {
    if (!state || typeof state !== "object") return state;
    const next = { ...state };
    delete next.threads;
    delete next.topic_meta;
    return next;
  }, []);

  const mergeAgenticUpdate = useCallback((prevState, update) => {
    const cleanUpdate = stripAgenticThreadFields(update);
    if (!cleanUpdate || typeof cleanUpdate !== "object") return prevState || null;
    return {
      ...(prevState || {}),
      ...cleanUpdate,
    };
  }, [stripAgenticThreadFields]);

  /** Keep the Max rounds input aligned with persisted server `max_rounds` (poll, add round, draft, etc.). */
  const syncAgenticMaxRoundsFromServer = useCallback((value) => {
    if (value == null || value === "") return;
    const n = Number(value);
    if (!Number.isFinite(n)) return;
    setAgenticMaxRounds(n);
  }, []);

  const syncAgenticSubCommentRoundsFromServer = useCallback((value) => {
    if (value == null || value === "") return;
    const n = Number(value);
    if (!Number.isFinite(n)) return;
    setAgenticSubCommentRounds(Math.max(0, Math.min(8, Math.floor(n))));
  }, []);

  const isFormSnapshotPristine = useCallback((snapshot) => {
    if (!snapshot || typeof snapshot !== "object") return false;
    const emptyPoc = !snapshot.pointOfContact || (
      !String(snapshot.pointOfContact.name || "").trim() &&
      !String(snapshot.pointOfContact.role || "").trim() &&
      !String(snapshot.pointOfContact.contact_details || "").trim() &&
      !String(snapshot.pointOfContact.notes || "").trim() &&
      !String(snapshot.pointOfContact.company || "").trim()
    );
    return (
      !String(snapshot.jobText || "").trim() &&
      !String(snapshot.companyName || "").trim() &&
      !String(snapshot.jobTitle || "").trim() &&
      !String(snapshot.location || "").trim() &&
      !String(snapshot.language || "").trim() &&
      !String(snapshot.salary || "").trim() &&
      (!Array.isArray(snapshot.requirements) || snapshot.requirements.length === 0) &&
      (!snapshot.competences || Object.keys(snapshot.competences).length === 0) &&
      emptyPoc &&
      !String(snapshot.additionalUserInfo || "").trim() &&
      !String(snapshot.additionalCompanyInfo || "").trim() &&
      !snapshot.extractedData
    );
  }, []);

  useEffect(() => {
    latestFormSnapshotRef.current = {
      jobText,
      companyName,
      jobTitle,
      location,
      language,
      salary,
      requirements,
      competences,
      pointOfContact,
      additionalUserInfo,
      additionalCompanyInfo,
      extractedData,
    };
  }, [
    jobText,
    companyName,
    jobTitle,
    location,
    language,
    salary,
    requirements,
    competences,
    pointOfContact,
    additionalUserInfo,
    additionalCompanyInfo,
    extractedData,
  ]);

  // Research state
  const [selectedCompanyReport, setSelectedCompanyReport] = useState(null);
  const [selectedTopDocs, setSelectedTopDocs] = useState(null);
  const [selectedPocReport, setSelectedPocReport] = useState(null);
  const [backgroundModels, setBackgroundModels] = useState(new Set()); // Loaded from backend on mount
  const [allSearchResults, setAllSearchResults] = useState([]); // All RAG-retrieved similar docs
  const [selectedDocIds, setSelectedDocIds] = useState(new Set()); // User-selected doc IDs for draft
  
  // Triggers for auto-research
  const [triggerCompanyResearch, setTriggerCompanyResearch] = useState(0);
  const [triggerPocResearch, setTriggerPocResearch] = useState(0);

  // Company extraction → countdown → research flow
  const [companyExtractionResult, setCompanyExtractionResult] = useState(null);
  const [companyResearchCountdown, setCompanyResearchCountdown] = useState(null);
  const [companyAutoResearchBlocked, setCompanyAutoResearchBlocked] = useState(false);
  const [companyResearchNotification, setCompanyResearchNotification] = useState(null);
  
  // Translation state for job text
  const { enabledLanguages } = useLanguages();
  const [referenceSidebarCollapsed, setReferenceSidebarCollapsed] = useState(false);
  const [competenceHighlightTerm, setCompetenceHighlightTerm] = useState(null);
  const [assemblyHighlightCtx, setAssemblyHighlightCtx] = useState(() => ({
    competenceCounts: {},
    finalAssemblyTextNormalized: "",
  }));

  const handleAssemblyHighlightCtx = useCallback((ctx) => {
    if (!ctx || typeof ctx !== "object") return;
    setAssemblyHighlightCtx({
      competenceCounts: ctx.competenceCounts || {},
      finalAssemblyTextNormalized: ctx.finalAssemblyTextNormalized || "",
    });
  }, []);

  const handleCompetenceTermClick = useCallback((term) => {
    setCompetenceHighlightTerm((prev) => (prev === term ? null : term));
  }, []);

  useEffect(() => {
    const inAssembly =
      (flow === "vendor" && vendorStage === "assembly") ||
      (flow === "agentic" && agenticStage === "assembly");
    if (!inAssembly) {
      setAssemblyHighlightCtx({ competenceCounts: {}, finalAssemblyTextNormalized: "" });
    }
  }, [flow, vendorStage, agenticStage]);
  const [jobTextViewLanguage, setJobTextViewLanguage] = useState("source");
  const [jobTextTranslations, setJobTextTranslations] = useState({});
  const [isTranslatingJobText, setIsTranslatingJobText] = useState(false);
  const [jobTextTranslationError, setJobTextTranslationError] = useState(null);
  const [lastJobTextSnapshot, setLastJobTextSnapshot] = useState(jobText);
  
  // Registry of phase objects from PhaseFlow
  const phaseRegistryRef = React.useRef(null);
  const draftFeedbackRegistryRef = useRef({});
  const agenticPhasesRef = useRef(null);
  const [, setPhaseRegistryTrigger] = useState(0); // For re-rendering when registry changes
  
  // Check authentication status on mount
  useEffect(() => {
    // Check authentication status immediately
    fetch("/api/auth/status/", {
      credentials: "include",
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.authenticated) {
          clearOAuthRedirectCooldown();
          setIsAuthenticated(true);
          markInitialAuthCheckComplete(true);
          // Initialize CSRF token after authentication is confirmed
          // This ensures the token is available for subsequent API calls
          initializeCsrfToken().catch((e) => {
            console.warn("Failed to initialize CSRF token after auth:", e);
          });
        } else {
          markInitialAuthCheckComplete(false);
          scheduleGoogleOAuthRedirect();
          setIsAuthenticated(false);
        }
        setCheckingAuth(false);
      })
      .catch((e) => {
        console.error("Failed to check auth status:", e);
        markInitialAuthCheckComplete(false);
        scheduleGoogleOAuthRedirect();
        setIsAuthenticated(false);
        setCheckingAuth(false);
      });
  }, []);

  useEffect(() => {
    if (!hasPointOfContactData) {
      setShowPointOfContact(false);
    }
  }, [hasPointOfContactData]);
  


  // Helper function to get current state for session restoration
  const getStateForRestore = React.useCallback(() => {
    return {
      jobText: jobText || "",
      cvText: "", // Not used in this app, but required by restore endpoint
      extractedData: extractedData,
      phaseRegistry: phaseRegistryRef.current,
    };
  }, [jobText, extractedData]);

  useEffect(() => {
    const onExpired = () => setShowSessionExpiredModal(true);
    const onRestored = () => {
      setShowSessionExpiredModal(false);
      setAuthRefreshGeneration((g) => g + 1);
    };
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, onExpired);
    window.addEventListener(AUTH_SESSION_RESTORED_EVENT, onRestored);
    return () => {
      window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, onExpired);
      window.removeEventListener(AUTH_SESSION_RESTORED_EVENT, onRestored);
    };
  }, []);

  useEffect(() => {
    if (!isAuthenticated || checkingAuth) return;

    const verifyStillAuthenticated = async () => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      try {
        const status = await fetchAuthStatus();
        if (!status.authenticated) {
          reportSessionExpired();
        }
      } catch (e) {
        console.warn("Auth status check failed:", e);
      }
    };

    document.addEventListener("visibilitychange", verifyStillAuthenticated);
    window.addEventListener("focus", verifyStillAuthenticated);
    return () => {
      document.removeEventListener("visibilitychange", verifyStillAuthenticated);
      window.removeEventListener("focus", verifyStillAuthenticated);
    };
  }, [isAuthenticated, checkingAuth]);

  useEffect(() => {
    if (authRefreshGeneration === 0) return;

    initializeCsrfToken().catch((e) => {
      console.warn("Failed to refresh CSRF token after re-auth:", e);
    });

    const state = getStateForRestore();
    syncStateToServer(state).catch((e) => {
      console.warn("Failed to sync local state to server after re-auth:", e);
    });
  }, [authRefreshGeneration, getStateForRestore]);

  // Update colors when system theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      setVendorColors(generateColors(vendors));
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [vendors]);

  // Reset job text translation cache when source text changes
  useEffect(() => {
    if (jobText !== lastJobTextSnapshot) {
      setJobTextTranslations({});
      setLastJobTextSnapshot(jobText);
      setJobTextViewLanguage("source");
    }
  }, [jobText, lastJobTextSnapshot]);

  const updateCompetencesScrollState = useCallback(() => {
    const el = competencesScrollRef.current;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    setCanScrollCompetencesUp(scrollTop > 0);
    setCanScrollCompetencesDown(scrollTop < scrollHeight - clientHeight - 2);
  }, []);

  useEffect(() => {
    const tick = () => updateCompetencesScrollState();
    const raf = requestAnimationFrame(tick);
    const el = competencesScrollRef.current;
    if (!el) return () => cancelAnimationFrame(raf);
    el.addEventListener("scroll", tick);
    const ro = new ResizeObserver(tick);
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("scroll", tick);
      ro.disconnect();
    };
  }, [updateCompetencesScrollState, requirements.length, showJobIntake]);

  // Get displayed job text (translated or original)
  const displayedJobText = useMemo(() => {
    if (jobTextViewLanguage !== "source" && jobTextTranslations[jobTextViewLanguage]) {
      return jobTextTranslations[jobTextViewLanguage];
    }
    return jobText;
  }, [jobTextViewLanguage, jobTextTranslations, jobText]);

  // Compute effective top_docs from user's manual selection (selectedDocIds)
  // Falls back to LLM-selected selectedTopDocs if no manual selection
  const effectiveTopDocs = useMemo(() => {
    if (selectedDocIds.size > 0 && allSearchResults.length > 0) {
      // Build docs from user selection, preserving LLM scores where available
      const llmScoreMap = {};
      (selectedTopDocs || []).forEach(d => {
        const id = d.id || d.company_name;
        if (id) llmScoreMap[id] = d.score;
      });
      return allSearchResults
        .filter(d => selectedDocIds.has(d.id || d.company_name))
        .map(d => {
          const id = d.id || d.company_name;
          const score = llmScoreMap[id];
          // Ensure every doc has a score (required by generate_letter)
          // User-added docs without LLM score get a default of 5
          return { ...d, score: score !== undefined ? score : 5 };
        });
    }
    return selectedTopDocs;
  }, [selectedDocIds, allSearchResults, selectedTopDocs]);

  /** Only job intake (similar offers) sends top_docs — via POST /api/phases/session/. */
  const jobIntakeTopDocsForSession = useMemo(() => {
    if (!allSearchResults.length) return {};
    return { top_docs: effectiveTopDocs || [] };
  }, [allSearchResults, effectiveTopDocs]);

  const autocompleteContextProps = useMemo(
    () => ({
      jobText,
      additionalUserInfo,
      additionalCompanyInfo,
      structureInstructions,
      companyReport: selectedCompanyReport || "",
      topDocs: effectiveTopDocs || [],
      companyName,
      jobTitle,
      location,
      language,
      salary,
      requirements: (Array.isArray(requirements) ? requirements : requirements ? [requirements] : []).filter(Boolean),
      competences,
      competenceScaleConfig,
      competenceOverrides,
      languages: enabledLanguages,
      pointOfContact: hasPointOfContactData ? pointOfContact : null,
    }),
    [
      jobText,
      additionalUserInfo,
      additionalCompanyInfo,
      structureInstructions,
      selectedCompanyReport,
      effectiveTopDocs,
      companyName,
      jobTitle,
      location,
      language,
      salary,
      requirements,
      competences,
      competenceScaleConfig,
      competenceOverrides,
      enabledLanguages,
      hasPointOfContactData,
      pointOfContact,
    ]
  );

  const buildJobSessionPayload = useCallback(
    (sessionId) => {
      const payload = {
        session_id: sessionId,
        job_text: jobText,
        company_name: companyName,
        job_title: jobTitle,
        location: location,
        language: language,
        salary: salary,
        requirements: (Array.isArray(requirements) ? requirements : requirements ? [requirements] : []).filter(Boolean),
        point_of_contact: hasPointOfContactData ? pointOfContact : null,
        additional_user_info: additionalUserInfo || "",
        additional_company_info: additionalCompanyInfo || "",
        structure_instructions: structureInstructions || "",
      };
      if (Object.keys(competences).length > 0) payload.competences = competences;
      Object.assign(payload, jobIntakeTopDocsForSession);
      return payload;
    },
    [
      jobText,
      companyName,
      jobTitle,
      location,
      language,
      salary,
      requirements,
      hasPointOfContactData,
      pointOfContact,
      additionalUserInfo,
      additionalCompanyInfo,
      structureInstructions,
      competences,
      jobIntakeTopDocsForSession,
    ]
  );

  const ensurePhaseSessionReady = useCallback(async () => {
    const sessionId =
      phaseSessionId ||
      (typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2));
    if (!phaseSessionId) {
      setPhaseSessionId(sessionId);
      await fetchWithHeartbeat("/api/phases/init/", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      });
    }
    await fetchWithHeartbeat("/api/phases/session/", {
      method: "POST",
      body: JSON.stringify(buildJobSessionPayload(sessionId)),
    });
    return sessionId;
  }, [phaseSessionId, buildJobSessionPayload]);

  const handleStartAutocomplete = async () => {
    if (!jobTitle.trim()) {
      setError("Job title is required");
      return;
    }
    if (!jobText?.trim()) {
      setError("Job description is required");
      return;
    }
    setError(null);
    try {
      await ensurePhaseSessionReady();
      navigate("/flows/autocomplete");
    } catch (e) {
      console.error("Failed to prepare autocomplete session:", e);
      setError("Failed to sync job details to session. Fix the issue or try again.");
    }
  };

  useEffect(() => {
    if (flow === "vendor" && vendorStage === "input") {
      navigate("/", { replace: true });
    } else if (flow === "agentic" && agenticStage === "input") {
      navigate("/", { replace: true });
    }
  }, [flow, vendorStage, agenticStage, navigate]);

  useEffect(() => {
    if (!phaseSessionId || !allSearchResults.length) return undefined;
    const t = setTimeout(() => {
      fetchWithHeartbeat("/api/phases/session/", {
        method: "POST",
        body: JSON.stringify({
          session_id: phaseSessionId,
          top_docs: effectiveTopDocs || [],
        }),
      }).catch((e) => console.warn("Failed to persist top_docs to session:", e));
    }, 400);
    return () => clearTimeout(t);
  }, [phaseSessionId, allSearchResults.length, effectiveTopDocs]);

  // Handle job text language change
  const handleJobTextLanguageChange = async (code) => {
    if (code === "source") {
      setJobTextViewLanguage("source");
      return;
    }

    setJobTextViewLanguage(code);
    
    // Check if already cached
    if (jobTextTranslations[code] && lastJobTextSnapshot === jobText) {
      return;
    }

    if (!jobText || !jobText.trim() || isTranslatingJobText) {
      return;
    }

    setIsTranslatingJobText(true);
    setJobTextTranslationError(null);

    try {
      const translated = await translateText(jobText, code, null);
      setJobTextTranslations((prev) => ({ ...prev, [code]: translated }));
      setLastJobTextSnapshot(jobText);
    } catch (e) {
      setJobTextTranslationError(e.message || "Translation failed");
    } finally {
      setIsTranslatingJobText(false);
    }
  };

  const phaseErrorKey = (phase, vendor) => `${phase}:${vendor}`;

  const setPhaseVendorError = (phase, vendor, message) => {
    setPhaseErrors((prev) => ({ ...prev, [phaseErrorKey(phase, vendor)]: message }));
    setPhaseRegistryTrigger((prev) => prev + 1);
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

  const clearPhaseRegistryForNewRun = () => {
    const phases = phaseRegistryRef.current;
    if (!phases) return;
    for (const phase of phases) {
      phase.approvedVendors?.clear?.();
      if (phase.cardData) {
        for (const v of Object.keys(phase.cardData)) {
          delete phase.cardData[v];
        }
      }
      if (phase.phase === "plan" && phase.planApproveRunners) {
        phase.planApproveRunners.clear();
      }
    }
    setPhaseRegistryTrigger((prev) => prev + 1);
  };

  // Helper to populate the "shelf" in PhaseFlow for a specific phase/vendor
  const populatePhaseShelf = useCallback((phaseName, vendor, data) => {
    if (phaseRegistryRef.current) {
      const phase = phaseRegistryRef.current.find((p) => p.phase === phaseName);
      if (phase) {
        phase.cardData[vendor] = data;
        if (phaseName === "plan" && phase.approvedVendors) {
          phase.approvedVendors.delete(vendor);
        }
        if (phase.cardErrors && Object.prototype.hasOwnProperty.call(phase.cardErrors, vendor)) {
          delete phase.cardErrors[vendor];
        }
        clearPhaseVendorError(phaseName, vendor);
        setPhaseRegistryTrigger((prev) => prev + 1);
      }
    }
  }, []);

  /** Surface background fetch failures on the phase card (never leave the card stuck on "Loading…"). */
  const setPhaseCardFetchError = useCallback((phaseName, vendor, message) => {
    if (!phaseRegistryRef.current) return;
    const phase = phaseRegistryRef.current.find((p) => p.phase === phaseName);
    if (!phase) return;
    if (!phase.cardErrors) phase.cardErrors = {};
    if (message) {
      phase.cardErrors[vendor] = message;
    } else {
      delete phase.cardErrors[vendor];
    }
    setPhaseRegistryTrigger((prev) => prev + 1);
  }, []);

  // Initialize CSRF token and session when component mounts
  useEffect(() => {
    // Initialize CSRF token first
    initializeCsrfToken().catch((e) => {
      console.warn("Failed to initialize CSRF token:", e);
    });

    const onCostTrackingError = (event) => {
      const message = event?.detail?.message;
      if (message) setCostTrackingError(message);
    };
    window.addEventListener(COST_TRACKING_ERROR_EVENT, onCostTrackingError);
    return () => window.removeEventListener(COST_TRACKING_ERROR_EVENT, onCostTrackingError);
  }, []);

  useEffect(() => {
    const sessionId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);
    setPhaseSessionId(sessionId);
    
    // Initialize session on backend (with CSRF token)
    fetchWithHeartbeat("/api/phases/init/", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }).catch((e) => {
      console.error("Failed to initialize session:", e);
      // Continue anyway - session will be created when needed
    });
  }, []);

  // Load minimum column width from settings (vendors endpoint handles active/inactive)
  useEffect(() => {
    if (!isAuthenticated) return;
    fetch("/api/personal-data/", {
      credentials: 'include',
    })
      .then((res) => res.json())
      .then((settings) => {
        // Load minimum column width
        if (settings.min_column_width !== undefined && settings.min_column_width !== null) {
          localStorage.setItem("minColumnWidth", settings.min_column_width.toString());
        }
        // Load default background models
        if (settings.default_background_models && Array.isArray(settings.default_background_models) && settings.default_background_models.length > 0) {
          setBackgroundModels(new Set(settings.default_background_models));
        }
        if (typeof settings.structure_instructions === "string") {
          setStructureInstructions(settings.structure_instructions);
        }
      })
      .catch((e) => {
        console.warn("Failed to load settings:", e);
      });
  }, [isAuthenticated, authRefreshGeneration]);

  // Fetch vendors on mount (GET request, no CSRF header needed)
  useEffect(() => {
    if (!isAuthenticated) return;
    fetch("/api/vendors/", {
      credentials: 'include', // Include cookies for session
    })
      .then((res) => res.json())
      .then((data) => {
        // API returns active and inactive lists
        const allVendors = [...(data.active || []), ...(data.inactive || [])];
        const activeVendors = new Set(data.active || []);
        
        setVendors(allVendors);
        setVendorColors(generateColors(allVendors));
        setSelectedVendors(activeVendors);
        if (typeof data.local_pricing_configured === "boolean") {
          setLocalPricingConfigured(data.local_pricing_configured);
        }
      })
      .catch((e) => setError(String(e)));
  }, [isAuthenticated, authRefreshGeneration]);

  // Rehydrate only on actual browser reload/back-forward, never on in-app route changes.
  // Also only rehydrate while the local form is still pristine to avoid overwriting new input.
  useEffect(() => {
    if (rehydrationAttemptedRef.current) return;
    if (checkingAuth || !isAuthenticated) return;

    const navEntry = performance.getEntriesByType("navigation")?.[0];
    const navType = navEntry?.type || "navigate";
    const isReloadLikeNav = navType === "reload" || navType === "back_forward";
    if (!isReloadLikeNav) {
      rehydrationAttemptedRef.current = true;
      return;
    }

    if (!isFormSnapshotPristine(latestFormSnapshotRef.current)) {
      rehydrationAttemptedRef.current = true;
      return;
    }

    rehydrationAttemptedRef.current = true;
    let cancelled = false;

    const safeString = (value) => (value == null ? "" : String(value));
    const normalizeRequirements = (value) => {
      if (Array.isArray(value)) return value.filter(Boolean);
      if (typeof value === "string" && value.trim()) return [value.trim()];
      return [];
    };

    (async () => {
      try {
        const [sessionRes, agenticRes] = await Promise.all([
          fetch("/api/phases/state/", { credentials: "include" }),
          flow === "agentic"
            ? fetch("/api/phases/agentic/state/", { credentials: "include" })
            : Promise.resolve(null),
        ]);
        if (cancelled) return;
        if (!sessionRes.ok) return;

        const sessionPayload = await sessionRes.json();
        if (cancelled) return;

        if (!isFormSnapshotPristine(latestFormSnapshotRef.current)) {
          return;
        }

        const sessionId = sessionPayload?.session_id;
        const state = sessionPayload?.session_state || {};
        const common = state?.metadata?.common || {};
        let restoredSomething = false;

        if (sessionId) {
          setPhaseSessionId(sessionId);
          restoredSomething = true;
        }
        if (state?.job_text != null) {
          setJobText(safeString(state.job_text));
          restoredSomething = true;
        }
        if (common.company_name != null) {
          setCompanyName(safeString(common.company_name));
          restoredSomething = true;
        }
        if (common.job_title != null) {
          setJobTitle(safeString(common.job_title));
          restoredSomething = true;
        }
        if (common.location != null) {
          setLocation(safeString(common.location));
          restoredSomething = true;
        }
        if (common.language != null) {
          setLanguage(safeString(common.language));
          restoredSomething = true;
        }
        if (common.salary != null) {
          setSalary(safeString(common.salary));
          restoredSomething = true;
        }
        if (common.additional_user_info != null) {
          setAdditionalUserInfo(safeString(common.additional_user_info));
          restoredSomething = true;
        }
        if (common.additional_company_info != null) {
          setAdditionalCompanyInfo(safeString(common.additional_company_info));
          restoredSomething = true;
        }
        if (common.hire_problem != null) {
          setHireProblem(safeString(common.hire_problem));
          restoredSomething = true;
        }
        if (common.requirements != null) {
          setRequirements(normalizeRequirements(common.requirements));
          restoredSomething = true;
        }
        if (common.competences && typeof common.competences === "object") {
          setCompetences(common.competences);
          restoredSomething = true;
        }
        if (common.point_of_contact && typeof common.point_of_contact === "object") {
          setPointOfContact({
            name: safeString(common.point_of_contact.name),
            role: safeString(common.point_of_contact.role),
            contact_details: safeString(common.point_of_contact.contact_details),
            notes: safeString(common.point_of_contact.notes),
            company: safeString(common.point_of_contact.company),
          });
          restoredSomething = true;
        }

        if (flow === "agentic" && agenticRes && agenticRes.ok) {
          const agenticPayload = await agenticRes.json();
          if (cancelled) return;
          const rawRestoredAgentic = agenticPayload?.agentic_state || null;
          const restoredAgentic = (() => {
            if (!rawRestoredAgentic || typeof rawRestoredAgentic !== "object") return rawRestoredAgentic;
            const normalized = normalizeAgenticThreads(
              rawRestoredAgentic.threads || {},
              rawRestoredAgentic.topic_meta || {}
            );
            return {
              ...rawRestoredAgentic,
              threads: normalized.threads,
              topic_meta: normalized.topicMeta,
            };
          })();
          if (restoredAgentic && restoredAgentic.status) {
            setAgenticState(restoredAgentic);
            if (restoredAgentic.max_rounds != null) syncAgenticMaxRoundsFromServer(restoredAgentic.max_rounds);
            if (restoredAgentic.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(restoredAgentic.sub_comment_rounds);
            if (restoredAgentic.status === "done") setAgenticStage("assembly");
            else setAgenticStage("agentic");
            restoredSomething = true;
          }
        }

        if (restoredSomething) {
          showNotification("Recovered previous session after browser reload");
        }
      } catch (e) {
        console.warn("Reload rehydration skipped:", e);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    checkingAuth,
    isAuthenticated,
    flow,
    normalizeAgenticThreads,
    stripAgenticThreadFields,
    syncAgenticMaxRoundsFromServer,
    syncAgenticSubCommentRoundsFromServer,
    isFormSnapshotPristine,
  ]);

  // Notify only when agentic feedback actually completes (ongoing becomes false), not on start or every poll
  const agenticOngoingRef = useRef(undefined);
  useEffect(() => {
    const ongoing = agenticState?.ongoing;
    const status = agenticState?.status;
    const wasOngoing = agenticOngoingRef.current;
    agenticOngoingRef.current = ongoing;
    if (status === "feedback" && ongoing === false && wasOngoing !== false) {
      showNotification("Agentic feedback completed");
    }
  }, [agenticState?.status, agenticState?.ongoing]);

  // When agentic flow finishes (status done), show assembly stage
  useEffect(() => {
    if (flow === "agentic" && agenticState?.status === "done") {
      setAgenticStage("assembly");
    }
  }, [flow, agenticState?.status]);

  // When navigating to agentic route with startAgentic state (clicking "Start agentic flow" from vendor route),
  // the new route mount gets fresh state; restore agentic stage and clear the state from history.
  useEffect(() => {
    if (flow === "agentic" && navLocation.state?.startAgentic) {
      setAgenticStage("agentic");
      navigate(navLocation.pathname, { replace: true, state: {} });
    }
  }, [flow, navLocation.pathname, navLocation.state?.startAgentic, navigate]);

  // Clear agentic final assembly when not done; do not auto-fill (user builds Final Letter from vendor columns if they want)
  useEffect(() => {
    if (agenticState?.status !== "done") {
      setAgenticFinalParagraphs([]);
    }
  }, [agenticState?.status]);

  // Note: We no longer need to reload when switching tabs since SettingsPage
  // now updates the shared state directly when saving

  // Company research countdown: tick every second, auto-trigger at 0
  useEffect(() => {
    if (companyResearchCountdown === null || companyResearchCountdown <= 0) return;
    const timer = setTimeout(() => {
      setCompanyResearchCountdown((prev) => (prev !== null && prev > 0 ? prev - 1 : null));
    }, 1000);
    return () => clearTimeout(timer);
  }, [companyResearchCountdown]);

  useEffect(() => {
    if (companyResearchCountdown === 0 && !companyAutoResearchBlocked) {
      setCompanyResearchCountdown(null);
      setTriggerCompanyResearch(Date.now());
    }
  }, [companyResearchCountdown, companyAutoResearchBlocked]);

  const hasUnsavedGeneratedWork = useMemo(() => {
    if (documentId) return false;
    const hasVendorOutput = Object.values(letters || {}).some(
      (text) => typeof text === "string" && text.trim().length > 0
    );
    const draftLetters = agenticState?.draft_letters || {};
    const finalLetters = agenticState?.final_letters || {};
    const hasAgenticOutput =
      (typeof agenticState?.draft_letter === "string" && agenticState.draft_letter.trim().length > 0) ||
      (typeof agenticState?.final_letter === "string" && agenticState.final_letter.trim().length > 0) ||
      Object.values(draftLetters).some((text) => typeof text === "string" && text.trim().length > 0) ||
      Object.values(finalLetters).some((text) => typeof text === "string" && text.trim().length > 0);
    return hasVendorOutput || hasAgenticOutput;
  }, [documentId, letters, agenticState]);

  const hasUnsavedComposeInput = useMemo(
    () =>
      !isFormSnapshotPristine({
        jobText,
        companyName,
        jobTitle,
        location,
        language,
        salary,
        requirements,
        competences,
        pointOfContact,
        additionalUserInfo,
        additionalCompanyInfo,
        extractedData,
      }),
    [
      isFormSnapshotPristine,
      jobText,
      companyName,
      jobTitle,
      location,
      language,
      salary,
      requirements,
      competences,
      pointOfContact,
      additionalUserInfo,
      additionalCompanyInfo,
      extractedData,
    ]
  );

  const shouldWarnOnLeave = hasUnsavedGeneratedWork || hasUnsavedComposeInput;

  useEffect(() => {
    if (isAuthenticated !== true || !shouldWarnOnLeave) return undefined;
    const onBeforeUnload = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [isAuthenticated, shouldWarnOnLeave]);

  const guardBeforeEnablingLocal = useCallback(
    (fn) => {
      if (localPricingConfigured) {
        fn();
        return;
      }
      if (isLocalPricingWarningDismissed()) {
        fn();
        return;
      }
      pendingLocalEnableActionRef.current = fn;
      setLocalPricingModalOpen(true);
    },
    [localPricingConfigured]
  );

  const handleLocalPricingModalContinue = useCallback(() => {
    if (localPricingDismissChecked) {
      dismissLocalPricingWarningForSession();
    }
    const fn = pendingLocalEnableActionRef.current;
    pendingLocalEnableActionRef.current = null;
    setLocalPricingModalOpen(false);
    setLocalPricingDismissChecked(false);
    if (typeof fn === "function") fn();
  }, [localPricingDismissChecked]);

  const handleLocalPricingModalCancel = useCallback(() => {
    pendingLocalEnableActionRef.current = null;
    setLocalPricingModalOpen(false);
    setLocalPricingDismissChecked(false);
  }, []);

  const extractErrorMessage = useCallback((error) => {
    if (!error) return "Unknown error";

    const errorStr = typeof error === "string" ? error : (error.message || String(error));

    if (error instanceof TypeError && error.message.includes("fetch")) {
      return "Network error: Unable to connect to server. Please check your connection.";
    }

    const providerMessageMatch = errorStr.match(/(?:'message'|"message")\s*:\s*'((?:[^'\\]|\\.)*)'/);
    if (providerMessageMatch) {
      return providerMessageMatch[1].replace(/\\'/g, "'").trim() || errorStr;
    }
    const providerMessageDouble = errorStr.match(/(?:'message'|"message")\s*:\s*"((?:[^"\\]|\\.)*)"/);
    if (providerMessageDouble) {
      return providerMessageDouble[1].replace(/\\"/g, '"').trim() || errorStr;
    }

    try {
      if (errorStr.includes("API error occurred:")) {
        const bodyMatch = errorStr.match(/Body:\s*({[\s\S]*})/);
        if (bodyMatch) {
          const body = JSON.parse(bodyMatch[1]);
          return body.detail || body.message || errorStr;
        }
        const detailMatch = errorStr.match(/"detail"\s*:\s*"([^"]+)"/);
        if (detailMatch) {
          return detailMatch[1];
        }
      }

      const parsed = JSON.parse(errorStr);
      if (parsed.detail) return parsed.detail;
      if (parsed.message) return parsed.message;
      if (parsed.error?.message) return parsed.error.message;
    } catch (e) {
      /* not JSON */
    }

    return errorStr.replace(/^Error:\s*/, "").trim() || "Unknown error";
  }, []);

  const onClearPhaseFetchError = useCallback(
    (phaseName, vendor) => {
      setPhaseCardFetchError(phaseName, vendor, null);
    },
    [setPhaseCardFetchError]
  );

  const onRetryPhaseFetch = useCallback(
    async (phaseName, vendor) => {
      if (phaseName !== "plan") return;
      const sessionId = phaseSessions[vendor] || phaseSessionId;
      if (!sessionId) {
        setPhaseCardFetchError(
          "plan",
          vendor,
          "No session ID. Return to job intake and start the vendor flow again."
        );
        return;
      }
      setPhaseCardFetchError("plan", vendor, null);
      try {
        const body = { session_id: sessionId };
        if (selectedCompanyReport) {
          body.company_report = selectedCompanyReport;
        }
        const result = await fetchWithHeartbeat(
          `/api/phases/plan/${vendor}/`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          },
          { getState: getStateForRestore }
        );
        if (result.isHeartbeat) return;
        populatePhaseShelf("plan", vendor, result.data);
        setPhaseSessions((prev) => ({ ...prev, [vendor]: sessionId }));
        const docId = result.data?.document?.id;
        if (docId) {
          setDocumentId((prev) => prev || docId);
        }
      } catch (e) {
        console.error(`Retry plan fetch failed for ${vendor}:`, e);
        setPhaseCardFetchError("plan", vendor, extractErrorMessage(e));
      }
    },
    [
      phaseSessions,
      phaseSessionId,
      selectedCompanyReport,
      getStateForRestore,
      setPhaseCardFetchError,
      populatePhaseShelf,
      extractErrorMessage,
    ]
  );

  // NOW we can do conditional returns (after all hooks are declared)
  
  // While checking authentication or if not authenticated, show loading/login
  // Only render main app content if authenticated
  if (checkingAuth) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          minHeight: "100vh",
          backgroundColor: "var(--bg-color)",
          color: "var(--text-color)",
        }}
      >
        <div
          style={{
            padding: "12px 20px",
            display: "flex",
            alignItems: "baseline",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <h1 style={{ margin: 0, fontSize: "24px", fontWeight: 600, color: "var(--text-color)" }}>
            Letter Writer
          </h1>
          <AppVersionLabel />
        </div>
        <div
          style={{
            flex: 1,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
          }}
        >
          <div>Checking authentication...</div>
        </div>
      </div>
    );
  }
  
  if (!isAuthenticated) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          minHeight: "100vh",
          backgroundColor: "var(--bg-color)",
          color: "var(--text-color)",
          padding: "20px",
        }}
      >
        <div
          style={{
            maxWidth: "400px",
            width: "100%",
            padding: "40px",
            backgroundColor: "var(--panel-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: "8px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
            textAlign: "center",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "center",
              gap: 8,
              flexWrap: "wrap",
              marginBottom: "10px",
            }}
          >
            <h1 style={{ margin: 0, fontSize: "24px", fontWeight: 600 }}>
              Letter Writer
            </h1>
            <AppVersionLabel />
          </div>
          <p style={{ marginBottom: "30px", color: "var(--text-color)", opacity: 0.8 }}>
            Sign in to continue
          </p>
          <button
            onClick={() => {
              scheduleGoogleOAuthRedirect();
            }}
            style={{
              width: "100%",
              padding: "12px 24px",
              fontSize: "16px",
              fontWeight: 600,
              backgroundColor: "#4285f4",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              transition: "background-color 0.2s",
            }}
            onMouseOver={(e) => {
              e.target.style.backgroundColor = "#357ae8";
            }}
            onMouseOut={(e) => {
              e.target.style.backgroundColor = "#4285f4";
            }}
          >
            Sign in with Google
          </button>
        </div>
      </div>
    );
  }

  const toggleVendor = (vendor, checked) => {
    if (vendor === "local" && checked) {
      guardBeforeEnablingLocal(() => {
        setSelectedVendors((prev) => {
          const next = new Set(prev);
          next.add("local");
          return next;
        });
      });
      return;
    }
    setSelectedVendors((prev) => {
      const next = new Set(prev);
      checked ? next.add(vendor) : next.delete(vendor);
      return next;
    });
  };

  const selectAll = (checked) => {
    if (!checked) {
      setSelectedVendors(new Set());
      return;
    }
    if (vendors.includes("local") && !selectedVendors.has("local")) {
      guardBeforeEnablingLocal(() => {
        setSelectedVendors(new Set(vendors));
      });
      return;
    }
    setSelectedVendors(new Set(vendors));
  };

  const extractData = async () => {
    if (!jobText.trim()) {
      setExtractionError("Please enter job description first");
      return;
    }
    setExtracting(true);
    setExtractionError(null);
    
    // Generate session_id upfront
    const sessionId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);
    setPhaseSessionId(sessionId);
    
    // Reset countdown/notification state
    setCompanyResearchCountdown(null);
    setCompanyAutoResearchBlocked(false);
    setCompanyResearchNotification(null);
    setCompanyExtractionResult(null);

    // Fire company metadata extraction (Part 3) in parallel — stateless, any worker.
    const companyExtractPromise = jobText.trim()
      ? fetchWithHeartbeat("/api/research/company/extract/", {
          method: "POST",
          body: JSON.stringify({ job_text: jobText }),
        }).catch((err) => {
          console.warn("Company extraction failed:", err);
          return null;
        })
      : Promise.resolve(null);

    // Handle company extraction result whenever it arrives (may be before or after skills).
    companyExtractPromise.then((res) => {
      const ext = res?.data?.extraction;
      if (!ext) return;
      setCompanyExtractionResult(ext);
      // Only fill fields the user hasn't manually entered yet.
      if (ext.company_name) setCompanyName((prev) => (prev.trim() ? prev : ext.company_name));
      if (ext.job_title) setJobTitle((prev) => (prev.trim() ? prev : ext.job_title));
      if (ext.location) setLocation((prev) => (prev.trim() ? prev : ext.location));
      if (ext.language) setLanguage((prev) => (prev.trim() ? prev : ext.language));
      if (ext.salary) setSalary((prev) => (prev.trim() ? prev : ext.salary));
      if (ext.point_of_contact) {
        setPointOfContact((prev) => {
          const hasManual = prev.name || prev.role || prev.contact_details || prev.notes || prev.company;
          if (hasManual) return prev;
          return {
            name: ext.point_of_contact.name || "",
            role: ext.point_of_contact.role || "",
            contact_details: ext.point_of_contact.contact_details || "",
            notes: ext.point_of_contact.notes || "",
            company: ext.point_of_contact.company || "",
          };
        });
        setShowPointOfContact(true);
        setTriggerPocResearch(Date.now());
      }
      // Update extractedData with company metadata (merges with skills data when that arrives)
      setExtractedData((prev) => ({
        ...(prev || {}),
        company_name: ext.company_name || prev?.company_name || "",
        job_title: ext.job_title || prev?.job_title || "",
        location: ext.location || prev?.location || "",
        language: ext.language || prev?.language || "",
        salary: ext.salary || prev?.salary || "",
        point_of_contact: ext.point_of_contact || prev?.point_of_contact || null,
      }));
      // Start 15-second countdown before auto-launching background research
      setCompanyResearchCountdown(15);
    });

    try {
      const scaleConfig = getScaleConfig();
      const result = await fetchWithHeartbeat("/api/extract/", {
        method: "POST",
        body: JSON.stringify({
          job_text: jobText,
          scale_config: {
            need: scaleConfig.need,
            level: scaleConfig.level,
            needSemantics: scaleConfig.needSemantics || {},
          },
        }),
      });
      const data = result.data;
      const extracted = data.extraction || {};
      const comp = extracted.competences;
      const cfg = getScaleConfig();
      if (comp && typeof comp === "object" && Object.keys(comp).length > 0) {
        setCompetences(comp);
        setCompetenceOverrides({});
        const keys = Object.keys(comp).sort((a, b) => {
          const numA = getEffectiveRating(a, comp, cfg, {});
          const numB = getEffectiveRating(b, comp, cfg, {});
          const impA = getEffectiveImportance(a, comp, cfg, {});
          const impB = getEffectiveImportance(b, comp, cfg, {});
          if (numA.presence == null || impA == null) return 1;
          if (numB.presence == null || impB == null) return -1;
          const scoreA = impA * (numA.presence - 2.5);
          const scoreB = impB * (numB.presence - 2.5);
          const absA = Math.abs(scoreA);
          const absB = Math.abs(scoreB);
          if (Math.abs(absB - absA) < 0.01) return scoreB - scoreA;
          return absB - absA;
        });
        setRequirements(keys);
      } else if (extracted.requirements) {
        const reqs = Array.isArray(extracted.requirements)
          ? extracted.requirements
          : [extracted.requirements];
        setRequirements(reqs.filter(Boolean));
        setCompetences({});
        setCompetenceOverrides({});
      }
      // Store extracted data (skills portion; company metadata merged by companyExtractPromise)
      setExtractedData((prev) => ({
        ...(prev || {}),
        requirements: extracted.requirements || requirements,
        competences: extracted.competences ?? {},
        hire_problem: extracted.hire_problem ?? prev?.hire_problem ?? "",
        job_text: jobText,
        additional_user_info: additionalUserInfo,
        additional_company_info: additionalCompanyInfo,
      }));
      if (extracted.hire_problem != null && String(extracted.hire_problem).trim()) {
        setHireProblem(String(extracted.hire_problem).trim());
      }

      // Similar docs and top docs come from the single extract call.
      const similarDocs = data.similar_documents || [];
      const topDocs = data.top_docs || [];
      if (similarDocs.length > 0) {
        setAllSearchResults(similarDocs);
      }
      if (topDocs.length > 0) {
        setSelectedTopDocs(topDocs);
        const llmIds = new Set(topDocs.map((d) => d.id || d.company_name).filter(Boolean));
        setSelectedDocIds(llmIds);
      }

    } catch (e) {
      console.error("Extract error", e);
      setExtractionError(e?.message || String(e));
      setCompetences({});
      setCompetenceOverrides({});
      setHireProblem("");
    } finally {
      setExtracting(false);
    }
  };

  const persistFinalLetter = async (finalText) => {
    if (!finalText) {
      const err = new Error("No letter text to save");
      setError(err.message);
      throw err;
    }
    if (!companyName) console.warn("persistFinalLetter: saving without company name");
    if (!jobText) console.warn("persistFinalLetter: saving without job text");
    const requirementsList = Array.isArray(requirements) ? requirements : requirements ? [requirements] : [];
    
    // Collect user corrections (compact diff format) grouped by vendor
    const correctionsByVendor = {};
    finalParagraphs.forEach((p) => {
      // Only track corrections for paragraphs that have a vendor (AI-generated)
      // and have been edited (text differs from originalText)
      if (p.vendor && p.originalText !== undefined && p.text !== p.originalText) {
        if (!correctionsByVendor[p.vendor]) {
          correctionsByVendor[p.vendor] = [];
        }
        // Create compact diff (returns array of changes, empty if no changes)
        const diffs = createTextDiff(p.originalText || "", p.text || "");
        // Flatten array of changes into the vendor's corrections array
        if (Array.isArray(diffs) && diffs.length > 0) {
          correctionsByVendor[p.vendor].push(...diffs);
        }
      }
    });
    
    const aiLetters = Object.entries(letters).map(([vendor, text]) => {
      const feedback = vendorFeedback[vendor] || {};
      // Calculate chunks used from this vendor in the final letter
      const chunksUsed = finalParagraphs.filter(p => p.vendor === vendor).length;
      return {
        vendor,
        text: text || "",
        cost: vendorCosts[vendor] ?? null,
        rating: feedback.rating || null,
        comment: feedback.comment || "",
        chunks_used: chunksUsed,
        user_corrections: correctionsByVendor[vendor] || [], // Include user corrections
      };
    });

    let feedbackExtraInfo = null;
    let feedbackAgentContext = null;
    if (flow === "vendor") {
      const draftPhase = phaseRegistryRef.current?.find((p) => p.phase === "draft");
      const reg = draftFeedbackRegistryRef.current || {};
      let acc = [];
      let agentAcc = [];
      for (const v of Array.from(selectedVendors)) {
        let merged = false;
        if (typeof reg[v] === "function") {
          const snap = reg[v]();
          if (snap?.feedbackKeys?.length) {
            acc = mergeExtraInfoFromFeedback(
              acc,
              snap.feedback,
              snap.feedback_overrides || {},
              snap.feedbackKeys,
            );
            agentAcc = mergeAgentContextFromFeedback(
              agentAcc,
              snap.feedback,
              snap.feedback_overrides || {},
              snap.feedbackKeys,
            );
            merged = true;
          }
        }
        if (!merged) {
          const shelfData = draftPhase?.cardData?.[v];
          const fromShelf = shelfData
            ? phaseModules.draft.initializeFeedbackFromData(shelfData)
            : null;
          if (fromShelf?.feedbackKeys?.length) {
            acc = mergeExtraInfoFromFeedback(acc, fromShelf.feedback, {}, fromShelf.feedbackKeys);
            agentAcc = mergeAgentContextFromFeedback(agentAcc, fromShelf.feedback, {}, fromShelf.feedbackKeys);
          }
        }
      }
      if (acc.length > 0) {
        feedbackExtraInfo = acc;
      } else {
        feedbackExtraInfo = [];
      }
      if (agentAcc.length > 0) {
        feedbackAgentContext = agentAcc;
      } else {
        feedbackAgentContext = [];
      }
    }

    const payload = {
      company_name: companyName,
      role: jobTitle || "",
      location: location || "",
      language: language || "",
      salary: salary || "",
      requirements: requirementsList,
      job_text: jobText,
      letter_text: finalText,
      ai_letters: aiLetters,
      ...(feedbackExtraInfo !== null ? { feedback_extra_info: feedbackExtraInfo } : {}),
      ...(feedbackAgentContext !== null ? { feedback_agent_context: feedbackAgentContext } : {}),
    };
    const url = documentId ? `/api/documents/${documentId}/` : "/api/documents/";
    const method = documentId ? "PUT" : "POST";
    try {
      setSavingFinal(true);
      setDocumentSaveNotice(null);
      const result = await fetchWithHeartbeat(url, {
        method,
        body: JSON.stringify(payload),
      });
      const data = result.data;
      if (Array.isArray(data.warnings) && data.warnings.length > 0) {
        setDocumentSaveNotice(data.warnings.join(" "));
      }
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }
    } catch (e) {
      const errorMsg = `Failed to save letter: ${e.message || e}`;
      setError(errorMsg);
      throw new Error(errorMsg);
    } finally {
      setSavingFinal(false);
    }
  };

  const persistAgenticLetter = async (letterText) => {
    if (!letterText?.trim()) {
      const err = new Error("No letter text to save");
      setAgenticSaveError(err.message);
      throw err;
    }
    if (!jobText?.trim()) {
      setAgenticSaveError("Job description is required to save");
      throw new Error("Job description is required to save");
    }
    // Build ai_letters like vendor flow so analytics/replay fields stay consistent.
    const finalLetters = agenticState?.final_letters || {};
    const paragraphs = Array.isArray(agenticFinalParagraphs) ? agenticFinalParagraphs : [];
    const vendorsFromParagraphs = paragraphs
      .map((p) => p?.vendor)
      .filter((v) => typeof v === "string" && v.trim().length > 0);
    const vendorKeys = Array.from(
      new Set([...Object.keys(finalLetters).filter(Boolean), ...vendorsFromParagraphs])
    );
    const totalCost = agenticState?.cost ?? null;
    const costPerVendor = vendorKeys.length ? (totalCost != null ? totalCost / vendorKeys.length : null) : totalCost;
    const correctionsByVendor = {};
    paragraphs.forEach((p) => {
      if (!p?.vendor) return;
      if (p.originalText === undefined || p.text === p.originalText) return;
      if (!correctionsByVendor[p.vendor]) correctionsByVendor[p.vendor] = [];
      const diffs = createTextDiff(p.originalText || "", p.text || "");
      if (Array.isArray(diffs) && diffs.length > 0) {
        correctionsByVendor[p.vendor].push(...diffs);
      }
    });
    const aiLetters = vendorKeys.length > 0
      ? vendorKeys.map((vendor) => ({
          vendor,
          text: (
            finalLetters[vendor] ||
            paragraphs
              .filter((p) => p?.vendor === vendor)
              .map((p) => p?.text || "")
              .join("\n\n")
          ).trim(),
          cost: costPerVendor,
          rating: vendorFeedback[vendor]?.rating || null,
          comment: vendorFeedback[vendor]?.comment || "",
          chunks_used: paragraphs.filter((p) => p?.vendor === vendor).length,
          user_corrections: correctionsByVendor[vendor] || [],
        }))
      : [
          {
            vendor: agenticState?.draft_vendor || "agentic",
            text: letterText.trim(),
            cost: totalCost,
            rating: vendorFeedback[agenticState?.draft_vendor || "agentic"]?.rating || null,
            comment: "",
            chunks_used: 0,
            user_corrections: [],
          },
        ];
    const payload = {
      company_name: companyName || "",
      role: jobTitle || "",
      location: location || "",
      language: language || "",
      salary: salary || "",
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
      job_text: jobText,
      letter_text: letterText.trim(),
      ai_letters: aiLetters,
    };
    const url = documentId ? `/api/documents/${documentId}/` : "/api/documents/";
    const method = documentId ? "PUT" : "POST";
    try {
      setAgenticSaveError(null);
      setAgenticSavingFinal(true);
      setDocumentSaveNotice(null);
      const result = await fetchWithHeartbeat(url, {
        method,
        body: JSON.stringify(payload),
      });
      const data = result.data;
      if (Array.isArray(data.warnings) && data.warnings.length > 0) {
        setDocumentSaveNotice(data.warnings.join(" "));
      }
      if (!documentId && data?.document?.id) {
        setDocumentId(data.document.id);
      }
    } catch (e) {
      const msg = e.message || "Failed to save letter";
      setAgenticSaveError(msg);
      throw new Error(msg);
    } finally {
      setAgenticSavingFinal(false);
    }
  };

  const persistAutocompleteLetter = async ({
    letterText,
    sections,
    proposalLetterText,
    autocompleteHistory,
    completionModel: completionModelUsed,
    planModel: planModelUsed,
    planCost,
    cycleModels: cycleModelsUsed,
    totalCost,
  }) => {
    const trimmed = (letterText || "").trim();
    if (!trimmed) {
      const err = new Error("No letter text to save");
      setError(err.message);
      throw err;
    }
    if (!jobText?.trim()) {
      const msg = "Job description is required to save";
      setError(msg);
      throw new Error(msg);
    }

    const sectionsPayload = (sections || []).map(
      ({ id, title, description, body, plan, proposal }) => ({
        id,
        title: title ?? "",
        description: description ?? "",
        body: body ?? "",
        plan: plan ?? "",
        proposal: proposal ?? "",
      })
    );

    const proposalText = (
      proposalLetterText ||
      sectionsToProposalText(sections) ||
      ""
    ).trim();
    const planAiLetter = buildAutocompletePlanAiLetter(
      planModelUsed,
      proposalText,
      planCost
    );

    const history = autocompleteHistory || { fixed_context: "", chunks: [] };
    const payload = {
      company_name: companyName || "",
      role: jobTitle || "",
      location: location || "",
      language: language || "",
      salary: salary || "",
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
      job_text: jobText,
      letter_text: trimmed,
      autocomplete_sections: sectionsPayload,
      autocomplete_history: {
        fixed_context: history.fixed_context || "",
        chunks: Array.isArray(history.chunks) ? history.chunks : [],
        completion_model: completionModelUsed || "",
        plan_model: planModelUsed || "",
        cycle_models: cycleModelsUsed || [],
        total_cost: typeof totalCost === "number" ? totalCost : 0,
      },
    };
    if (planAiLetter) {
      payload.ai_letters = [planAiLetter];
    }

    const url = documentId ? `/api/documents/${documentId}/` : "/api/documents/";
    const method = documentId ? "PUT" : "POST";
    try {
      setSavingFinal(true);
      const result = await fetchWithHeartbeat(url, {
        method,
        body: JSON.stringify(payload),
      });
      const data = result.data;
      if (!documentId && data?.document?.id) {
        setDocumentId(data.document.id);
      }
      try {
        await fetchWithHeartbeat("/api/phases/clear/", { method: "POST" });
        setPhaseSessionId(null);
        setPhaseSessions({});
      } catch (clearErr) {
        console.warn("Letter saved but failed to clear server session:", clearErr);
      }
    } catch (e) {
      const errorMsg = `Failed to save letter: ${e.message || e}`;
      setError(errorMsg);
      throw new Error(errorMsg);
    } finally {
      setSavingFinal(false);
    }
  };

  // Generic retry function - takes URL, body, and result handler
  // No phase knowledge - caller provides everything
  // Returns the result data or throws on error
  const retryVendor = async (url, body, onResult) => {
    await retryApiCall(url, body, onResult);
  };
  
  // Helper to create a retry function for a specific phase/vendor
  // This is phase-aware, but retryVendor itself is not
  const createRetryForPhase = (phaseName, vendor) => {
    const phaseModule = phaseModules[phaseName];
    if (!phaseModule || !phaseModule.getApiConfig) {
      throw new Error(`Phase module "${phaseName}" not found`);
    }
    
    const apiConfig = phaseModule.getApiConfig(vendor, phaseSessionId, null);
    if (!apiConfig) {
      throw new Error(`API config not available for phase "${phaseName}"`);
    }
    
    // Create result handler using phase module
    const onResult = (data) => {
      // Populate the shelf in PhaseFlow
      populatePhaseShelf(phaseName, vendor, data);

      if (phaseModule.handleRetryResult) {
        phaseModule.handleRetryResult(data, {
          vendor,
          sessionId: phaseSessionId,
          setDocumentId: (id) => {
            if (!documentId) setDocumentId(id);
          },
          setPhaseSessions,
          setUiStage: setVendorStage,
          setShowInput: () => setVendorStage("input"),
          setLetters,
          setVendorParagraphs,
          setVendorCosts,
          splitIntoParagraphs,
        });
      }
    };
    
    return () => retryVendor(apiConfig.url, apiConfig.body, onResult);
  };

  const updatePhaseEdit = (vendor, phase, field, value) => {
    // Cards now own their edits, so this is just a no-op callback
    // Cards will handle their own edit state
  };

  const approveExtraction = async (vendor) => {
    if (!phaseSessionId || !vendor) return;
    
    // Check if extraction was edited (different from extracted data)
    const currentExtraction = {
      company_name: companyName,
      job_title: jobTitle,
      location: location,
      language: language,
      salary: salary,
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
      point_of_contact: (pointOfContact.name || pointOfContact.role || pointOfContact.contact_details || pointOfContact.notes || pointOfContact.company) ? pointOfContact : null,
    };
    const extractionEdited = extractedData && (
      extractedData.company_name !== currentExtraction.company_name ||
      extractedData.job_title !== currentExtraction.job_title ||
      extractedData.location !== currentExtraction.location ||
      extractedData.language !== currentExtraction.language ||
      extractedData.salary !== currentExtraction.salary ||
      JSON.stringify(extractedData.requirements) !== JSON.stringify(currentExtraction.requirements) ||
      JSON.stringify(extractedData.point_of_contact || null) !== JSON.stringify(currentExtraction.point_of_contact)
    );

    setError(null);

    try {
      // If extraction was edited, save it to session first
      if (extractionEdited) {
        await fetchWithHeartbeat("/api/phases/session/", {
          method: "POST",
          body: JSON.stringify({
            session_id: phaseSessionId,
            job_text: jobText,
            company_name: companyName,
            job_title: jobTitle,
            location: location,
            language: language,
            salary: salary,
            requirements: currentExtraction.requirements.filter(Boolean),
            competences: Object.keys(competences).length > 0 ? competences : undefined,
            point_of_contact: currentExtraction.point_of_contact,
            structure_instructions: structureInstructions || "",
            ...jobIntakeTopDocsForSession,
          }),
        });
      } else {
        await fetchWithHeartbeat("/api/phases/session/", {
          method: "POST",
          body: JSON.stringify({
            session_id: phaseSessionId,
            structure_instructions: structureInstructions || "",
            ...jobIntakeTopDocsForSession,
          }),
        });
      }
      
      // Plan phase - include selected research results if available
      const planBody = {
        session_id: phaseSessionId,
      };
      if (selectedCompanyReport) {
        planBody.company_report = selectedCompanyReport;
      }
      const result = await fetchWithHeartbeat(
        `/api/phases/plan/${vendor}/`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(planBody),
        },
        { getState: getStateForRestore }
      );
      
      // Handle 202 Accepted (heartbeat/still processing)
      if (result.isHeartbeat) {
        // Don't throw error - request is still in progress
        // Frontend should continue waiting for the original request to complete
        return;
      }
      
      const data = result.data;

      // Populate the plan phase shelf in PhaseFlow
      populatePhaseShelf("plan", vendor, data);

      setPhaseSessions((prev) => ({ ...prev, [vendor]: phaseSessionId }));
      // phaseState, phaseEdits removed - cards own their state
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }
    } catch (e) {
      console.error("Plan phase error after extraction approval:", e);
      setPhaseCardFetchError("plan", vendor, extractErrorMessage(e));
    }
  };

  const handleSubmit = async () => {
    if (!jobTitle.trim()) {
      setError("Job title is required");
      return;
    }
    
    setLoading(true);
    setError(null);
    setPhaseErrors({});
    setLetters({});
    setVendorCosts({});
    setFailedVendors({});
    setVendorParagraphs({});
    setFinalParagraphs([]);
    setDocumentId(null);
    navigate("/flows/vendors");
    setVendorStage("phases");
    // phaseState, phaseEdits, phaseErrors removed - cards own their state
    setPhaseSessions({});
    clearPhaseRegistryForNewRun();
    setPhaseFlowResetKey((k) => k + 1);
    
    const vendorList = Array.from(selectedVendors);
    const initialSessionId = phaseSessionId || (
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2)
    );
    if (!phaseSessionId) {
      setPhaseSessionId(initialSessionId);
      // Initialize session if not already done
      try {
        await fetchWithHeartbeat("/api/phases/init/", {
          method: "POST",
          body: JSON.stringify({ session_id: initialSessionId }),
        });
      } catch (e) {
        console.error("Failed to initialize session:", e);
      }
    }

    // Always populate session with current state before starting drafts.
    try {
      await fetchWithHeartbeat("/api/phases/session/", {
        method: "POST",
        body: JSON.stringify(buildJobSessionPayload(initialSessionId)),
      });
    } catch (e) {
      console.error("Failed to update session data:", e);
      setError("Failed to update session data. Please try again.");
      setLoading(false);
      return;
    }

    // Save competence ratings to profile (after user modifications) for future extractions and CV appendix
    const ratingsToSave = buildCompetenceRatingsForProfile(
      competences,
      requirements,
      competenceOverrides,
      competenceScaleConfig
    );
    if (Object.keys(ratingsToSave).length > 0) {
      fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({ competence_ratings: ratingsToSave }),
      }).catch((e) => console.warn("Failed to save competence ratings to profile:", e));
    }

    // Start plan phase for all vendors in parallel (draft runs after plan is approved)
    vendorList.forEach((vendor) => {
      (async () => {
        try {
          const body = {
            session_id: initialSessionId,
          };
          // Pass overrides if available (from consolidated research)
          if (selectedCompanyReport) {
            body.company_report = selectedCompanyReport;
          }

          const result = await fetchWithHeartbeat(
            `/api/phases/plan/${vendor}/`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            },
            { getState: getStateForRestore }
          );
          
          // Handle 202 Accepted (heartbeat/still processing)
          if (result.isHeartbeat) {
            // Don't throw error - request is still in progress
            return;
          }
          
          const data = result.data;
          
          // Populate the plan phase shelf in PhaseFlow
          populatePhaseShelf("plan", vendor, data);

          // Update session for this vendor
          setPhaseSessions((prev) => ({ ...prev, [vendor]: initialSessionId }));
          
          // Set session ID from first successful response
          setPhaseSessionId((prev) => prev || initialSessionId);
        } catch (e) {
          console.error(`Plan phase error for ${vendor}:`, e);
          setPhaseCardFetchError("plan", vendor, extractErrorMessage(e));
        }
      })();
    });
    
    // Set initial session ID immediately (will be updated by first successful response)
    setPhaseSessionId(initialSessionId);
    setLoading(false);
  };

  const handleSubmitAgentic = async () => {
    if (!jobTitle.trim()) {
      setError("Job title is required");
      return;
    }
    setAgenticLoading(true);
    setAgenticError(null);
    setError(null);
    setAgenticState(null);
    bestKnownThreadsRef.current = null;
    navigate("/flows/agentic", { state: { startAgentic: true } });
    setAgenticStage("agentic");
    const initialSessionId = phaseSessionId || (
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2)
    );
    if (!phaseSessionId) {
      setPhaseSessionId(initialSessionId);
      try {
        await fetchWithHeartbeat("/api/phases/init/", {
          method: "POST",
          body: JSON.stringify({ session_id: initialSessionId }),
        });
      } catch (e) {
        console.error("Failed to initialize session:", e);
      }
    }
    // Always populate session with current state before starting agentic flow.
    try {
      await fetchWithHeartbeat("/api/phases/session/", {
        method: "POST",
        body: JSON.stringify(buildJobSessionPayload(initialSessionId)),
      });
    } catch (e) {
      console.error("Failed to update session:", e);
      setAgenticError("Failed to update session. Please try again.");
      setAgenticLoading(false);
      setAgenticStage("input");
      return;
    }
    // Save competence ratings to profile (same as phased flow) for future extractions and CV appendix
    const ratingsToSave = buildCompetenceRatingsForProfile(
      competences,
      requirements,
      competenceOverrides,
      competenceScaleConfig
    );
    if (Object.keys(ratingsToSave).length > 0) {
      fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({ competence_ratings: ratingsToSave }),
      }).catch((e) => console.warn("Failed to save competence ratings to profile:", e));
    }
    try {
      const body = {};
      if (selectedCompanyReport) body.company_report = selectedCompanyReport;
      // Honor vendor selection: one draft per selected vendor
      if (vendorsList.length > 0) body.draft_vendors = vendorsList;
      body.max_rounds = agenticMaxRounds;
      body.sub_comment_rounds = agenticSubCommentRounds;
      const res = await fetchWithHeartbeat("/api/phases/agentic/draft/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.isHeartbeat) {
        setAgenticLoading(false);
        return;
      }
      const nextAgentic = stripAgenticThreadFields(res.data?.agentic_state ?? null);
      setAgenticState(nextAgentic);
      if (nextAgentic?.max_rounds != null) syncAgenticMaxRoundsFromServer(nextAgentic.max_rounds);
      if (nextAgentic?.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(nextAgentic.sub_comment_rounds);
      setAgenticStage("agentic");
    } catch (e) {
      console.error("Agentic draft error", e);
      setAgenticError(extractErrorMessage(e));
      // Keep user on agentic flow so they see the error and can retry or change settings
    } finally {
      setAgenticLoading(false);
    }
  };

  const fetchAgenticPoll = async () => {
    try {
      const res = await fetch("/api/phases/agentic/feedback/poll/", { credentials: "include" });
      if (!res.ok) return false;
      const data = await res.json();
      publishUserMonthlyCost(data);
      const normalized = normalizeAgenticThreads(data.threads || {}, data.topic_meta || {});
      // Update best-known threads outside of React state so the ref is always current
      // regardless of React batching order. Any non-empty list per topic is saved.
      const best = bestKnownThreadsRef.current || {};
      let bestUpdated = false;
      for (const topic of AGENTIC_TOPICS) {
        const incoming = normalized.threads[topic] || [];
        if (incoming.length > (best[topic]?.length || 0)) {
          best[topic] = incoming;
          bestUpdated = true;
        }
      }
      if (bestUpdated) bestKnownThreadsRef.current = { ...best };

      setAgenticState((prev) => {
        // Threads are append-only: comments are marked removed, never deleted.
        // Merge per topic: keep the longest list seen (server response, previous React state,
        // or the best-known ref) so the UI never regresses to "No comments yet."
        const threads = {};
        for (const topic of AGENTIC_TOPICS) {
          const prevList = prev?.threads?.[topic] || [];
          const nextList = normalized.threads[topic] || [];
          const refList = bestKnownThreadsRef.current?.[topic] || [];
          const longest = [prevList, nextList, refList].reduce(
            (a, b) => (b.length > a.length ? b : a),
            [],
          );
          threads[topic] = longest;
        }
        return {
          ...(prev || {}),
          threads,
          status: data.status ?? prev?.status,
          ongoing: data.ongoing,
          feedback_suspended: data.feedback_suspended,
          topic_meta: normalized.topicMeta,
          ...(data.max_rounds != null && { max_rounds: data.max_rounds }),
          ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }),
        };
      });
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
      return data.ongoing === true;
    } catch (e) {
      console.warn("Failed to poll agentic feedback:", e);
      return false;
    }
  };

  const handleAgenticFeedbackStart = async () => {
    if (!vendorsList.length) return;
    setAgenticLoading(true);
    setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/feedback/start/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback_vendors: vendorsList }),
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, {
        status: data.status ?? "feedback",
        ongoing: data.ongoing,
        feedback_suspended: data.feedback_suspended,
        ...(data.max_rounds != null && { max_rounds: data.max_rounds }),
        ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }),
      }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) {
      setAgenticError(e?.message || String(e));
    } finally {
      setAgenticLoading(false);
    }
  };

  const handleAgenticSuspend = async () => {
    setAgenticLoading(true);
    setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/feedback/suspend/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ all: true }),
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, {
        status: data.status ?? prev?.status,
        ongoing: data.ongoing,
        feedback_suspended: data.feedback_suspended,
        ...(data.max_rounds != null && { max_rounds: data.max_rounds }),
        ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }),
      }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) {
      setAgenticError(e?.message || String(e));
    } finally {
      setAgenticLoading(false);
    }
  };

  const handleAgenticResume = async () => {
    setAgenticLoading(true);
    setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/feedback/resume/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ all: true }),
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, {
        status: data.status ?? prev?.status,
        ongoing: data.ongoing,
        feedback_suspended: data.feedback_suspended,
        ...(data.max_rounds != null && { max_rounds: data.max_rounds }),
        ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }),
      }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) {
      setAgenticError(e?.message || String(e));
    } finally {
      setAgenticLoading(false);
    }
  };

  const handleAgenticAddRound = async (all = true, topic = null) => {
    setAgenticLoading(true);
    setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/rounds/add/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(all ? { all: true } : { topic }),
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      publishUserMonthlyCost(data);
      setAgenticState((prev) => mergeAgenticUpdate(prev, {
        status: data.status ?? prev?.status,
        ongoing: data.ongoing,
        feedback_suspended: data.feedback_suspended,
        ...(data.max_rounds != null && { max_rounds: data.max_rounds }),
        ...(data.sub_comment_rounds != null && { sub_comment_rounds: data.sub_comment_rounds }),
      }));
      if (data.max_rounds != null) syncAgenticMaxRoundsFromServer(data.max_rounds);
      if (data.sub_comment_rounds != null) syncAgenticSubCommentRoundsFromServer(data.sub_comment_rounds);
    } catch (e) {
      setAgenticError(e?.message || String(e));
    } finally {
      setAgenticLoading(false);
    }
  };

  const handleAgenticVote = async () => {
    if (!vendorsList.length) return;
    setAgenticLoading(true);
    setAgenticError(null);
    try {
      const res = await fetch("/api/phases/agentic/vote/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voting_vendors: vendorsList }),
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      publishUserMonthlyCost(data);
      if (data?.agentic_update != null) {
        setAgenticState((prev) => mergeAgenticUpdate(prev, data.agentic_update));
      }
    } catch (e) {
      setAgenticError(e?.message || String(e));
    } finally {
      setAgenticLoading(false);
    }
  };

  const handleAgenticRefine = async (threadsOverride = null, options = {}) => {
    setAgenticLoading(true);
    setAgenticError(null);
    try {
      const opts = { method: "POST" };
      const body = {};
      if (threadsOverride != null && typeof threadsOverride === "object") {
        body.threads = threadsOverride;
      }
      const n = options.refine_sample_count;
      if (n != null && Number.isFinite(Number(n))) {
        body.refine_sample_count = Math.max(1, Math.min(20, Math.floor(Number(n))));
      }
      if (Object.keys(body).length > 0) {
        opts.headers = { "Content-Type": "application/json" };
        opts.body = JSON.stringify(body);
      }
      const res = await fetchWithHeartbeat("/api/phases/agentic/refine/", opts);
      if (res.isHeartbeat) return;
      if (res.data?.agentic_update != null) {
        setAgenticState((prev) => mergeAgenticUpdate(prev, res.data.agentic_update));
      }
    } catch (e) {
      setAgenticError(e?.message || String(e));
    } finally {
      setAgenticLoading(false);
    }
  };

  const approvePhase = async (phase, vendor, edits = {}) => {
    // Prevent duplicate calls if already approved/processing
    // Note: session tracking is a decent proxy for "is in flight" if we assume
    // that a phase session is set only once per phase. 
    // However, the best guard is the UI button being disabled.
    // We can also check if we already have the result data in the shelf to avoid re-fetching
    // unless explicitly asked (which would likely be a different function or cleared state).

    if (phase === "plan") {
      const sessionId = phaseSessions[vendor] || phaseSessionId;
      const payload = {
        session_id: sessionId,
        letter_plan: edits.letter_plan,
      };
      if (selectedCompanyReport) {
        payload.company_report = selectedCompanyReport;
      }
      try {
        const result = await fetchWithHeartbeat(
          `/api/phases/draft/${vendor}/`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          { getState: getStateForRestore }
        );
        if (result.isHeartbeat) {
          return null;
        }
        const data = result.data;
        populatePhaseShelf("draft", vendor, data);
        return data;
      } catch (e) {
        console.error("Draft phase error after plan approval", e);
        const errorMessage = extractErrorMessage(e);
        setPhaseVendorError("plan", vendor, errorMessage);
        throw new Error(errorMessage);
      }
    }

    if (phase === "draft") {
      // Approving the draft phase triggers refinement and sends the final letter to assembly
      const sessionId = phaseSessions[vendor] || phaseSessionId;
      const payload = {
        session_id: sessionId,
      };
      
      // Send edits if provided
      if (edits.draft_letter) {
        payload.draft_letter = edits.draft_letter;
      }
      if (edits.company_report) {
        payload.company_report = edits.company_report;
      }
      if (edits.feedback_overrides) {
        payload.feedback_override = edits.feedback_overrides;
      }

      try {
        const result = await fetchWithHeartbeat(
          `/api/phases/refine/${vendor}/`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
          { getState: getStateForRestore }
        );
        
        // Handle 202 Accepted (heartbeat/still processing)
        if (result.isHeartbeat) {
          return null;
        }
        
        const data = result.data;

        // Update current phase shelf to reset base state (approval "blesses" the edits)
        const currentDraft = phaseRegistryRef.current?.find(p => p.phase === "draft");
        const currentData = currentDraft?.cardData[vendor] || {};
        const updatedDraftData = { ...currentData, ...edits };
        // If we have feedback overrides, merge them into the base feedback
        if (edits.feedback_overrides) {
          updatedDraftData.feedback = {
            ...(currentData.feedback || {}),
            ...edits.feedback_overrides
          };
        }
        populatePhaseShelf("draft", vendor, updatedDraftData);
        
        // Update parent state for assembly phase
        const finalText = data.final_letter || edits.draft_letter || "";
        setLetters((prev) => ({ ...prev, [vendor]: finalText }));
        setVendorParagraphs((prev) => ({
          ...prev,
          [vendor]: splitIntoParagraphs(finalText, vendor),
        }));
        setVendorCosts((prev) => ({
          ...prev,
          [vendor]: data.cost ?? prev[vendor] ?? 0,
        }));
        
        // Check if all vendors are done
        const allDone = vendorsList.every((v) => {
          // We can't check phaseState anymore, so we'll check if they have letters
          return letters[v] || (v === vendor && finalText);
        });
        
        if (allDone) {
          setVendorStage("assembly");
          setAssemblyVisible(true);
        }
        
        return data;
      } catch (e) {
        console.error("Refine generation error", e);
        const errorMessage = extractErrorMessage(e);
        setPhaseVendorError("draft", vendor, errorMessage);
        throw new Error(errorMessage);
      }
    }
  };

  const approveAllPhase = async (phase) => {
    // Cards now own their state, so we just call approve for all vendors
    // Cards will handle their own approval logic
    const vendorList = Array.from(selectedVendors);
    await Promise.all(vendorList.map((v) => approvePhase(phase, v, {})));
  };

  const onAddParagraph = (paraObj) => {
    setFinalParagraphs((prev) => [...prev, { ...paraObj }]);
  };

  const clearVendorAssembly = (vendor) => {
    setVendorParagraphs((prev) => {
      const next = { ...prev };
      delete next[vendor];
      return next;
    });
    setVendorCosts((prev) => {
      const next = { ...prev };
      delete next[vendor];
      return next;
    });
    setLetters((prev) => {
      const next = { ...prev };
      delete next[vendor];
      return next;
    });
  };

  const rerunFromDraft = async (vendor) => {
    clearVendorAssembly(vendor);
    // Cards now own their state, so we just call approve
    // The card will handle clearing its own state
    await approvePhase("draft", vendor, {});
  };

  const resetForm = async () => {
    setVendorStage("input");
    setAgenticStage("input");
    setAgenticState(null);
    bestKnownThreadsRef.current = null;
    setAgenticError(null);
    setPhaseSessionId(null);
    // phaseState, phaseEdits, phaseErrors removed - cards own their state
    setLetters({});
    setVendorParagraphs({});
    setFailedVendors({});
    setPhaseErrors({});
    setPhaseSessions({});
    clearPhaseRegistryForNewRun();
    setPhaseFlowResetKey((k) => k + 1);
    setError(null);
    setFinalParagraphs([]);
    setAgenticFinalParagraphs([]);
    setDocumentId(null);
    setSavingFinal(false);
    setAgenticSavingFinal(false);
    setAgenticSaveError(null);
    setActiveTab("compose");
    setAssemblyVisible(true);
    // Keep extracted data and job text - don't clear them
    // setCompanyName("");
    // setJobTitle("");
    // setLocation("");
    // setLanguage("");
    // setSalary("");
    // setRequirements([]);
    setExtractionError(null);
    setSelectedCompanyReport(null);
    setSelectedTopDocs(null);
    setSelectedPocReport(null);
    setAllSearchResults([]);
    setSelectedDocIds(new Set());
    setCompanyExtractionResult(null);
    setCompanyResearchCountdown(null);
    setCompanyAutoResearchBlocked(false);
    setCompanyResearchNotification(null);
    
    // Initialize session when clicking back to ensure CV is loaded
    // This ensures CV is in session before starting phases again
    try {
      await fetchWithHeartbeat("/api/phases/init/", {
        method: "POST",
        body: JSON.stringify({}),
      });
    } catch (e) {
      console.error("Failed to initialize session when going back:", e);
      // Continue anyway - session will be initialized when starting phases
    }
  };

  const goBackToJobIntake = async () => {
    await resetForm();
    navigate("/");
  };

  const handleCloseSessionAndRestart = async () => {
    if (
      hasUnsavedGeneratedWork &&
      !window.confirm("Your unsaved work will be discarded. Continue?")
    ) {
      return;
    }
    try {
      await fetchWithHeartbeat("/api/phases/clear/", {
        method: "POST",
      });
    } catch (e) {
      console.error("Failed to clear session:", e);
      setError("Failed to close session. Please try again.");
      return;
    }
    await resetForm();
    clearAutocompleteFlowCache();
    setJobText("");
    setCompanyName("");
    setJobTitle("");
    setLocation("");
    setLanguage("");
    setSalary("");
    setRequirements([]);
    setCompetences({});
    setCompetenceOverrides({});
    setPointOfContact({
      name: "",
      role: "",
      contact_details: "",
      notes: "",
      company: "",
    });
    setAdditionalUserInfo("");
    setAdditionalCompanyInfo("");
    setShowPointOfContact(false);
    setShowAdditionalInfo(false);
    setExtractedData(null);
    setJobTextTranslations({});
    setJobTextViewLanguage("source");
    setLastJobTextSnapshot("");
    navigate("/");
  };

  const vendorsList = Array.from(selectedVendors);
  const toggleX = "40%"; // horizontal placement for phases/assembly toggles
  // Check if we have any letters (indicates at least one refine phase completed)
  const hasVendorAssembly = vendorsList.some((v) => letters[v]);
  const hasAgenticAssembly = agenticState?.status === "done";

  const renderCompose = () => (
    <>
      {showJobIntake ? (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
            <VendorSelector
              vendors={vendors}
              selected={selectedVendors}
              onToggle={toggleVendor}
              onSelectAll={selectAll}
            />
            <LanguageConfig />
          </div>
          <div style={{ marginTop: 10 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
              <label style={{ fontSize: "14px", fontWeight: 600, color: "var(--text-color)" }}>
                Job Description
              </label>
              <LanguageSelector
                languages={enabledLanguages}
                viewLanguage={jobTextViewLanguage}
                onLanguageChange={handleJobTextLanguageChange}
                hasTranslation={(code) => Boolean(jobTextTranslations[code])}
                disabled={false}
                isTranslating={isTranslatingJobText}
                size="small"
              />
            </div>
            {jobTextTranslationError && (
              <div style={{ color: "var(--error-text)", fontSize: "12px", marginBottom: 6 }}>
                {jobTextTranslationError}
              </div>
            )}
            <textarea
              style={{
                width: "100%",
                height: 150,
                backgroundColor: jobTextViewLanguage === "source" ? "var(--input-bg)" : "var(--panel-bg)",
                color: "var(--text-color)",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                padding: 8,
                opacity: jobTextViewLanguage === "source" ? 1 : 0.9,
              }}
              placeholder="Paste job description here"
              value={displayedJobText}
              onChange={(e) => {
                // Only allow editing in source language
                if (jobTextViewLanguage === "source") {
                  setJobText(e.target.value);
                }
              }}
              readOnly={jobTextViewLanguage !== "source"}
            />
          </div>

          {/* Additional Information - collapsible section */}
          <div style={{ marginTop: 15, textAlign: "center" }}>
            <button
              onClick={() => setShowAdditionalInfo(!showAdditionalInfo)}
              style={{
                padding: "6px 16px",
                fontSize: "13px",
                backgroundColor: "transparent",
                color: "var(--text-color)",
                border: "1px dashed var(--border-color)",
                borderRadius: "4px",
                cursor: "pointer",
                opacity: 0.8,
              }}
            >
              {showAdditionalInfo ? "− Hide additional information" : "+ Anything extra the AI should consider for this?"}
            </button>
            {showAdditionalInfo && (
              <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 15 }}>
                <div>
                  <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600, color: "var(--text-color)" }}>
                    About You (not in CV)
                  </label>
                  <textarea
                    style={{
                      width: "100%",
                      height: 80,
                      backgroundColor: "var(--input-bg)",
                      color: "var(--text-color)",
                      border: "1px solid var(--border-color)",
                      borderRadius: "4px",
                      padding: 8,
                      fontSize: "14px",
                    }}
                    placeholder={`Info about you relevant to this position that isn't in your CV, e.g.,
'this certification/project that is rarely relevant might make the difference here',
'I am a power user of this service they provide', 'my commute would be easy', ...`}
                    value={additionalUserInfo}
                    onChange={(e) => setAdditionalUserInfo(e.target.value)}
                  />
                  <p style={{ marginTop: 4, fontSize: "11px", color: "var(--text-color)", opacity: 0.7 }}>
                    Passed to the letter writer and CV accuracy check.
                  </p>
                </div>
                <div>
                  <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600, color: "var(--text-color)" }}>
                    About the Company
                  </label>
                  <textarea
                    style={{
                      width: "100%",
                      height: 80,
                      backgroundColor: "var(--input-bg)",
                      color: "var(--text-color)",
                      border: "1px solid var(--border-color)",
                      borderRadius: "4px",
                      padding: 8,
                      fontSize: "14px",
                    }}
                    placeholder={`Extra info about the company or role, e.g.,
'I have insider information on what they are like and care about / what they really need for this position',
'I want to highlight this aspect of their culture or needs on why they might want to hire me', ...`}
                    value={additionalCompanyInfo}
                    onChange={(e) => setAdditionalCompanyInfo(e.target.value)}
                  />
                  <p style={{ marginTop: 4, fontSize: "11px", color: "var(--text-color)", opacity: 0.7 }}>
                    Passed to company background research.
                  </p>
                </div>
              </div>
            )}
          </div>
          
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button
              onClick={extractData}
              disabled={extracting || !jobText.trim()}
              style={{
                padding: "10px 20px",
                backgroundColor: extracting || !jobText.trim() ? "var(--header-bg)" : "#10b981",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: extracting || !jobText.trim() ? "not-allowed" : "pointer",
              }}
            >
              {extracting ? "Extracting..." : "Extract data"}
            </button>
            {extractionError && (
              <div style={{ color: "var(--error-text)", padding: "10px 0", fontSize: "14px" }}>
                {extractionError}
              </div>
            )}
          </div>

          <div style={{ marginTop: 20, padding: 15, border: "1px solid var(--border-color)", borderRadius: 8, backgroundColor: "var(--input-bg)" }}>
             <h3 style={{ marginTop: 0, fontSize: "16px", fontWeight: 600 }}>Company & Job Details</h3>
             <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    <div>
                        <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Job Title *</label>
                        <input type="text" value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Job title" />
                    </div>
                    <div>
                        <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Company Name</label>
                        <input type="text" value={companyName} onChange={(e) => setCompanyName(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Company name" />
                    </div>
                    <div>
                        <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Location</label>
                        <input type="text" value={location} onChange={(e) => setLocation(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Location" />
                    </div>
                    <div>
                        <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Language</label>
                        <input type="text" value={language} onChange={(e) => setLanguage(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Language" />
                    </div>
                    <div>
                        <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Salary</label>
                        <input type="text" value={salary} onChange={(e) => setSalary(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Salary range" />
                    </div>
                </div>
                <div>
                    {/* Countdown banner after company extraction (Part 3) completes */}
                    {companyResearchCountdown !== null && companyResearchCountdown > 0 && (
                      <div style={{
                        padding: "8px 12px",
                        marginBottom: 8,
                        borderRadius: 4,
                        border: "1px solid #5b9bd5",
                        backgroundColor: "rgba(91, 155, 213, 0.1)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        fontSize: 13,
                      }}>
                        <span>
                          Extracted: <strong>{companyExtractionResult?.company_name || companyName || "—"}</strong>
                          {companyExtractionResult?.job_title ? ` — ${companyExtractionResult.job_title}` : ""}
                          {companyExtractionResult?.location ? ` (${companyExtractionResult.location})` : ""}
                          {". "}Background research in <strong>{companyResearchCountdown}s</strong>…
                        </span>
                        <button
                          onClick={() => {
                            setCompanyResearchCountdown(null);
                            setCompanyAutoResearchBlocked(true);
                            setCompanyResearchNotification("Auto-research paused. Edit details above, then click \"Start Research\" below.");
                          }}
                          style={{
                            padding: "3px 10px",
                            fontSize: 12,
                            border: "1px solid var(--border-color)",
                            borderRadius: 4,
                            backgroundColor: "var(--bg-color)",
                            color: "var(--text-color)",
                            cursor: "pointer",
                            whiteSpace: "nowrap",
                            marginLeft: 12,
                          }}
                        >
                          Edit first
                        </button>
                      </div>
                    )}
                    {companyAutoResearchBlocked && companyResearchNotification && (
                      <div style={{
                        padding: "6px 12px",
                        marginBottom: 8,
                        borderRadius: 4,
                        border: "1px solid #d4a843",
                        backgroundColor: "rgba(212, 168, 67, 0.1)",
                        fontSize: 12,
                        color: "var(--text-color)",
                      }}>
                        {companyResearchNotification}
                      </div>
                    )}
                    {/* Research result notification */}
                    {!companyAutoResearchBlocked && companyResearchNotification && companyResearchCountdown === null && (
                      <div style={{
                        padding: "6px 12px",
                        marginBottom: 8,
                        borderRadius: 4,
                        border: `1px solid ${companyResearchNotification.includes("cached") || companyResearchNotification.includes("similar") ? "#5a9e6f" : "#5b9bd5"}`,
                        backgroundColor: companyResearchNotification.includes("cached") || companyResearchNotification.includes("similar") ? "rgba(90, 158, 111, 0.1)" : "rgba(91, 155, 213, 0.1)",
                        fontSize: 12,
                        color: "var(--text-color)",
                      }}>
                        {companyResearchNotification}
                      </div>
                    )}
                    <ResearchComponent 
                        label="Company Research"
                        type="company"
                        query={companyName}
                        context={{ job_text: jobText, additional_company_info: additionalCompanyInfo }}
                        vendors={backgroundModels}
                        onResultSelected={(report, topDocs, source, resolvedName) => {
                            setSelectedCompanyReport(report);
                            setSelectedTopDocs(topDocs);
                            if (topDocs && topDocs.length > 0) {
                              const llmIds = new Set(topDocs.map(d => d.id || d.company_name).filter(Boolean));
                              setSelectedDocIds(llmIds);
                            }
                            // Show notification based on how the research was resolved
                            if (source === "cache") {
                              setCompanyResearchNotification(`Found cached research for "${resolvedName || companyName}".`);
                            } else if (source === "similar") {
                              setCompanyResearchNotification(`Found similar company "${resolvedName}", using existing research.`);
                            } else {
                              setCompanyResearchNotification(`New research completed for "${companyName}".`);
                            }
                            setCompanyAutoResearchBlocked(false);
                        }}
                        externalTrigger={triggerCompanyResearch}
                    />
                </div>
             </div>
          </div>

          <div style={{ marginTop: 20, padding: 15, border: "1px solid var(--border-color)", borderRadius: 8, backgroundColor: "var(--input-bg)" }}>
             <button
               onClick={() => setShowPointOfContact(!showPointOfContact)}
               style={{
                 width: "100%",
                 display: "flex",
                 justifyContent: "space-between",
                 alignItems: "center",
                 marginTop: 0,
                 marginBottom: 0,
                 padding: 0,
                 fontSize: "16px",
                 fontWeight: 600,
                 color: "var(--text-color)",
                 background: "transparent",
                 border: "none",
                 cursor: "pointer",
                 textAlign: "left",
               }}
               aria-expanded={showPointOfContact}
               aria-label={showPointOfContact ? "Collapse point of contact" : "Expand point of contact"}
             >
               <span>Point of Contact</span>
               <span style={{ fontSize: 12, opacity: 0.8 }}>{showPointOfContact ? "▲" : "▼"}</span>
             </button>
             {!hasPointOfContactData && (
               <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--secondary-text-color)" }}>
                 Empty - collapsed by default.
               </p>
             )}
             {showPointOfContact && (
             <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 10 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div>
                    <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Name</label>
                    <input type="text" value={pointOfContact.name} onChange={(e) => setPointOfContact({ ...pointOfContact, name: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Contact name" />
                  </div>
                  <div>
                    <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Role</label>
                    <input type="text" value={pointOfContact.role} onChange={(e) => setPointOfContact({ ...pointOfContact, role: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Role in company" />
                  </div>
                  <div>
                    <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Contact Details</label>
                    <input type="text" value={pointOfContact.contact_details} onChange={(e) => setPointOfContact({ ...pointOfContact, contact_details: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Email, phone, etc." />
                  </div>
                  <div>
                    <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Company (if intermediary)</label>
                    <input type="text" value={pointOfContact.company} onChange={(e) => setPointOfContact({ ...pointOfContact, company: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Intermediary company" />
                  </div>
                  <div>
                    <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Notes</label>
                    <textarea value={pointOfContact.notes} onChange={(e) => setPointOfContact({ ...pointOfContact, notes: e.target.value })} style={{ width: "100%", height: 48, padding: 6, fontSize: 13, resize: "vertical", backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Notes about contact" />
                  </div>
                </div>
                <div>
                    <ResearchComponent 
                        label="POC Research"
                        type="poc"
                        query={pointOfContact.name}
                        context={{ job_text: jobText, company_name: companyName }}
                        vendors={backgroundModels}
                        onResultSelected={(report, topDocs) => {
                            setSelectedPocReport(report);
                        }}
                        externalTrigger={triggerPocResearch}
                    />
                </div>
             </div>
             )}
          </div>

          {/* Two-column layout: Similar offers (left) | Competences (right) */}
          <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gridTemplateRows: "minmax(0, 1fr)", gap: 16, height: "min(80vh, 600px)" }}>
            {/* Left column: Similar previous job offers from RAG */}
            <div style={{ display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
              <div style={{ marginBottom: 4, flexShrink: 0 }}>
                <label style={{ display: "block", fontSize: "14px", fontWeight: 600 }}>
                  Similar Previous Offers
                </label>
                <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginTop: 2 }}>
                  RAG-retrieved offers. LLM picks are highlighted. Toggle to include/exclude from draft.
                </div>
              </div>
              <div style={{ flex: 1, minHeight: 0 }}>
                <SimilarOffersCarousel
                  allSearchResults={allSearchResults}
                  topDocs={selectedTopDocs || []}
                  selectedDocIds={selectedDocIds}
                  onSelectionChange={setSelectedDocIds}
                />
              </div>
            </div>

            {/* Right column: Key competences */}
            <div style={{ display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
              <div style={{ marginBottom: 4, flexShrink: 0 }}>
                <label style={{ display: "block", fontSize: "14px", fontWeight: 600 }}>
                  How good is your fit? Key competences weighted match:
                  {(() => {
                  const keys = Object.keys(competences);
                  if (keys.length === 0) return null;
                  let totalWeighted = 0;
                  let totalWeight = 0;
                  keys.forEach(key => {
                    const num = getEffectiveRating(key, competences, competenceScaleConfig, competenceOverrides);
                    const imp = getEffectiveImportance(key, competences, competenceScaleConfig, competenceOverrides);
                    if (num.presence != null && imp != null) {
                      totalWeighted += num.presence * imp;
                      totalWeight += imp;
                    }
                  });
                  if (totalWeight === 0) return null;
                  const avgPresence = totalWeighted / totalWeight;
                  const avgStars = Math.round(avgPresence);
                  return (
                    <span style={{ fontWeight: 500, color: "var(--secondary-text-color)", marginLeft: 6 }}>
                      <span style={{ fontSize: 11 }}>{"★".repeat(avgStars)}{"☆".repeat(5 - avgStars)}</span> ({avgPresence.toFixed(1)})
                    </span>
                  );
                })()}
                </label>
                <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginTop: 2 }}>
                  CV fit levels can be adjusted. They will be remembered.
                </div>
              </div>
              <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
                <div style={{ marginBottom: 12 }}>
                  <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: 4 }}>
                    What problem is this hire meant to solve?
                  </label>
                  <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginBottom: 6 }}>
                    Extracted in the same pass as key competences; edit if the model missed nuance.
                  </div>
                  <textarea
                    value={hireProblem}
                    onChange={(e) => setHireProblem(e.target.value)}
                    placeholder="e.g. scale the data platform, lead a regulatory migration, own the first sales motion in a new region…"
                    rows={4}
                    style={{
                      width: "100%",
                      boxSizing: "border-box",
                      padding: 8,
                      fontSize: 13,
                      resize: "vertical",
                      backgroundColor: "var(--bg-color)",
                      color: "var(--text-color)",
                      border: "1px solid var(--border-color)",
                      borderRadius: 4,
                      fontFamily: "inherit",
                    }}
                  />
                </div>
                <CompetencesList
                  requirements={requirements}
                  competences={competences}
                  scaleConfig={competenceScaleConfig}
                  overrides={competenceOverrides}
                  onOverridesChange={setCompetenceOverrides}
                  editable
                  onRequirementsChange={setRequirements}
                  onCompetencesChange={setCompetences}
                />
              </div>
            </div>
          </div>
          {error && <p style={{ color: "var(--error-text)" }}>{error}</p>}
          {documentSaveNotice && (
            <p
              role="status"
              style={{
                color: "var(--secondary-text-color)",
                background: "var(--warning-bg)",
                border: "1px solid var(--warning-border)",
                padding: "10px 12px",
                borderRadius: 4,
              }}
            >
              {documentSaveNotice}
            </p>
          )}

          <div style={{ marginTop: 20, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              onClick={handleStartAutocomplete}
              disabled={!jobText || !jobTitle.trim()}
              style={{
                padding: "10px 20px",
                backgroundColor: !jobText || !jobTitle.trim() ? "var(--header-bg)" : "#0d9488",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: !jobText || !jobTitle.trim() ? "not-allowed" : "pointer",
              }}
            >
              Start autocomplete
            </button>
            <AutocompletePlanModelSelect />
            <button
              onClick={handleSubmit}
              disabled={loading || !jobText || !jobTitle.trim() || selectedVendors.size === 0}
              style={{
                padding: "10px 20px",
                backgroundColor: loading || !jobText || !jobTitle.trim() || selectedVendors.size === 0 ? "var(--header-bg)" : "#3b82f6",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: loading || !jobText || !jobTitle.trim() || selectedVendors.size === 0 ? "not-allowed" : "pointer",
              }}
            >
              {loading ? "Starting..." : "Start vendor flow"}
            </button>
            <div
              style={{
                width: 1,
                minHeight: 24,
                backgroundColor: "var(--border-color)",
                margin: "0 4px",
              }}
              aria-hidden="true"
            />
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <button
                onClick={handleSubmitAgentic}
                disabled={agenticLoading || !jobText || !jobTitle.trim() || selectedVendors.size === 0}
                style={{
                  padding: "10px 20px",
                  backgroundColor: agenticLoading || !jobText || !jobTitle.trim() || selectedVendors.size === 0 ? "var(--header-bg)" : "#7c3aed",
                  color: "white",
                  border: "none",
                  borderRadius: "4px",
                  cursor: agenticLoading || !jobText || !jobTitle.trim() || selectedVendors.size === 0 ? "not-allowed" : "pointer",
                }}
              >
                {agenticLoading ? "Starting…" : "Start agentic flow"}
              </button>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 13, color: "var(--text-color)" }}>Max rounds:</span>
                <input
                  type="number"
                  min={1}
                  max={15}
                  value={agenticMaxRounds}
                  onChange={(e) => setAgenticMaxRounds(Math.max(1, Math.min(15, parseInt(e.target.value, 10) || 3)))}
                  style={{ width: 48, padding: "6px 8px", borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }} title="Per main round: add-subcomment phases then vote/prune, after top-level comments (0 = skip sub-comments).">
                <span style={{ fontSize: 13, color: "var(--text-color)" }}>Sub-comment rounds:</span>
                <input
                  type="number"
                  min={0}
                  max={8}
                  value={agenticSubCommentRounds}
                  onChange={(e) => setAgenticSubCommentRounds(Math.max(0, Math.min(8, parseInt(e.target.value, 10) || 0)))}
                  style={{ width: 48, padding: "6px 8px", borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }}
                />
              </label>
            </div>
          </div>
        </>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "stretch",
            gap: 12,
            width: "100%",
            minHeight: "calc(100vh - 120px)",
            boxSizing: "border-box",
          }}
        >
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
            marginBottom: 10,
            position: "relative",
            flexWrap: "wrap",
          }}
        >
          <button
            onClick={goBackToJobIntake}
            style={{
              padding: "8px 16px",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
              cursor: "pointer",
            }}
          >
            ← Back to job details
          </button>
          <button
            type="button"
            onClick={handleCloseSessionAndRestart}
            style={{
              padding: "8px 16px",
              backgroundColor: "#b91c1c",
              color: "white",
              border: "1px solid #991b1b",
              borderRadius: "4px",
              cursor: "pointer",
            }}
            title="Clear current session and restart with a blank input form"
          >
            Close session and restart
          </button>
          {(flow === "vendor" && vendorStage === "assembly" && assemblyVisible) && (
            <div
              style={{
                position: "absolute",
                left: toggleX,
                transform: "translateX(-50%)",
              }}
            >
              <button
                onClick={() => setAssemblyVisible(false)}
                style={{
                  padding: "10px 14px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "999px",
                  backgroundColor: "var(--button-bg)",
                  color: "var(--button-text)",
                  cursor: "pointer",
                  boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
                }}
              >
                ↑ Show phases
              </button>
            </div>
          )}
          {(flow === "agentic" && agenticStage === "assembly") && (
            <div
              style={{
                position: "absolute",
                left: toggleX,
                transform: "translateX(-50%)",
              }}
            >
              <button
                type="button"
                onClick={() => agenticPhasesRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
                style={{
                  padding: "10px 14px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "999px",
                  backgroundColor: "var(--button-bg)",
                  color: "var(--button-text)",
                  cursor: "pointer",
                  boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
                }}
              >
                ↑ Back to feedback
              </button>
            </div>
          )}
          <div style={{ marginLeft: "auto" }}>
            <LanguageConfig />
          </div>
        </div>
        {error && <p style={{ color: "var(--error-text)" }}>{error}</p>}
        {documentSaveNotice && (
        <p
          role="status"
          style={{
            color: "var(--secondary-text-color)",
            background: "var(--warning-bg)",
            border: "1px solid var(--warning-border)",
            padding: "10px 12px",
            borderRadius: 4,
          }}
        >
          {documentSaveNotice}
        </p>
      )}
          {/* Flow-specific phases: above the final assembly so scroll-up or back shows them. Never show vendor PhaseFlow on agentic route. */}
          {flow === "agentic" && (
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
              vendorColors={vendorColors}
              loading={agenticLoading}
              error={agenticError}
              onPollState={fetchAgenticPoll}
              pollIntervalMs={1000}
            />
            </div>
          )}
          {flow === "vendor" && (
            <div style={{ display: (vendorStage === "assembly" && assemblyVisible) ? "none" : "block" }}>
              <PhaseFlow
                vendorsList={vendorsList}
                flowResetKey={phaseFlowResetKey}
                onEditChange={updatePhaseEdit}
                onApprove={approvePhase}
                onApproveAll={approveAllPhase}
                sessionId={phaseSessionId}
                documentId={documentId}
                draftFeedbackRegistryRef={draftFeedbackRegistryRef}
                onClearPhaseFetchError={onClearPhaseFetchError}
                onRetryPhaseFetch={onRetryPhaseFetch}
                onRegisterPhases={(phases) => {
                  phaseRegistryRef.current = phases;
                }}
                onPhaseComplete={(vendor, phase, data) => {
                  if (phase === "draft" && data?.final_letter) {
                    // Already handled in approvePhase
                  }
                }}
              />
            </div>
          )}

          {/* Final assembly: same LetterTabs for phased flow and agentic flow (when done) */}
          {((flow === "vendor" && vendorStage === "assembly") || (flow === "agentic" && agenticStage === "assembly")) && (
            <div style={{ 
              position: "relative", 
              paddingTop: 4,
              display: (flow === "agentic" && agenticStage === "assembly") ? "block" : (assemblyVisible ? "block" : "none")
            }}>
              <LetterTabs
                vendorsList={
                  flow === "agentic"
                    ? Object.keys(agenticState?.final_letters || {}).filter(Boolean)
                    : vendorsList
                }
                vendorParagraphs={
                  flow === "agentic" && agenticState?.final_letters
                    ? Object.fromEntries(
                        Object.entries(agenticState.final_letters).map(([v, text]) => [
                          v,
                          splitIntoParagraphs(text || "", v),
                        ])
                      )
                    : vendorParagraphs
                }
                vendorCosts={
                  flow === "agentic"
                    ? (() => {
                        const cost = agenticState?.cost ?? 0;
                        const vs = Object.keys(agenticState?.final_letters || {});
                        return vs.length ? Object.fromEntries(vs.map((v) => [v, cost / vs.length])) : {};
                      })()
                    : vendorCosts
                }
                vendorRefineCosts={
                  flow === "agentic"
                    ? (Object.keys(agenticState?.final_letters || {})).reduce((acc, v) => ({ ...acc, [v]: agenticState?.cost ?? 0 }), {})
                    : vendorRefineCosts
                }
                finalParagraphs={flow === "agentic" ? agenticFinalParagraphs : finalParagraphs}
                setFinalParagraphs={flow === "agentic" ? setAgenticFinalParagraphs : setFinalParagraphs}
                originalText={jobText}
                requirements={requirements}
                competences={competences}
                competenceScaleConfig={competenceScaleConfig}
                competenceOverrides={competenceOverrides}
                vendorColors={vendorColors}
                failedVendors={flow === "agentic" ? {} : failedVendors}
                onRetry={
                  flow === "agentic"
                    ? async () => {}
                    : async (vendor) => {
                        setFailedVendors((prev) => {
                          const next = { ...prev };
                          delete next[vendor];
                          return next;
                        });
                        try {
                          await approvePhase("draft", vendor, {});
                        } catch (e) {
                          console.error("Retry error:", e);
                          const errorMessage = extractErrorMessage(e);
                          setFailedVendors((prev) => ({ ...prev, [vendor]: errorMessage }));
                        }
                      }
                }
                onAddParagraph={onAddParagraph}
                onSave={flow === "agentic" ? persistAgenticLetter : persistFinalLetter}
                savingFinal={flow === "agentic" ? agenticSavingFinal : savingFinal}
                vendorFeedback={vendorFeedback}
                setVendorFeedback={setVendorFeedback}
                refineSamples={flow === "agentic" ? (agenticState?.refine_samples || {}) : {}}
                vendorDraftParagraphs={
                  flow === "agentic" && agenticState?.draft_letters
                    ? Object.fromEntries(
                        Object.entries(agenticState.draft_letters).map(([v, text]) => [
                          v,
                          splitIntoParagraphs(text || "", v),
                        ])
                      )
                    : undefined
                }
                selectedKeyTerm={competenceHighlightTerm}
                onTermClick={handleCompetenceTermClick}
                onHighlightContextChange={handleAssemblyHighlightCtx}
              />
            </div>
          )}
          </div>
          {referenceSidebarCollapsed ? (
            <button
              type="button"
              onClick={() => setReferenceSidebarCollapsed(false)}
              aria-label="Expand job and fit reference panel"
              title="Job offer, key competences, company report, extracted goal"
              style={{
                flexShrink: 0,
                width: 44,
                alignSelf: "stretch",
                minHeight: 160,
                marginTop: 0,
                padding: "10px 6px",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "flex-start",
                gap: 10,
                border: "1px solid var(--border-color)",
                borderRadius: 8,
                background: "var(--card-bg)",
                color: "var(--text-color)",
                cursor: "pointer",
                boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
                boxSizing: "border-box",
              }}
            >
              <span style={{ fontSize: 16, lineHeight: 1, flexShrink: 0 }} aria-hidden>
                ‹
              </span>
              {[
                "Job offer",
                "Key fit",
                "Report",
                ...(selectedPocReport ? ["POC"] : []),
              ].map((label) => (
                <span
                  key={label}
                  style={{
                    writingMode: "vertical-rl",
                    textOrientation: "mixed",
                    transform: "rotate(180deg)",
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: "0.05em",
                    color: "var(--secondary-text-color)",
                    lineHeight: 1.2,
                    whiteSpace: "nowrap",
                  }}
                >
                  {label}
                </span>
              ))}
            </button>
          ) : (
            <div
              style={{
                width: 340,
                flexShrink: 0,
                alignSelf: "stretch",
                minHeight: 0,
                display: "flex",
                flexDirection: "column",
                border: "1px solid var(--border-color)",
                borderRadius: 8,
                overflow: "hidden",
                background: "var(--card-bg)",
              }}
            >
              <JobDescriptionColumn
                jobText={jobText}
                companyReport={selectedCompanyReport}
                pocReport={selectedPocReport}
                requirements={requirements}
                competences={competences}
                scaleConfig={competenceScaleConfig}
                overrides={competenceOverrides}
                width="100%"
                minWidth="0"
                languages={enabledLanguages}
                selectedKeyTerm={competenceHighlightTerm}
                onTermClick={handleCompetenceTermClick}
                competenceCounts={assemblyHighlightCtx.competenceCounts || {}}
                finalAssemblyText={assemblyHighlightCtx.finalAssemblyTextNormalized || ""}
                hireProblem={hireProblem}
                onHireProblemChange={setHireProblem}
                onCollapsePanel={() => setReferenceSidebarCollapsed(true)}
              />
            </div>
          )}
        </div>
      )}

      {Object.keys(failedVendors).length > 0 && (
        <div
          style={{
            marginTop: 10,
            padding: 10,
            background: "var(--warning-bg)",
            border: "1px solid var(--warning-border)",
            color: "var(--text-color)",
            borderRadius: "4px",
          }}
        >
          <h3 style={{ marginTop: 0 }}>Failed Vendors:</h3>
          {Object.entries(failedVendors).map(([vendor, errorMsg]) => (
            <div key={vendor} style={{ marginBottom: 10 }}>
              <strong style={{ color: "var(--text-color)" }}>{vendor}:</strong>{" "}
              {errorMsg}
              <button
                onClick={async () => {
                  // Default to draft phase for failed vendors
                  // In the future, we could track which phase failed
                  setFailedVendors((prev) => {
                    const next = { ...prev };
                    delete next[vendor];
                    return next;
                  });
                  try {
                    const retryFn = createRetryForPhase("draft", vendor);
                    await retryFn();
                  } catch (e) {
                    console.error("Retry error:", e);
                    const errorMessage = extractErrorMessage(e);
                    setFailedVendors((prev) => ({ ...prev, [vendor]: errorMessage }));
                  }
                }}
                style={{
                  marginLeft: 10,
                  padding: "4px 8px",
                  backgroundColor: "var(--button-bg)",
                  color: "var(--button-text)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  cursor: "pointer",
                }}
              >
                Retry
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Assembly (LetterTabs) is shown when vendorStage or agenticStage is "assembly" above */}
    </>
  );

  const renderAutocompleteView = () => (
    <>
      <div style={{ marginBottom: 12 }}>
        <button
          type="button"
          onClick={() => navigate("/")}
          style={{
            padding: "8px 16px",
            backgroundColor: "var(--button-bg)",
            color: "var(--button-text)",
            border: "1px solid var(--border-color)",
            borderRadius: "4px",
            cursor: "pointer",
          }}
        >
          ← Back to job details
        </button>
      </div>
      {error && <p style={{ color: "var(--error-text)" }}>{error}</p>}
      <AutocompleteFlow
        {...autocompleteContextProps}
        onSaveAndCopy={persistAutocompleteLetter}
        savingFinal={savingFinal}
      />
    </>
  );

  return (
    <div
      style={{
        padding: 20,
        backgroundColor: "var(--bg-color)",
        color: "var(--text-color)",
        minHeight: "100vh",
      }}
    >
      {costTrackingError && (
        <div
          role="alert"
          style={{
            marginBottom: 12,
            padding: "10px 14px",
            backgroundColor: "var(--error-bg, #fef2f2)",
            border: "1px solid var(--error-border, #fecaca)",
            borderRadius: 6,
            color: "var(--error-text, #b91c1c)",
            fontSize: 13,
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            alignItems: "flex-start",
          }}
        >
          <span>
            <strong>Cost tracking unavailable:</strong> {costTrackingError}
          </span>
          <button
            type="button"
            onClick={() => setCostTrackingError(null)}
            style={{
              flexShrink: 0,
              border: "none",
              background: "transparent",
              color: "inherit",
              cursor: "pointer",
              fontSize: 16,
              lineHeight: 1,
            }}
            aria-label="Dismiss cost tracking warning"
          >
            ×
          </button>
        </div>
      )}

      <div style={{ position: "relative", marginBottom: 12 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 8,
              flexWrap: "wrap",
              minWidth: 0,
            }}
          >
            <h1 style={{ margin: 0, color: "var(--text-color)" }}>Letter Writer</h1>
            <AppVersionLabel />
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button
              onClick={() => setShowStyleBlade(true)}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor: "var(--button-bg)",
                color: "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              AI Instructions
            </button>
            <button
              onClick={() => setShowCvOverlay(true)}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor: showCvOverlay ? "#3b82f6" : "var(--button-bg)",
                color: showCvOverlay ? "white" : "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Your CV
            </button>
            <button
              onClick={() => setShowDocumentsOverlay(true)}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor: showDocumentsOverlay ? "#3b82f6" : "var(--button-bg)",
                color: showDocumentsOverlay ? "white" : "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Previous Examples
            </button>
            <button
              onClick={() => setShowSettingsOverlay(true)}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor: showSettingsOverlay ? "#3b82f6" : "var(--button-bg)",
                color: showSettingsOverlay ? "white" : "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Settings
            </button>

            <CostDisplay onNavigate={() => setShowCostsOverlay(true)} />
            <AuthButton />
          </div>
        </div>

      </div>

      {/* Main content is always the flow (compose). AI Instructions, CV, Previous Examples, Settings, Costs are overlays. */}
      {flow === "autocomplete" ? renderAutocompleteView() : renderCompose()}

      <OverlayPanel title="Your CV" isOpen={showCvOverlay} onClose={() => setShowCvOverlay(false)}>
        <PersonalDataPage />
      </OverlayPanel>
      <OverlayPanel title="Previous Examples" isOpen={showDocumentsOverlay} onClose={() => setShowDocumentsOverlay(false)}>
        <DocumentsPage />
      </OverlayPanel>
      <OverlayPanel title="Settings" isOpen={showSettingsOverlay} onClose={() => setShowSettingsOverlay(false)}>
        <SettingsPage
          vendors={vendors}
          selectedVendors={selectedVendors}
          setSelectedVendors={setSelectedVendors}
          setBackgroundModels={setBackgroundModels}
          onCompetenceScalesChange={() => setCompetenceScaleConfig(getScaleConfig())}
          guardBeforeEnablingLocal={guardBeforeEnablingLocal}
        />
      </OverlayPanel>
      <OverlayPanel title="API Costs" isOpen={showCostsOverlay} onClose={() => setShowCostsOverlay(false)}>
        <CostsPage />
      </OverlayPanel>

      <LocalPricingWarningModal
        isOpen={localPricingModalOpen}
        onContinue={handleLocalPricingModalContinue}
        onCancel={handleLocalPricingModalCancel}
        dismissChecked={localPricingDismissChecked}
        onDismissCheckedChange={setLocalPricingDismissChecked}
      />

      <SessionExpiredModal isOpen={showSessionExpiredModal} />

      {/* Floating toggle to assembly while still in phases (after first refinement ready) */}
      {!showInput && ((flow === "vendor" && vendorStage !== "assembly" && hasVendorAssembly) || (flow === "agentic" && agenticStage !== "assembly" && hasAgenticAssembly)) && (
        <div
          style={{
            position: "fixed",
            bottom: 0,
            left: toggleX,
            zIndex: 20,
            pointerEvents: "none",
            transform: "translateX(-50%)",
          }}
        >
          <button
            onClick={() => {
              if (flow === "vendor") setVendorStage("assembly");
              else setAgenticStage("assembly");
              setAssemblyVisible(true);
            }}
            style={{
              padding: "8px 20px",
              border: "1px solid var(--border-color)",
              borderBottom: "none",
              borderRadius: "12px 12px 0 0",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              boxShadow: "0 -2px 10px rgba(0,0,0,0.1)",
              pointerEvents: "auto",
              fontSize: "14px",
              fontWeight: "500",
            }}
          >
            ↓ To final assembly
          </button>
        </div>
      )}

      {/* Floating toggle back to assembly when hidden (phases view) */}
      {!showInput && flow === "vendor" && vendorStage === "assembly" && !assemblyVisible && (
        <div
          style={{
            position: "fixed",
            bottom: 0,
            left: toggleX,
            transform: "translateX(-50%)",
            zIndex: 20,
            pointerEvents: "none",
          }}
        >
          <button
            onClick={() => setAssemblyVisible(true)}
            style={{
              padding: "8px 20px",
              border: "1px solid var(--border-color)",
              borderBottom: "none",
              borderRadius: "12px 12px 0 0",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              boxShadow: "0 -2px 10px rgba(0,0,0,0.1)",
              pointerEvents: "auto",
              fontSize: "14px",
              fontWeight: "500",
            }}
          >
            ↓ Back to assembly
          </button>
        </div>
      )}

      <StyleInstructionsBlade
        isOpen={showStyleBlade}
        onClose={() => setShowStyleBlade(false)}
      />
    </div>
  );
}

