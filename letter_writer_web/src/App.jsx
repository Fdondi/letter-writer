import React, { useState, useEffect, useMemo } from "react";
import ModelSelector from "./components/ModelSelector";
import LetterTabs from "./components/LetterTabs";
import StyleInstructionsBlade from "./components/StyleInstructionsBlade";
import PhaseFlow from "./components/PhaseFlow";
import DocumentsPage from "./components/DocumentsPage";
import PersonalDataPage from "./components/PersonalDataPage";
import LanguageConfig from "./components/LanguageConfig";
import LanguageSelector from "./components/LanguageSelector";
import { splitIntoParagraphs } from "./utils/split";
import { fetchWithHeartbeat, retryApiCall } from "./utils/apiHelpers";
import { phases as phaseModules } from "./components/phases";
import { translateText } from "./utils/translate";
import { useLanguages } from "./contexts/LanguageContext";

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

export default function App() {
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
  const [extracting, setExtracting] = useState(false);
  const [extractionError, setExtractionError] = useState(null);
  const [documentId, setDocumentId] = useState(null);
  const [selectedVendors, setSelectedVendors] = useState(new Set());
  const [letters, setLetters] = useState({}); // vendor -> text
  const [vendorCosts, setVendorCosts] = useState({}); // vendor -> cost (total cumulative)
  const [vendorRefineCosts, setVendorRefineCosts] = useState({}); // vendor -> refine phase cost (final letter cost)
  const [failedVendors, setFailedVendors] = useState({}); // vendor -> error message
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showInput, setShowInput] = useState(true);
  const [showStyleBlade, setShowStyleBlade] = useState(false);
  const [uiStage, setUiStage] = useState("input"); // input | phases | assembly
  const [phaseSessionId, setPhaseSessionId] = useState(null);
  const [phaseSessions, setPhaseSessions] = useState({}); // vendor -> session_id
  const [savingFinal, setSavingFinal] = useState(false);
  const [activeTab, setActiveTab] = useState("compose"); // "compose" | "documents" | "personal-data"
  const [assemblyVisible, setAssemblyVisible] = useState(true); // when in assembly stage, show assembly or phases
  const [extractedData, setExtractedData] = useState(null); // Track extracted data to detect modifications
  
  // Translation state for job text
  const { enabledLanguages } = useLanguages();
  const [jobTextViewLanguage, setJobTextViewLanguage] = useState("source");
  const [jobTextTranslations, setJobTextTranslations] = useState({});
  const [isTranslatingJobText, setIsTranslatingJobText] = useState(false);
  const [jobTextTranslationError, setJobTextTranslationError] = useState(null);
  const [lastJobTextSnapshot, setLastJobTextSnapshot] = useState(jobText);
  
  // Registry of phase objects from PhaseFlow
  const phaseRegistryRef = React.useRef(null);
  const [, setPhaseRegistryTrigger] = useState(0); // For re-rendering when registry changes

  // Helper function to get current state for session restoration
  const getStateForRestore = React.useCallback(() => {
    return {
      jobText: jobText || "",
      cvText: "", // Not used in this app, but required by restore endpoint
      extractedData: extractedData,
      phaseRegistry: phaseRegistryRef.current,
    };
  }, [jobText, extractedData]);

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

  // Get displayed job text (translated or original)
  const displayedJobText = useMemo(() => {
    if (jobTextViewLanguage !== "source" && jobTextTranslations[jobTextViewLanguage]) {
      return jobTextTranslations[jobTextViewLanguage];
    }
    return jobText;
  }, [jobTextViewLanguage, jobTextTranslations, jobText]);

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

  // Helper to populate the "shelf" in PhaseFlow for a specific phase/vendor
  const populatePhaseShelf = (phaseName, vendor, data) => {
    if (phaseRegistryRef.current) {
      const phase = phaseRegistryRef.current.find(p => p.phase === phaseName);
      if (phase) {
        phase.cardData[vendor] = data;
        setPhaseRegistryTrigger(prev => prev + 1);
      }
    }
  };

  // Initialize session when component mounts
  useEffect(() => {
    const sessionId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);
    setPhaseSessionId(sessionId);
    
    // Initialize session on backend
    fetch("/api/phases/init/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    }).catch((e) => {
      console.error("Failed to initialize session:", e);
      // Continue anyway - session will be created when needed
    });
  }, []);

  // Fetch vendors on mount
  useEffect(() => {
    fetch("/api/vendors/")
      .then((res) => res.json())
      .then((data) => {
        const vendorList = data.vendors || [];
        setVendors(vendorList);
        setSelectedVendors(new Set(vendorList));
        setVendorColors(generateColors(vendorList));
      })
      .catch((e) => setError(String(e)));
  }, []);

  const toggleVendor = (vendor, checked) => {
    setSelectedVendors((prev) => {
      const next = new Set(prev);
      checked ? next.add(vendor) : next.delete(vendor);
      return next;
    });
  };

  const selectAll = (checked) => {
    setSelectedVendors(checked ? new Set(vendors) : new Set());
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
    
    try {
      const res = await fetch("/api/extract/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          job_text: jobText,
          session_id: sessionId,
        }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || "Failed to extract data");
      }
      const data = await res.json();
      const extracted = data.extraction || {};
      if (extracted.company_name) setCompanyName(extracted.company_name);
      if (extracted.job_title) setJobTitle(extracted.job_title);
      if (extracted.location) setLocation(extracted.location);
      if (extracted.language) setLanguage(extracted.language);
      if (extracted.salary) setSalary(extracted.salary);
      if (extracted.requirements) {
        const reqs = Array.isArray(extracted.requirements)
          ? extracted.requirements
          : [extracted.requirements];
        setRequirements(reqs.filter(Boolean));
      }
      // Store extracted data to detect if user modified it later
      setExtractedData({
        company_name: extracted.company_name || companyName,
        job_title: extracted.job_title || jobTitle,
        location: extracted.location || location,
        language: extracted.language || language,
        salary: extracted.salary || salary,
        requirements: extracted.requirements || requirements,
        job_text: jobText,
      });
    } catch (e) {
      console.error("Extract error", e);
      setExtractionError(e?.message || String(e));
    } finally {
      setExtracting(false);
    }
  };

  // Helper function to extract user-friendly error messages
  const extractErrorMessage = (error) => {
    if (!error) return "Unknown error";
    
    // If it's already a string, try to parse it
    const errorStr = typeof error === 'string' ? error : (error.message || String(error));
    
    // Handle NetworkError (TypeError)
    if (error instanceof TypeError && error.message.includes('fetch')) {
      return "Network error: Unable to connect to server. Please check your connection.";
    }
    
    // Try to extract JSON detail from error string
    try {
      // Handle "API error occurred: Status XXX. Body: {...}" format
      if (errorStr.includes('API error occurred:')) {
        const bodyMatch = errorStr.match(/Body:\s*({[\s\S]*})/);
        if (bodyMatch) {
          const body = JSON.parse(bodyMatch[1]);
          return body.detail || body.message || errorStr;
        }
        // Try to extract detail directly
        const detailMatch = errorStr.match(/"detail"\s*:\s*"([^"]+)"/);
        if (detailMatch) {
          return detailMatch[1];
        }
      }
      
      // Try to parse as JSON directly
      const parsed = JSON.parse(errorStr);
      if (parsed.detail) return parsed.detail;
      if (parsed.message) return parsed.message;
    } catch (e) {
      // Not JSON, continue with original string
    }
    
    // Return the error string, but clean up common patterns
    return errorStr.replace(/^Error:\s*/, '').trim() || "Unknown error";
  };

  const persistFinalLetter = async (finalText) => {
    if (!finalText || !companyName || !jobText) return;
    const requirementsList = Array.isArray(requirements) ? requirements : requirements ? [requirements] : [];
    const aiLetters = Object.entries(letters).map(([vendor, text]) => ({
      vendor,
      text: text || "",
      cost: vendorCosts[vendor] ?? null,
    }));
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
    };
    const url = documentId ? `/api/documents/${documentId}/` : "/api/documents/";
    const method = documentId ? "PUT" : "POST";
    try {
      setSavingFinal(true);
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }
    } catch (e) {
      setError(`Failed to save letter: ${e.message || e}`);
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
          setUiStage,
          setShowInput,
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
    };
    const extractionEdited = extractedData && (
      extractedData.company_name !== currentExtraction.company_name ||
      extractedData.job_title !== currentExtraction.job_title ||
      extractedData.location !== currentExtraction.location ||
      extractedData.language !== currentExtraction.language ||
      extractedData.salary !== currentExtraction.salary ||
      JSON.stringify(extractedData.requirements) !== JSON.stringify(currentExtraction.requirements)
    );

    setError(null);

    try {
      // If extraction was edited, save it to session first
      if (extractionEdited) {
        await fetch("/api/phases/session/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: phaseSessionId,
            job_text: jobText,
            company_name: companyName,
            job_title: jobTitle,
            location: location,
            language: language,
            salary: salary,
            requirements: currentExtraction.requirements,
          }),
        });
      }
      
      // Background phase only needs session_id - it reads all data from the session
      const result = await fetchWithHeartbeat(
        `/api/phases/background/${vendor}/`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: phaseSessionId,
          }),
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
      // Background response now returns data directly (no vendors wrapper)
      const vendorData = data;

      // Populate the background phase shelf in PhaseFlow
      populatePhaseShelf("background", vendor, vendorData);

      setPhaseSessions((prev) => ({ ...prev, [vendor]: phaseSessionId }));
      // phaseState, phaseEdits removed - cards own their state
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }
    } catch (e) {
      console.error("Background phase error", e);
      // Cards now own their error state
    }
  };

  const handleSubmit = async () => {
    if (!companyName.trim() || !jobTitle.trim()) {
      setError("Company name and job title are required");
      return;
    }
    
    setLoading(true);
    setError(null);
    setLetters({});
    setVendorCosts({});
    setFailedVendors({});
    setVendorParagraphs({});
    setFinalParagraphs([]);
    setDocumentId(null);
    setShowInput(false);
    setUiStage("phases");
    // phaseState, phaseEdits, phaseErrors removed - cards own their state
    setPhaseSessions({});
    
    const vendorList = Array.from(selectedVendors);
    // Session should already be initialized on mount, but ensure it exists
    const initialSessionId = phaseSessionId || (
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2)
    );
    if (!phaseSessionId) {
      setPhaseSessionId(initialSessionId);
      // Initialize session if not already done
      try {
        await fetch("/api/phases/init/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: initialSessionId }),
        });
      } catch (e) {
        console.error("Failed to initialize session:", e);
      }
    }

    // Check if data was modified after extraction
    const currentData = {
      company_name: companyName,
      job_title: jobTitle,
      location: location,
      language: language,
      salary: salary,
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
      job_text: jobText,
    };
    const dataModified = !extractedData || 
      extractedData.company_name !== currentData.company_name ||
      extractedData.job_title !== currentData.job_title ||
      extractedData.location !== currentData.location ||
      extractedData.language !== currentData.language ||
      extractedData.salary !== currentData.salary ||
      JSON.stringify(extractedData.requirements) !== JSON.stringify(currentData.requirements) ||
      extractedData.job_text !== currentData.job_text;

    // Update common session data if:
    // - No extraction was called (extractedData is null), OR
    // - User modified data after extraction
    // Wait for it to complete before starting background phases
    // Call session endpoint if:
    // 1. Data was modified after extraction, OR
    // 2. No extraction was called (user manually input data)
    const shouldUpdateSession = dataModified || !extractedData;
    if (shouldUpdateSession) {
      try {
        // Send individual fields that the user sees in the webpage
        const sessionPayload = {
          session_id: initialSessionId,
          job_text: jobText,
          company_name: companyName,
          job_title: jobTitle,
          location: location,
          language: language,
          salary: salary,
          requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
        };
        
        await fetch("/api/phases/session/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(sessionPayload),
        });
      } catch (e) {
        console.error("Failed to update session data:", e);
        setError("Failed to update session data. Please try again.");
        setLoading(false);
        return;
      }
    }

    // Start background phase for all vendors in parallel
    // Each vendor only needs session_id - they read all data from the session
    vendorList.forEach((vendor) => {
      (async () => {
        try {
          const result = await fetchWithHeartbeat(
            `/api/phases/background/${vendor}/`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                session_id: initialSessionId,
              }),
            },
            { getState: getStateForRestore }
          );
          
          // Handle 202 Accepted (heartbeat/still processing)
          if (result.isHeartbeat) {
            // Don't throw error - request is still in progress
            return;
          }
          
          const data = result.data;
          // Background response now returns data directly (no vendors wrapper)
          const vendorData = data;
          
          // Populate the background phase shelf in PhaseFlow
          populatePhaseShelf("background", vendor, vendorData);

          // Update session for this vendor
          setPhaseSessions((prev) => ({ ...prev, [vendor]: initialSessionId }));
          // phaseState, phaseEdits, phaseErrors removed - cards own their state
          
          // Set session ID from first successful response
          setPhaseSessionId((prev) => prev || initialSessionId);
        } catch (e) {
          // Cards now own their error state
          console.error(`Background phase error for ${vendor}:`, e);
        }
      })();
    });
    
    // Set initial session ID immediately (will be updated by first successful response)
    setPhaseSessionId(initialSessionId);
    setLoading(false);
  };

  const approvePhase = async (phase, vendor, edits = {}) => {
    // Prevent duplicate calls if already approved/processing
    // Note: session tracking is a decent proxy for "is in flight" if we assume
    // that a phase session is set only once per phase. 
    // However, the best guard is the UI button being disabled.
    // We can also check if we already have the result data in the shelf to avoid re-fetching
    // unless explicitly asked (which would likely be a different function or cleared state).

    if (phase === "background") {
      const sessionId = phaseSessions[vendor] || phaseSessionId;

      try {
        const result = await fetchWithHeartbeat(
          `/api/phases/draft/${vendor}/`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: sessionId,
              company_report: edits.company_report || "",
            }),
          },
          { getState: getStateForRestore }
        );
        
        // Handle 202 Accepted (heartbeat/still processing)
        if (result.isHeartbeat) {
          return null;
        }
        
        const data = result.data;
        
        // Populate the refine phase shelf in PhaseFlow (this contains the draft and feedback)
        // Check if we already have data to avoid overwriting if a race condition occurs
        // though typically the last write wins.
        populatePhaseShelf("refine", vendor, data);

        // Return data to the caller (VendorCard) so it knows to proceed
        return data;
      } catch (e) {
        console.error("Draft generation error", e);
        const errorMessage = extractErrorMessage(e);
        throw new Error(errorMessage);
      }
    } else if (phase === "refine") {
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
          setUiStage("assembly");
          setShowInput(false);
          setAssemblyVisible(true);
        }
        
        return data;
      } catch (e) {
        console.error("Refine generation error", e);
        const errorMessage = extractErrorMessage(e);
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

  const rerunFromBackground = async (vendor, phaseName = "background") => {
    clearVendorAssembly(vendor);
    // Cards now own their state, so we just call approve
    // The card will handle clearing its own state
    await approvePhase("background", vendor, {});
  };

  const resetForm = () => {
    setShowInput(true);
    setUiStage("input");
    setPhaseSessionId(null);
    // phaseState, phaseEdits, phaseErrors removed - cards own their state
    setLetters({});
    setVendorParagraphs({});
    setFailedVendors({});
    setError(null);
    setFinalParagraphs([]);
    setDocumentId(null);
    setSavingFinal(false);
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
  };

  const vendorsList = Array.from(selectedVendors);
  const toggleX = "40%"; // horizontal placement for phases/assembly toggles
  // Check if we have any letters (indicates at least one refine phase completed)
  const hasAssembly = vendorsList.some((v) => letters[v]);

  const renderCompose = () => (
    <>
      {showInput ? (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
            <ModelSelector
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
          
          <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                Company Name *
              </label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                style={{
                  width: "100%",
                  padding: 8,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
                placeholder="Company name"
              />
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                Job Title *
              </label>
              <input
                type="text"
                value={jobTitle}
                onChange={(e) => setJobTitle(e.target.value)}
                style={{
                  width: "100%",
                  padding: 8,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
                placeholder="Job title"
              />
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                Location
              </label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                style={{
                  width: "100%",
                  padding: 8,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
                placeholder="Location"
              />
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                Language
              </label>
              <input
                type="text"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                style={{
                  width: "100%",
                  padding: 8,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
                placeholder="Language"
              />
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                Salary
              </label>
              <input
                type="text"
                value={salary}
                onChange={(e) => setSalary(e.target.value)}
                style={{
                  width: "100%",
                  padding: 8,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
                placeholder="Salary range"
              />
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                Requirements
              </label>
              <textarea
                value={Array.isArray(requirements) ? requirements.join("\n") : requirements}
                onChange={(e) => {
                  const lines = e.target.value.split("\n").map((l) => l.trim()).filter(Boolean);
                  setRequirements(lines);
                }}
                style={{
                  width: "100%",
                  height: 80,
                  padding: 8,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
                placeholder="One requirement per line"
              />
            </div>
          </div>
          
          <button
            onClick={handleSubmit}
            disabled={loading || !jobText || !companyName.trim() || !jobTitle.trim() || selectedVendors.size === 0}
            style={{
              marginTop: 20,
              padding: "10px 20px",
              backgroundColor:
                loading || !jobText || !companyName.trim() || !jobTitle.trim() || selectedVendors.size === 0
                  ? "var(--header-bg)"
                  : "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor:
                loading || !jobText || !companyName.trim() || !jobTitle.trim() || selectedVendors.size === 0
                  ? "not-allowed"
                  : "pointer",
            }}
          >
            {loading ? "Starting..." : "Start phased flow"}
          </button>
        </>
      ) : (
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
            onClick={resetForm}
            style={{
              padding: "8px 16px",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
              cursor: "pointer",
            }}
          >
            ← Back to Input
          </button>
          <LanguageConfig />
          {uiStage === "assembly" && assemblyVisible && (
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
        </div>
      )}
      {error && <p style={{ color: "var(--error-text)" }}>{error}</p>}

      {!showInput && uiStage !== "assembly" && (
        <PhaseFlow
          vendorsList={vendorsList}
          onEditChange={updatePhaseEdit}
          onApprove={approvePhase}
          onApproveAll={approveAllPhase}
          onRerunFromBackground={rerunFromBackground}
          sessionId={phaseSessionId}
          onRegisterPhases={(phases) => {
            phaseRegistryRef.current = phases;
          }}
          onPhaseComplete={(vendor, phase, data) => {
            // Handle phase completion - update parent state if needed
            if (phase === "refine" && data?.final_letter) {
              // Already handled in approvePhase
            }
          }}
        />
      )}

      {!showInput && uiStage === "assembly" && (
        <>
          {assemblyVisible ? (
            <div style={{ position: "relative", paddingTop: 4 }}>
              <LetterTabs
                vendorsList={vendorsList}
                vendorParagraphs={vendorParagraphs}
                vendorCosts={vendorCosts}
                vendorRefineCosts={vendorRefineCosts}
                finalParagraphs={finalParagraphs}
                setFinalParagraphs={setFinalParagraphs}
                originalText={jobText}
                vendorColors={vendorColors}
                failedVendors={failedVendors}
                onRetry={async (vendor) => {
                  // In assembly stage, retry refine phase
                  setFailedVendors((prev) => {
                    const next = { ...prev };
                    delete next[vendor];
                    return next;
                  });
                  try {
                    const retryFn = createRetryForPhase("refine", vendor);
                    await retryFn();
                  } catch (e) {
                    console.error("Retry error:", e);
                    const errorMessage = extractErrorMessage(e);
                    setFailedVendors((prev) => ({ ...prev, [vendor]: errorMessage }));
                  }
                }}
                onAddParagraph={onAddParagraph}
                onCopyFinal={persistFinalLetter}
                savingFinal={savingFinal}
              />
            </div>
          ) : (
            <>
              <PhaseFlow
                vendorsList={vendorsList}
                onEditChange={updatePhaseEdit}
                onApprove={approvePhase}
                onApproveAll={approveAllPhase}
                onRerunFromBackground={rerunFromBackground}
                sessionId={phaseSessionId}
                onRegisterPhases={(phases) => {
                  phaseRegistryRef.current = phases;
                }}
                onPhaseComplete={(vendor, phase, data) => {
                  // Handle phase completion - update parent state if needed
                  if (phase === "refine" && data?.final_letter) {
                    // Already handled in approvePhase
                  }
                }}
              />
            </>
          )}
        </>
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
                  // Default to background phase for failed vendors
                  // In the future, we could track which phase failed
                  setFailedVendors((prev) => {
                    const next = { ...prev };
                    delete next[vendor];
                    return next;
                  });
                  try {
                    const retryFn = createRetryForPhase("background", vendor);
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

      {/* Assembly content is shown only in uiStage === "assembly" above */}
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
      <div style={{ position: "relative", marginBottom: 12 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <h1 style={{ margin: 0, color: "var(--text-color)" }}>Letter Writer</h1>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => setActiveTab("compose")}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor: activeTab === "compose" ? "#3b82f6" : "var(--button-bg)",
                color: activeTab === "compose" ? "white" : "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Compose
            </button>
            <button
              onClick={() => setActiveTab("documents")}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor:
                  activeTab === "documents" ? "#3b82f6" : "var(--button-bg)",
                color: activeTab === "documents" ? "white" : "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Documents
            </button>
            <button
              onClick={() => setActiveTab("personal-data")}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor:
                  activeTab === "personal-data" ? "#3b82f6" : "var(--button-bg)",
                color: activeTab === "personal-data" ? "white" : "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Your data
            </button>
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
              ⚙️ Style
            </button>
          </div>
        </div>

      </div>

      {activeTab === "compose" ? renderCompose() : activeTab === "documents" ? <DocumentsPage /> : <PersonalDataPage />}

      {/* Floating toggle to assembly while still in phases (after first refinement ready) */}
      {!showInput && uiStage !== "assembly" && hasAssembly && (
        <div
          style={{
            position: "fixed",
            bottom: 16,
            left: toggleX,
            zIndex: 20,
            pointerEvents: "none",
            transform: "translateX(-50%)",
          }}
        >
          <button
            onClick={() => {
              setUiStage("assembly");
              setAssemblyVisible(true);
            }}
            style={{
              padding: "10px 14px",
              border: "1px solid var(--border-color)",
              borderRadius: "999px",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              boxShadow: "0 2px 10px rgba(0,0,0,0.18)",
              pointerEvents: "auto",
            }}
          >
            ↓ To final assembly
          </button>
        </div>
      )}

      {/* Floating toggle back to assembly when hidden (phases view) */}
      {!showInput && uiStage === "assembly" && !assemblyVisible && (
        <div
          style={{
            position: "fixed",
            bottom: 16,
            left: toggleX,
            transform: "translateX(-50%)",
            zIndex: 20,
            pointerEvents: "none",
          }}
        >
          <button
            onClick={() => setAssemblyVisible(true)}
            style={{
              padding: "10px 14px",
              border: "1px solid var(--border-color)",
              borderRadius: "999px",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              boxShadow: "0 2px 10px rgba(0,0,0,0.18)",
              pointerEvents: "auto",
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

