import React, { useState, useEffect, useMemo } from "react";
import ModelSelector from "./components/ModelSelector";
import LetterTabs from "./components/LetterTabs";
import StyleInstructionsBlade from "./components/StyleInstructionsBlade";
import PhaseFlow from "./components/PhaseFlow";
import FinalReview from "./components/FinalReview";
import DocumentsPage from "./components/DocumentsPage";
import PersonalDataPage from "./components/PersonalDataPage";
import SettingsPage from "./components/SettingsPage";
import LanguageConfig from "./components/LanguageConfig";
import LanguageSelector from "./components/LanguageSelector";
import AuthButton from "./components/AuthButton";
import CostDisplay from "./components/CostDisplay";
import CostsPage from "./components/CostsPage";
import { splitIntoParagraphs } from "./utils/split";
import { fetchWithHeartbeat, retryApiCall, initializeCsrfToken, getCsrfToken } from "./utils/apiHelpers";
import { phases as phaseModules } from "./components/phases";
import { translateText } from "./utils/translate";
import { useLanguages } from "./contexts/LanguageContext";
import { createTextDiff } from "./utils/diff";

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
  // ALL hooks must be declared before any conditional returns (React rules)
  // Authentication state
  const [isAuthenticated, setIsAuthenticated] = useState(null); // null = checking, true = authenticated, false = not authenticated
  const [checkingAuth, setCheckingAuth] = useState(true); // Start checking on mount
  
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
  const [pointOfContact, setPointOfContact] = useState({
    name: "",
    role: "",
    contact_details: "",
    notes: "",
    company: "",
  });
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
  const [uiStage, setUiStage] = useState("input"); // input | phases | assembly | final_review
  const [finalReviewText, setFinalReviewText] = useState("");
  const [phaseSessionId, setPhaseSessionId] = useState(null);
  const [phaseSessions, setPhaseSessions] = useState({}); // vendor -> session_id
  const [savingFinal, setSavingFinal] = useState(false);
  const [activeTab, setActiveTab] = useState("compose"); // "compose" | "documents" | "personal-data" | "settings"
  const [assemblyVisible, setAssemblyVisible] = useState(true); // when in assembly stage, show assembly or phases
  const [extractedData, setExtractedData] = useState(null); // Track extracted data to detect modifications
  const [vendorFeedback, setVendorFeedback] = useState({}); // vendor -> { rating, comment }
  
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
  
  // Check authentication status on mount
  useEffect(() => {
    // Check authentication status immediately
    fetch("/api/auth/status/", {
      credentials: "include",
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.authenticated) {
          setIsAuthenticated(true);
          // Initialize CSRF token after authentication is confirmed
          // This ensures the token is available for subsequent API calls
          initializeCsrfToken().catch((e) => {
            console.warn("Failed to initialize CSRF token after auth:", e);
          });
        } else {
          // Not authenticated - redirect to Google OAuth login
          const returnUrl = window.location.pathname + window.location.search;
          if (returnUrl && returnUrl !== "/accounts/google/login/") {
            sessionStorage.setItem("authReturnUrl", returnUrl);
          }
          window.location.href = "/accounts/google/login/";
          setIsAuthenticated(false);
        }
        setCheckingAuth(false);
      })
      .catch((e) => {
        console.error("Failed to check auth status:", e);
        // On error, redirect to Google OAuth login
        const returnUrl = window.location.pathname + window.location.search;
        if (returnUrl && returnUrl !== "/accounts/google/login/") {
          sessionStorage.setItem("authReturnUrl", returnUrl);
        }
        window.location.href = "/accounts/google/login/";
        setIsAuthenticated(false);
        setCheckingAuth(false);
      });
  }, []);
  


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

  // Initialize CSRF token and session when component mounts
  useEffect(() => {
    // Initialize CSRF token first
    initializeCsrfToken().catch((e) => {
      console.warn("Failed to initialize CSRF token:", e);
    });
    
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
    fetch("/api/personal-data/", {
      credentials: 'include',
    })
      .then((res) => res.json())
      .then((settings) => {
        // Load minimum column width
        if (settings.min_column_width !== undefined && settings.min_column_width !== null) {
          localStorage.setItem("minColumnWidth", settings.min_column_width.toString());
        }
      })
      .catch((e) => {
        console.warn("Failed to load settings:", e);
      });
  }, []);

  // Fetch vendors on mount (GET request, no CSRF header needed)
  useEffect(() => {
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
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Note: We no longer need to reload when switching tabs since SettingsPage
  // now updates the shared state directly when saving

  // NOW we can do conditional returns (after all hooks are declared)
  
  // While checking authentication or if not authenticated, show loading/login
  // Only render main app content if authenticated
  if (checkingAuth) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          minHeight: "100vh",
          backgroundColor: "var(--bg-color)",
          color: "var(--text-color)",
        }}
      >
        <div>Checking authentication...</div>
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
          <h1 style={{ marginTop: 0, marginBottom: "10px", fontSize: "24px", fontWeight: 600 }}>
            Letter Writer
          </h1>
          <p style={{ marginBottom: "30px", color: "var(--text-color)", opacity: 0.8 }}>
            Sign in to continue
          </p>
          <button
            onClick={() => {
              window.location.href = "/accounts/google/login/";
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
      const result = await fetchWithHeartbeat("/api/extract/", {
        method: "POST",
        body: JSON.stringify({ 
          job_text: jobText,
          session_id: sessionId,
        }),
      });
      const data = result.data;
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
      // Only update point of contact if extraction found it, otherwise preserve manual input
      if (extracted.point_of_contact) {
        setPointOfContact({
          name: extracted.point_of_contact.name || "",
          role: extracted.point_of_contact.role || "",
          contact_details: extracted.point_of_contact.contact_details || "",
          notes: extracted.point_of_contact.notes || "",
          company: extracted.point_of_contact.company || "",
        });
      }
      // If no point_of_contact in extraction, keep existing manual input (don't clear it)
      // Store extracted data to detect if user modified it later
      // For point_of_contact, use extracted value if present, otherwise use current state (preserves manual input)
      const currentPoc = (pointOfContact.name || pointOfContact.role || pointOfContact.contact_details || pointOfContact.notes || pointOfContact.company) ? pointOfContact : null;
      setExtractedData({
        company_name: extracted.company_name || companyName,
        job_title: extracted.job_title || jobTitle,
        location: extracted.location || location,
        language: extracted.language || language,
        salary: extracted.salary || salary,
        requirements: extracted.requirements || requirements,
        point_of_contact: extracted.point_of_contact || currentPoc,
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
      const result = await fetchWithHeartbeat(url, {
        method,
        body: JSON.stringify(payload),
      });
      const data = result.data;
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
            requirements: currentExtraction.requirements,
            point_of_contact: currentExtraction.point_of_contact,
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
    if (!jobTitle.trim()) {
      setError("Job title is required");
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
    // Track if we're creating a new session (phaseSessionId was null)
    const isNewSession = !phaseSessionId;
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

    // Check if data was modified after extraction
    const currentData = {
      company_name: companyName,
      job_title: jobTitle,
      location: location,
      language: language,
      salary: salary,
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
      job_text: jobText,
      point_of_contact: (pointOfContact.name || pointOfContact.role || pointOfContact.contact_details || pointOfContact.notes || pointOfContact.company) ? pointOfContact : null,
    };
    const dataModified = !extractedData || 
      extractedData.company_name !== currentData.company_name ||
      extractedData.job_title !== currentData.job_title ||
      extractedData.location !== currentData.location ||
      extractedData.language !== currentData.language ||
      extractedData.salary !== currentData.salary ||
      JSON.stringify(extractedData.requirements) !== JSON.stringify(currentData.requirements) ||
      extractedData.job_text !== currentData.job_text ||
      JSON.stringify(extractedData.point_of_contact || null) !== JSON.stringify(currentData.point_of_contact);

    // Update common session data if:
    // - This is a new session (e.g., after clicking "Back to Input"), OR
    // - No extraction was called (extractedData is null), OR
    // - User modified data after extraction
    // Wait for it to complete before starting background phases
    // Call session endpoint if:
    // 1. This is a new session (needs to be populated with data), OR
    // 2. Data was modified after extraction, OR
    // 3. No extraction was called (user manually input data)
    const shouldUpdateSession = isNewSession || dataModified || !extractedData;
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
          point_of_contact: (pointOfContact.name || pointOfContact.role || pointOfContact.contact_details || pointOfContact.notes || pointOfContact.company) ? pointOfContact : null,
        };
        
        await fetchWithHeartbeat("/api/phases/session/", {
          method: "POST",
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
        
        // Update current phase shelf to reset base state (approval "blesses" the edits)
        const currentBackground = phaseRegistryRef.current?.find(p => p.phase === "background");
        const currentData = currentBackground?.cardData[vendor] || {};
        populatePhaseShelf("background", vendor, { ...currentData, ...edits });

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

        // Update current phase shelf to reset base state (approval "blesses" the edits)
        const currentRefine = phaseRegistryRef.current?.find(p => p.phase === "refine");
        const currentData = currentRefine?.cardData[vendor] || {};
        const updatedRefineData = { ...currentData, ...edits };
        // If we have feedback overrides, merge them into the base feedback
        if (edits.feedback_overrides) {
          updatedRefineData.feedback = {
            ...(currentData.feedback || {}),
            ...edits.feedback_overrides
          };
        }
        populatePhaseShelf("refine", vendor, updatedRefineData);
        
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

  const resetForm = async () => {
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

  const vendorsList = Array.from(selectedVendors);
  const toggleX = "40%"; // horizontal placement for phases/assembly toggles
  // Check if we have any letters (indicates at least one refine phase completed)
  const hasAssembly = vendorsList.some((v) => letters[v]);

  const handleFinalize = (text) => {
    setFinalReviewText(text);
    setUiStage("final_review");
  };

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
            {/* Left Column */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
            </div>
            {/* Right Column */}
            <div style={{ display: "flex", flexDirection: "column", gap: 10, height: "100%" }}>
              <div>
                <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                  Company Name
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
              <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                  Key Competences
                </label>
                <textarea
                  value={Array.isArray(requirements) ? requirements.join("\n") : requirements}
                  onChange={(e) => {
                    const lines = e.target.value.split("\n").map((l) => l.trim()).filter(Boolean);
                    setRequirements(lines);
                  }}
                  style={{
                    width: "100%",
                    flex: 1,
                    padding: 8,
                    backgroundColor: "var(--input-bg)",
                    color: "var(--text-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "4px",
                    resize: "vertical",
                  }}
                  placeholder="One competence per line"
                />
              </div>
            </div>
          </div>

          {/* Point of Contact Section - Always visible */}
          <div style={{ marginTop: 20, padding: 15, backgroundColor: "var(--input-bg)", borderRadius: "8px", border: "1px solid var(--border-color)" }}>
            <h3 style={{ marginTop: 0, marginBottom: 12, fontSize: "16px", fontWeight: 600 }}>
              Point of Contact
            </h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                  Name
                </label>
                <input
                  type="text"
                  value={pointOfContact.name}
                  onChange={(e) => setPointOfContact({ ...pointOfContact, name: e.target.value })}
                  style={{
                    width: "100%",
                    padding: 8,
                    backgroundColor: "var(--input-bg)",
                    color: "var(--text-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "4px",
                  }}
                  placeholder="Contact name"
                />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                  Role
                </label>
                <input
                  type="text"
                  value={pointOfContact.role}
                  onChange={(e) => setPointOfContact({ ...pointOfContact, role: e.target.value })}
                  style={{
                    width: "100%",
                    padding: 8,
                    backgroundColor: "var(--input-bg)",
                    color: "var(--text-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "4px",
                  }}
                  placeholder="Role in company"
                />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                  Contact Details
                </label>
                <input
                  type="text"
                  value={pointOfContact.contact_details}
                  onChange={(e) => setPointOfContact({ ...pointOfContact, contact_details: e.target.value })}
                  style={{
                    width: "100%",
                    padding: 8,
                    backgroundColor: "var(--input-bg)",
                    color: "var(--text-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "4px",
                  }}
                  placeholder="Email, phone, etc."
                />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                  Company (if separate intermediary)
                </label>
                <input
                  type="text"
                  value={pointOfContact.company}
                  onChange={(e) => setPointOfContact({ ...pointOfContact, company: e.target.value })}
                  style={{
                    width: "100%",
                    padding: 8,
                    backgroundColor: "var(--input-bg)",
                    color: "var(--text-color)",
                    border: "1px solid var(--border-color)",
                    borderRadius: "4px",
                  }}
                  placeholder="Intermediary company (e.g., recruiting agency)"
                />
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>
                Notes
              </label>
              <textarea
                value={pointOfContact.notes}
                onChange={(e) => setPointOfContact({ ...pointOfContact, notes: e.target.value })}
                style={{
                  width: "100%",
                  height: 60,
                  padding: 8,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
                placeholder="Notes about contact or how to reach them"
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
          <div style={{ marginLeft: "auto" }}>
            <LanguageConfig />
          </div>
        </div>
      )}
      {error && <p style={{ color: "var(--error-text)" }}>{error}</p>}

      {!showInput && (
        <>
          <div style={{ display: ((uiStage === "assembly" && assemblyVisible) || uiStage === "final_review") ? "none" : "block" }}>
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
          </div>

          {/* Keep LetterTabs mounted to preserve translation state */}
          {(uiStage === "assembly" || uiStage === "final_review") && (
            <div style={{ 
              position: "relative", 
              paddingTop: 4,
              display: (uiStage === "assembly" && assemblyVisible) ? "block" : "none"
            }}>
              <LetterTabs
                vendorsList={vendorsList}
                vendorParagraphs={vendorParagraphs}
                vendorCosts={vendorCosts}
                vendorRefineCosts={vendorRefineCosts}
                finalParagraphs={finalParagraphs}
                setFinalParagraphs={setFinalParagraphs}
                originalText={jobText}
                requirements={requirements}
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
                onFinalize={handleFinalize}
                savingFinal={savingFinal}
                vendorFeedback={vendorFeedback}
                setVendorFeedback={setVendorFeedback}
              />
            </div>
          )}

          {uiStage === "final_review" && (
             <FinalReview
                initialText={finalReviewText}
                jobText={jobText}
                requirements={requirements}
                onSaveAndCopy={persistFinalLetter}
                onBack={() => setUiStage("assembly")}
                saving={savingFinal}
             />
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
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
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
              Your CV
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
              Previous Examples
            </button>
            <button
              onClick={() => setActiveTab("settings")}
              style={{
                padding: "8px 12px",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                backgroundColor:
                  activeTab === "settings" ? "#3b82f6" : "var(--button-bg)",
                color: activeTab === "settings" ? "white" : "var(--button-text)",
                cursor: "pointer",
                fontSize: "14px",
              }}
            >
              Settings
            </button>

            <CostDisplay onNavigate={() => setActiveTab("costs")} />
            <AuthButton />
          </div>
        </div>

      </div>

      {activeTab === "compose"
        ? renderCompose()
        : activeTab === "documents"
        ? <DocumentsPage />
        : activeTab === "settings"
        ? <SettingsPage 
            vendors={vendors} 
            selectedVendors={selectedVendors}
            setSelectedVendors={setSelectedVendors}
          />
        : activeTab === "costs"
        ? <CostsPage />
        : <PersonalDataPage />}

      {/* Floating toggle to assembly while still in phases (after first refinement ready) */}
      {!showInput && uiStage !== "assembly" && uiStage !== "final_review" && hasAssembly && (
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
              setUiStage("assembly");
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
      {!showInput && uiStage === "assembly" && !assemblyVisible && (
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

