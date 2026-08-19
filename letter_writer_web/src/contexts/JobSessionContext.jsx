import React, { createContext, useContext, useState, useEffect, useMemo, useRef, useCallback } from "react";
import { fetchWithHeartbeat, initializeCsrfToken } from "../utils/apiHelpers";
import { getScaleConfig, getEffectiveRating, getEffectiveImportance, buildCompetenceRatingsForProfile } from "../utils/competenceScales";
import { useLanguages } from "./LanguageContext";
import { translateText } from "../utils/translate";
import { getLanguageTranslateParams } from "../utils/languageLevels";
import { isLocalPricingWarningDismissed, dismissLocalPricingWarningForSession } from "../components/LocalPricingWarningModal.jsx";
import {
  AUTH_SESSION_EXPIRED_EVENT,
  AUTH_SESSION_RESTORED_EVENT,
  fetchAuthStatus,
  markInitialAuthCheckComplete,
  reportSessionExpired,
} from "../utils/authSession.js";
import { scheduleGoogleOAuthRedirect, clearOAuthRedirectCooldown } from "../utils/googleOAuthRedirect";

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

export const JobSessionContext = createContext(null);

export function useJobSession() {
  const ctx = useContext(JobSessionContext);
  if (!ctx) throw new Error("useJobSession must be used within a JobSessionProvider");
  return ctx;
}

export function JobSessionProvider({ children }) {
  const { enabledLanguages, languages: profileLanguages, translationProvider } = useLanguages();

  // Auth state (managed here so vendor/personal-data fetches can gate on it)
  const [isAuthenticated, setIsAuthenticated] = useState(null);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [authRefreshGeneration, setAuthRefreshGeneration] = useState(0);
  const [showSessionExpiredModal, setShowSessionExpiredModal] = useState(false);

  useEffect(() => {
    fetch("/api/auth/status/", { credentials: "include" })
      .then((res) => res.json())
      .then((data) => {
        if (data.authenticated) {
          clearOAuthRedirectCooldown();
          setIsAuthenticated(true);
          markInitialAuthCheckComplete(true);
          initializeCsrfToken().catch((e) => console.warn("Failed to init CSRF:", e));
        } else {
          markInitialAuthCheckComplete(false);
          scheduleGoogleOAuthRedirect();
          setIsAuthenticated(false);
        }
        setCheckingAuth(false);
      })
      .catch((e) => {
        console.error("Auth check failed:", e);
        markInitialAuthCheckComplete(false);
        scheduleGoogleOAuthRedirect();
        setIsAuthenticated(false);
        setCheckingAuth(false);
      });
  }, []);

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
    const verify = async () => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      try {
        const status = await fetchAuthStatus();
        if (!status.authenticated) reportSessionExpired();
      } catch (e) {
        console.warn("Auth status check failed:", e);
      }
    };
    document.addEventListener("visibilitychange", verify);
    window.addEventListener("focus", verify);
    return () => {
      document.removeEventListener("visibilitychange", verify);
      window.removeEventListener("focus", verify);
    };
  }, [isAuthenticated, checkingAuth]);

  useEffect(() => {
    if (authRefreshGeneration === 0) return;
    initializeCsrfToken().catch((e) => console.warn("Failed to refresh CSRF:", e));
  }, [authRefreshGeneration]);

  // Core intake fields
  const [jobText, setJobText] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [location, setLocation] = useState("");
  const [language, setLanguage] = useState("");
  const [salary, setSalary] = useState("");
  const [requirements, setRequirements] = useState([]);
  const [competences, setCompetences] = useState({});
  const [hireProblem, setHireProblem] = useState("");
  const [competenceOverrides, setCompetenceOverrides] = useState({});
  const [competenceScaleConfig, setCompetenceScaleConfig] = useState(getScaleConfig);
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
  const [extractedData, setExtractedData] = useState(null);

  // Session / vendor state
  const [documentId, setDocumentId] = useState(null);
  const [vendors, setVendors] = useState([]);
  const [vendorColors, setVendorColors] = useState({});
  const [selectedVendors, setSelectedVendors] = useState(new Set());
  const [localPricingConfigured, setLocalPricingConfigured] = useState(true);
  const [localPricingModalOpen, setLocalPricingModalOpen] = useState(false);
  const [localPricingDismissChecked, setLocalPricingDismissChecked] = useState(false);
  const pendingLocalEnableActionRef = useRef(null);
  const [phaseSessionId, setPhaseSessionId] = useState(null);
  const [error, setError] = useState(null);
  const [documentSaveNotice, setDocumentSaveNotice] = useState(null);
  const [savingFinal, setSavingFinal] = useState(false);
  const [includePlanStep, setIncludePlanStep] = useState(true);
  const [loading, setLoading] = useState(false);
  const [backgroundModels, setBackgroundModels] = useState(new Set());

  // Research state
  const [selectedCompanyReport, setSelectedCompanyReport] = useState(null);
  const [selectedTopDocs, setSelectedTopDocs] = useState(null);
  const [selectedPocReport, setSelectedPocReport] = useState(null);
  const [allSearchResults, setAllSearchResults] = useState([]);
  const [selectedDocIds, setSelectedDocIds] = useState(new Set());
  const [triggerCompanyResearch, setTriggerCompanyResearch] = useState(0);
  const [triggerPocResearch, setTriggerPocResearch] = useState(0);
  const [companyExtractionResult, setCompanyExtractionResult] = useState(null);
  const [companyResearchCountdown, setCompanyResearchCountdown] = useState(null);
  const [companyAutoResearchBlocked, setCompanyAutoResearchBlocked] = useState(false);
  const [companyResearchNotification, setCompanyResearchNotification] = useState(null);

  // Translation state for job text
  const [jobTextViewLanguage, setJobTextViewLanguage] = useState("source");
  const [jobTextTranslations, setJobTextTranslations] = useState({});
  const [isTranslatingJobText, setIsTranslatingJobText] = useState(false);
  const [jobTextTranslationError, setJobTextTranslationError] = useState(null);
  const [lastJobTextSnapshot, setLastJobTextSnapshot] = useState(jobText);

  // Assembly highlight state
  const [competenceHighlightTerm, setCompetenceHighlightTerm] = useState(null);
  const [assemblyHighlightCtx, setAssemblyHighlightCtx] = useState(() => ({
    competenceCounts: {},
    finalAssemblyTextNormalized: "",
  }));

  // Scroll arrow state for competences list
  const [canScrollCompetencesUp, setCanScrollCompetencesUp] = useState(false);
  const [canScrollCompetencesDown, setCanScrollCompetencesDown] = useState(false);

  // Vendor feedback
  const [vendorFeedback, setVendorFeedback] = useState({});

  // Refs
  const latestFormSnapshotRef = useRef(null);
  const competencesScrollRef = useRef(null);

  // ─── Derived values ────────────────────────────────────────────────────────

  const hasPointOfContactData = useMemo(() => (
    Boolean(pointOfContact.name?.trim()) ||
    Boolean(pointOfContact.role?.trim()) ||
    Boolean(pointOfContact.contact_details?.trim()) ||
    Boolean(pointOfContact.notes?.trim()) ||
    Boolean(pointOfContact.company?.trim())
  ), [pointOfContact]);

  const displayedJobText = useMemo(() => {
    if (jobTextViewLanguage !== "source" && jobTextTranslations[jobTextViewLanguage]) {
      return jobTextTranslations[jobTextViewLanguage];
    }
    return jobText;
  }, [jobTextViewLanguage, jobTextTranslations, jobText]);

  // Compute effective top_docs from user's manual selection (selectedDocIds).
  // Falls back to LLM-selected selectedTopDocs if no manual selection.
  const effectiveTopDocs = useMemo(() => {
    if (selectedDocIds.size > 0 && allSearchResults.length > 0) {
      const llmScoreMap = {};
      (selectedTopDocs || []).forEach((d) => {
        const id = d.id || d.company_name;
        if (id) llmScoreMap[id] = d.score;
      });
      return allSearchResults
        .filter((d) => selectedDocIds.has(d.id || d.company_name))
        .map((d) => {
          const id = d.id || d.company_name;
          const score = llmScoreMap[id];
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

  // ─── Callbacks ─────────────────────────────────────────────────────────────

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
    // isFormSnapshotPristine is stable (useCallback with no deps that change)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
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
        hire_problem: hireProblem || "",
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
      hireProblem,
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

  const handleJobTextLanguageChange = useCallback(async (code) => {
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
      const { translation, warning } = await translateText(
        jobText,
        code,
        null,
        getLanguageTranslateParams(profileLanguages, code, translationProvider),
      );
      if (warning) setJobTextTranslationError(warning);
      setJobTextTranslations((prev) => ({ ...prev, [code]: translation }));
      setLastJobTextSnapshot(jobText);
    } catch (e) {
      setJobTextTranslationError(e.message || "Translation failed");
    } finally {
      setIsTranslatingJobText(false);
    }
  }, [jobText, jobTextTranslations, lastJobTextSnapshot, isTranslatingJobText, profileLanguages, translationProvider]);

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

  const updateCompetencesScrollState = useCallback(() => {
    const el = competencesScrollRef.current;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    setCanScrollCompetencesUp(scrollTop > 0);
    setCanScrollCompetencesDown(scrollTop < scrollHeight - clientHeight - 2);
  }, []);

  const extractData = useCallback(async () => {
    if (!jobText.trim()) {
      setExtractionError("Please enter job description first");
      return;
    }
    setExtracting(true);
    setExtractionError(null);

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

    // Fire company metadata extraction in parallel — stateless, any worker.
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
  }, [jobText, requirements, additionalUserInfo, additionalCompanyInfo]);

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

  const toggleVendor = useCallback((vendor, checked) => {
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
  }, [guardBeforeEnablingLocal]);

  const selectAll = useCallback((checked) => {
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
  }, [vendors, selectedVendors, guardBeforeEnablingLocal]);

  const resetIntake = useCallback(() => {
    setJobText("");
    setCompanyName("");
    setJobTitle("");
    setLocation("");
    setLanguage("");
    setSalary("");
    setRequirements([]);
    setCompetences({});
    setHireProblem("");
    setCompetenceOverrides({});
    setPointOfContact({ name: "", role: "", contact_details: "", notes: "", company: "" });
    setShowPointOfContact(false);
    setAdditionalUserInfo("");
    setAdditionalCompanyInfo("");
    setStructureInstructions("");
    setShowAdditionalInfo(false);
    setExtractionError(null);
    setExtractedData(null);
    setSelectedCompanyReport(null);
    setSelectedTopDocs(null);
    setSelectedPocReport(null);
    setAllSearchResults([]);
    setSelectedDocIds(new Set());
    setCompanyExtractionResult(null);
    setCompanyResearchCountdown(null);
    setCompanyAutoResearchBlocked(false);
    setCompanyResearchNotification(null);
    setJobTextViewLanguage("source");
    setJobTextTranslations({});
    setJobTextTranslationError(null);
    setDocumentId(null);
    setError(null);
  }, []);

  const saveCompetenceRatingsToProfile = useCallback(async () => {
    const ratingsToSave = buildCompetenceRatingsForProfile(
      competences,
      requirements,
      competenceOverrides,
      competenceScaleConfig
    );
    if (Object.keys(ratingsToSave).length === 0) return;
    await fetchWithHeartbeat("/api/personal-data/", {
      method: "POST",
      body: JSON.stringify({ competence_ratings: ratingsToSave }),
    });
  }, [competences, requirements, competenceOverrides, competenceScaleConfig]);

  // ─── Effects ───────────────────────────────────────────────────────────────

  // Initialize phaseSessionId + POST /api/phases/init/ on mount
  useEffect(() => {
    const sessionId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);
    setPhaseSessionId(sessionId);
    fetchWithHeartbeat("/api/phases/init/", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }).catch((e) => {
      console.error("Failed to initialize session:", e);
    });
  }, []);

  // Fetch vendors when authenticated
  useEffect(() => {
    if (!isAuthenticated) return;
    fetch("/api/vendors/", { credentials: "include" })
      .then((res) => res.json())
      .then((data) => {
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

  // Fetch personal-data settings when authenticated
  useEffect(() => {
    if (!isAuthenticated) return;
    fetch("/api/personal-data/", { credentials: "include" })
      .then((res) => res.json())
      .then((settings) => {
        if (settings.min_column_width !== undefined && settings.min_column_width !== null) {
          localStorage.setItem("minColumnWidth", settings.min_column_width.toString());
        }
        if (
          settings.default_background_models &&
          Array.isArray(settings.default_background_models) &&
          settings.default_background_models.length > 0
        ) {
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

  // Persist top_docs to session when allSearchResults changes
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

  // Persist additional_user_info/additional_company_info/hire_problem to session
  useEffect(() => {
    if (!phaseSessionId) return undefined;
    const t = setTimeout(() => {
      fetchWithHeartbeat("/api/phases/session/", {
        method: "POST",
        body: JSON.stringify({
          session_id: phaseSessionId,
          additional_user_info: additionalUserInfo || "",
          additional_company_info: additionalCompanyInfo || "",
          hire_problem: hireProblem || "",
        }),
      }).catch((e) => console.warn("Failed to persist additional job notes to session:", e));
    }, 400);
    return () => clearTimeout(t);
  }, [phaseSessionId, additionalUserInfo, additionalCompanyInfo, hireProblem]);

  // Company research countdown timer: tick every second
  useEffect(() => {
    if (companyResearchCountdown === null || companyResearchCountdown <= 0) return;
    const timer = setTimeout(() => {
      setCompanyResearchCountdown((prev) => (prev !== null && prev > 0 ? prev - 1 : null));
    }, 1000);
    return () => clearTimeout(timer);
  }, [companyResearchCountdown]);

  // Auto-trigger company research when countdown reaches 0
  useEffect(() => {
    if (companyResearchCountdown === 0 && !companyAutoResearchBlocked) {
      setCompanyResearchCountdown(null);
      setTriggerCompanyResearch(Date.now());
    }
  }, [companyResearchCountdown, companyAutoResearchBlocked]);

  // Track form snapshot
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

  // hasPointOfContact collapse effect: hide section when all fields cleared
  useEffect(() => {
    if (!hasPointOfContactData) {
      setShowPointOfContact(false);
    }
  }, [hasPointOfContactData]);

  // Reset job text translation cache when source text changes
  useEffect(() => {
    if (jobText !== lastJobTextSnapshot) {
      setJobTextTranslations({});
      setLastJobTextSnapshot(jobText);
      setJobTextViewLanguage("source");
    }
  }, [jobText, lastJobTextSnapshot]);

  // Competences scroll state observer
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
  }, [updateCompetencesScrollState, requirements.length]);

  // Vendor colors on theme change
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      setVendorColors(generateColors(vendors));
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [vendors]);

  // ─── Context value ─────────────────────────────────────────────────────────

  const value = {
    // Auth
    isAuthenticated, checkingAuth, authRefreshGeneration, setAuthRefreshGeneration,
    showSessionExpiredModal, setShowSessionExpiredModal,
    // State + setters
    jobText, setJobText,
    companyName, setCompanyName,
    jobTitle, setJobTitle,
    location, setLocation,
    language, setLanguage,
    salary, setSalary,
    requirements, setRequirements,
    competences, setCompetences,
    hireProblem, setHireProblem,
    competenceOverrides, setCompetenceOverrides,
    competenceScaleConfig, setCompetenceScaleConfig,
    pointOfContact, setPointOfContact,
    showPointOfContact, setShowPointOfContact,
    additionalUserInfo, setAdditionalUserInfo,
    additionalCompanyInfo, setAdditionalCompanyInfo,
    structureInstructions, setStructureInstructions,
    showAdditionalInfo, setShowAdditionalInfo,
    extracting, setExtracting,
    extractionError, setExtractionError,
    extractedData, setExtractedData,
    documentId, setDocumentId,
    vendors, setVendors,
    vendorColors, setVendorColors,
    selectedVendors, setSelectedVendors,
    localPricingConfigured, setLocalPricingConfigured,
    localPricingModalOpen, setLocalPricingModalOpen,
    localPricingDismissChecked, setLocalPricingDismissChecked,
    pendingLocalEnableActionRef,
    phaseSessionId, setPhaseSessionId,
    error, setError,
    documentSaveNotice, setDocumentSaveNotice,
    savingFinal, setSavingFinal,
    includePlanStep, setIncludePlanStep,
    loading, setLoading,
    backgroundModels, setBackgroundModels,
    // Research
    selectedCompanyReport, setSelectedCompanyReport,
    selectedTopDocs, setSelectedTopDocs,
    selectedPocReport, setSelectedPocReport,
    allSearchResults, setAllSearchResults,
    selectedDocIds, setSelectedDocIds,
    triggerCompanyResearch, setTriggerCompanyResearch,
    triggerPocResearch, setTriggerPocResearch,
    companyExtractionResult, setCompanyExtractionResult,
    companyResearchCountdown, setCompanyResearchCountdown,
    companyAutoResearchBlocked, setCompanyAutoResearchBlocked,
    companyResearchNotification, setCompanyResearchNotification,
    // Translation
    jobTextViewLanguage, setJobTextViewLanguage,
    jobTextTranslations, setJobTextTranslations,
    isTranslatingJobText, setIsTranslatingJobText,
    jobTextTranslationError, setJobTextTranslationError,
    lastJobTextSnapshot, setLastJobTextSnapshot,
    // Assembly highlight
    competenceHighlightTerm, setCompetenceHighlightTerm,
    assemblyHighlightCtx, setAssemblyHighlightCtx,
    // Scroll arrows
    canScrollCompetencesUp, setCanScrollCompetencesUp,
    canScrollCompetencesDown, setCanScrollCompetencesDown,
    // Vendor feedback
    vendorFeedback, setVendorFeedback,
    // Refs
    latestFormSnapshotRef,
    competencesScrollRef,
    // Derived values
    hasPointOfContactData,
    displayedJobText,
    effectiveTopDocs,
    jobIntakeTopDocsForSession,
    autocompleteContextProps,
    hasUnsavedComposeInput,
    // Callbacks
    buildJobSessionPayload,
    ensurePhaseSessionReady,
    handleJobTextLanguageChange,
    handleAssemblyHighlightCtx,
    handleCompetenceTermClick,
    isFormSnapshotPristine,
    updateCompetencesScrollState,
    extractData,
    guardBeforeEnablingLocal,
    handleLocalPricingModalContinue,
    handleLocalPricingModalCancel,
    toggleVendor,
    selectAll,
    resetIntake,
    saveCompetenceRatingsToProfile,
  };

  return (
    <JobSessionContext.Provider value={value}>
      {children}
    </JobSessionContext.Provider>
  );
}
