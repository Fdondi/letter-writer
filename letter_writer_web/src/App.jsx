import React, { useState, useEffect } from "react";
import ModelSelector from "./components/ModelSelector";
import LetterTabs from "./components/LetterTabs";
import StyleInstructionsBlade from "./components/StyleInstructionsBlade";
import PhaseFlow from "./components/PhaseFlow";
import DocumentsPage from "./components/DocumentsPage";
import { splitIntoParagraphs } from "./utils/split";

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
  const [phaseState, setPhaseState] = useState({});
  const [phaseEdits, setPhaseEdits] = useState({});
  const [phaseErrors, setPhaseErrors] = useState({});
  const [savingFinal, setSavingFinal] = useState(false);
  const [activeTab, setActiveTab] = useState("compose"); // "compose" | "documents"
  const [assemblyVisible, setAssemblyVisible] = useState(true); // when in assembly stage, show assembly or phases
  const [extractedData, setExtractedData] = useState(null); // Track extracted data to detect modifications

  // Update colors when system theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      setVendorColors(generateColors(vendors));
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [vendors]);

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

  const retryVendor = async (vendor) => {
    setFailedVendors((prev) => {
      const next = { ...prev };
      delete next[vendor];
      return next;
    });
    try {
      const res = await fetch(`/api/phases/background/${vendor}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: phaseSessionId,
        }),
      });

      if (!res.ok) {
        let detail = `Failed to restart background for ${vendor}`;
        try {
          const text = await res.text();
          try {
            const json = JSON.parse(text);
            detail = json.detail || json.message || text;
          } catch {
            detail = text || detail;
          }
        } catch (e) {
          detail = `HTTP ${res.status}: ${res.statusText}`;
        }
        throw new Error(detail);
      }

      const data = await res.json();
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }

      // Background response now returns data directly (no vendors wrapper)
      const vendorData = data;
      setPhaseSessions((prev) => ({ ...prev, [vendor]: phaseSessionId }));
      setPhaseState((prev) => ({
        ...prev,
        [vendor]: {
          background: { data: vendorData, approved: false },
          draft: { data: null, approved: false },
          refine: { data: null, approved: false },
          cost: vendorData.cost || 0,
        },
      }));
      setPhaseEdits((prev) => ({
        ...prev,
        [vendor]: {
          background: {
            company_report: vendorData.company_report || "",
          },
          draft: { draft_letter: "" },
          refine: { draft_letter: "" },
        },
      }));
      setPhaseErrors((prev) => ({ ...prev, [vendor]: null }));
      setUiStage("phases");
      setShowInput(false);
    } catch (e) {
      console.error("Retry vendor error", e);
      const errorMessage = extractErrorMessage(e);
      setFailedVendors((prev) => ({ ...prev, [vendor]: errorMessage }));
      setPhaseErrors((prev) => ({ ...prev, [vendor]: errorMessage }));
    }
  };

  const updatePhaseEdit = (vendor, phase, field, value) => {
    setPhaseEdits((prev) => ({
      ...prev,
      [vendor]: {
        ...(prev[vendor] || {}),
        [phase]: {
          ...(prev[vendor]?.[phase] || {}),
          [field]: value,
        },
      },
    }));
    
    // If user manually edits a field, clear any error for this vendor
    // The user's edited data is the data to use - no synthetic data needed
    if ((phase === "background" && field === "company_report") || 
        (phase === "refine" && field === "draft_letter")) {
      if (value?.trim()) {
        setPhaseErrors((prev) => {
          const next = { ...prev };
          delete next[vendor];
          return next;
        });
      }
    }
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
      const res = await fetch(`/api/phases/background/${vendor}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: phaseSessionId,
        }),
      });
      if (!res.ok) {
        let detail = "Failed to start background phase";
        try {
          const text = await res.text();
          try {
            const json = JSON.parse(text);
            detail = json.detail || json.message || text;
          } catch {
            detail = text || detail;
          }
        } catch (e) {
          detail = `HTTP ${res.status}: ${res.statusText}`;
        }
        throw new Error(detail);
      }
      const data = await res.json();
      // Background response now returns data directly (no vendors wrapper)
      const vendorData = data;

      setPhaseSessions((prev) => ({ ...prev, [vendor]: phaseSessionId }));
      setPhaseState((prev) => ({
        ...prev,
        [vendor]: {
          background: { data: vendorData, approved: false },
          refine: { data: null, approved: false },
          cost: vendorData.cost || 0,
        },
      }));
      setPhaseEdits((prev) => ({
        ...prev,
        [vendor]: {
          background: {
            company_report: vendorData.company_report || "",
          },
          refine: { draft_letter: "" },
        },
      }));
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }
    } catch (e) {
      console.error("Background phase error", e);
      const errorMessage = extractErrorMessage(e);
      setPhaseErrors((prev) => ({ ...prev, [vendor]: errorMessage }));
    } finally {
      setLoadingVendors((prev) => {
        const next = new Set(prev);
        next.delete(vendor);
        return next;
      });
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
    setPhaseState({});
    setPhaseEdits({});
    setPhaseErrors({});
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
          const res = await fetch(`/api/phases/background/${vendor}/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: initialSessionId,
            }),
          });
          if (!res.ok) {
            const detail = await res.text();
            throw new Error(detail || `Failed to start background for ${vendor}`);
          }
          const data = await res.json();
          // Background response now returns data directly (no vendors wrapper)
          const vendorData = data;
          
          // Update state for this vendor immediately on success
          setPhaseSessions((prev) => ({ ...prev, [vendor]: initialSessionId }));
          setPhaseState((prev) => ({
            ...prev,
            [vendor]: {
              background: { data: vendorData, approved: false },
              refine: { data: null, approved: false },
              cost: vendorData.cost || 0,
            },
          }));
          setPhaseEdits((prev) => ({
            ...prev,
            [vendor]: {
              background: {
                company_report: vendorData.company_report || "",
              },
              refine: { draft_letter: "" },
            },
          }));
          
          // Clear any previous error for this vendor
          setPhaseErrors((prev) => {
            const next = { ...prev };
            delete next[vendor];
            return next;
          });
          
          // Set session ID from first successful response
          setPhaseSessionId((prev) => prev || initialSessionId);
        } catch (e) {
          // Update error state immediately for this vendor
          const errorMessage = extractErrorMessage(e);
          setPhaseErrors((prev) => ({ ...prev, [vendor]: errorMessage }));
          console.error(`Background phase error for ${vendor}:`, e);
        }
      })();
    });
    
    // Set initial session ID immediately (will be updated by first successful response)
    setPhaseSessionId(initialSessionId);
    setLoading(false);
  };

  const approvePhase = async (phase, vendor) => {
    if (phase === "background") {
      setPhaseErrors((prev) => ({ ...prev, [vendor]: null }));
      const edits = phaseEdits[vendor]?.background || {};
      const sessionId = phaseSessions[vendor] || phaseSessionId;

      try {
        const res = await fetch(`/api/phases/draft/${vendor}/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            // background is user-editable; always send current edits to override cached
            company_report: edits.company_report,
          }),
        });
        if (!res.ok) {
          let detail = "Failed to generate draft";
          try {
            const text = await res.text();
            // Try to parse as JSON first
            try {
              const json = JSON.parse(text);
              detail = json.detail || json.message || text;
            } catch {
              // Not JSON, use as-is
              detail = text || detail;
            }
          } catch (e) {
            // Failed to read response body
            detail = `HTTP ${res.status}: ${res.statusText}`;
          }
          throw new Error(detail);
        }
        const data = await res.json();

        setPhaseState((prev) => ({
          ...prev,
          [vendor]: {
            ...(prev[vendor] || {}),
            background: { ...(prev[vendor]?.background || {}), approved: true },
            refine: { data, approved: false },
            cost: data.cost ?? prev[vendor]?.cost ?? 0,
          },
        }));

        setPhaseEdits((prev) => ({
          ...prev,
          [vendor]: {
            ...(prev[vendor] || {}),
            background: {
              ...(prev[vendor]?.background || {}),
              company_report: edits.company_report ?? "",
            },
            refine: {
              // Initialize editable draft in the refine stage; final letter will be produced in assembly phase
              draft_letter: data.draft_letter || "",
              feedback_overrides: {},
            },
          },
        }));
      } catch (e) {
        console.error("Draft generation error", e);
        const errorMessage = extractErrorMessage(e);
        setPhaseErrors((prev) => ({ ...prev, [vendor]: errorMessage }));
      }
    } else if (phase === "refine") {
      // Get edited draft letter from phaseEdits (user edits) or fallback to state (original from draft phase)
      const editedDraft = (phaseEdits[vendor]?.refine?.draft_letter ?? "").trim();
      // Get original draft from state (set when draft phase completed)
      const originalDraft = (phaseState[vendor]?.refine?.data?.draft_letter ?? "").trim();
      // Check if user edited the draft (editedDraft exists and differs from original)
      const draftWasEdited = editedDraft !== "" && editedDraft !== originalDraft;
      
      setPhaseErrors((prev) => ({ ...prev, [vendor]: null }));
      const sessionId = phaseSessions[vendor] || phaseSessionId;
      const bg = phaseState[vendor]?.background?.data || {};
      const bgEdits = phaseEdits[vendor]?.background || {};
      const backgroundDirty =
        (bgEdits.company_report ?? "") !== (bg.company_report ?? "");
      const feedbackOverrides = phaseEdits[vendor]?.refine?.feedback_overrides || {};
      const hasFeedbackOverrides = Object.keys(feedbackOverrides).length > 0;

      try {
        const payload = {
          session_id: sessionId,
        };
        // Only send draft_letter if it was actually edited
        if (draftWasEdited) {
          payload.draft_letter = editedDraft;
        }
        // Only send background overrides if the user changed them
        if (backgroundDirty) {
          payload.company_report = bgEdits.company_report ?? "";
        }
        if (hasFeedbackOverrides) {
          payload.feedback_override = feedbackOverrides;
        }

        const res = await fetch(`/api/phases/refine/${vendor}/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          let detail = "Failed to refine letter";
          try {
            const text = await res.text();
            // Try to parse as JSON first
            try {
              const json = JSON.parse(text);
              detail = json.detail || json.message || text;
            } catch {
              // Not JSON, use as-is
              detail = text || detail;
            }
          } catch (e) {
            // Failed to read response body
            detail = `HTTP ${res.status}: ${res.statusText}`;
          }
          throw new Error(detail);
        }
        const data = await res.json();

        // Calculate refine phase cost (cost to produce final letter)
        // This is the cost added in the refine phase (draft + refine steps)
        // Refine cumulative cost is data.cost (background + draft + refine)
        // Background cost is stored in phaseState before this update
        const backgroundCost = phaseState[vendor]?.background?.data?.cost ?? 0;
        const refineCumulativeCost = data.cost ?? phaseState[vendor]?.cost ?? 0;
        const refinePhaseCost = Math.max(0, refineCumulativeCost - backgroundCost);

        let allDone = false;
        setPhaseState((prev) => {
          const next = {
            ...prev,
            [vendor]: {
              ...(prev[vendor] || {}),
              // Refine phase keeps its original data (draft_letter, feedback) - don't overwrite with final_letter
              // final_letter belongs to the assembly phase, not refine phase
              refine: { 
                ...(prev[vendor]?.refine || {}),
                approved: true 
              },
              cost: data.cost ?? prev[vendor]?.cost ?? 0,
            },
          };
          allDone = Array.from(selectedVendors).every((v) => next[v]?.refine?.approved);
          return next;
        });
        setPhaseEdits((prev) => ({
          ...prev,
          [vendor]: {
            ...(prev[vendor] || {}),
            refine: {
              // Keep only draft_letter and feedback in refine phase edits
              // final_letter belongs to assembly phase, not refine phase
              draft_letter: originalDraft, // Keep original draft, not from response
            },
          },
        }));
        const finalText = data.final_letter || editedDraft;
        setLetters((prev) => ({ ...prev, [vendor]: finalText }));
        setVendorParagraphs((prev) => ({
          ...prev,
          [vendor]: splitIntoParagraphs(finalText, vendor),
        }));
        setVendorCosts((prev) => ({
          ...prev,
          [vendor]: data.cost ?? prev[vendor]?.cost ?? 0,
        }));
        
        setVendorRefineCosts((prev) => ({
          ...prev,
          [vendor]: refinePhaseCost,
        }));

        if (allDone) {
          setUiStage("assembly");
          setShowInput(false);
          setAssemblyVisible(true);
        }
      } catch (e) {
        console.error("Refine approve error", e);
        const errorMessage = extractErrorMessage(e);
        setPhaseErrors((prev) => ({ ...prev, [vendor]: errorMessage }));
      }
    }
  };

  const approveAllPhase = async (phase) => {
    if (phase === "background") {
      // Only approve vendors that have background data ready (not just pending)
      const ready = Array.from(selectedVendors).filter(
        (v) => !(phaseState[v]?.background?.approved) && phaseState[v]?.background?.data
      );
      await Promise.all(ready.map((v) => approvePhase("background", v)));
    } else if (phase === "refine") {
      // Only approve vendors that have refine data ready
      const ready = Array.from(selectedVendors).filter(
        (v) => !phaseState[v]?.refine?.approved && phaseState[v]?.refine?.data
      );
      await Promise.all(ready.map((v) => approvePhase("refine", v)));
    }
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

  const rerunFromBackground = async (vendor) => {
    clearVendorAssembly(vendor);
    setPhaseState((prev) => ({
      ...prev,
      [vendor]: {
        ...(prev[vendor] || {}),
        refine: { data: null, approved: false },
      },
    }));
    setPhaseEdits((prev) => ({
      ...prev,
      [vendor]: {
        ...(prev[vendor] || {}),
        refine: { draft_letter: "" },
      },
    }));
    await approvePhase("background", vendor);
  };

  const resetForm = () => {
    setShowInput(true);
    setUiStage("input");
    setPhaseSessionId(null);
    setPhaseState({});
    setPhaseEdits({});
    setPhaseErrors({});
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
  const hasAssembly = vendorsList.some((v) => phaseState[v]?.refine?.approved);

  const renderCompose = () => (
    <>
      {showInput ? (
        <>
          <ModelSelector
            vendors={vendors}
            selected={selectedVendors}
            onToggle={toggleVendor}
            onSelectAll={selectAll}
          />
          <textarea
            style={{
              width: "100%",
              height: 150,
              marginTop: 10,
              backgroundColor: "var(--input-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
              padding: 8,
            }}
            placeholder="Paste job description here"
            value={jobText}
            onChange={(e) => setJobText(e.target.value)}
          />
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
            gap: 10,
            marginBottom: 10,
            position: "relative",
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
        </div>
      )}
      {error && <p style={{ color: "var(--error-text)" }}>{error}</p>}

      {!showInput && uiStage !== "assembly" && (
        <PhaseFlow
          vendorsList={vendorsList}
          phaseState={phaseState}
          phaseEdits={phaseEdits}
          errors={phaseErrors}
          onEditChange={updatePhaseEdit}
          onApprove={approvePhase}
          onApproveAll={approveAllPhase}
          onRerunFromBackground={rerunFromBackground}
          sessionId={phaseSessionId}
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
                onRetry={retryVendor}
                onAddParagraph={onAddParagraph}
                onCopyFinal={persistFinalLetter}
                savingFinal={savingFinal}
              />
            </div>
          ) : (
            <>
              <PhaseFlow
                vendorsList={vendorsList}
                phaseState={phaseState}
                phaseEdits={phaseEdits}
                errors={phaseErrors}
                onEditChange={updatePhaseEdit}
                onApprove={approvePhase}
                onApproveAll={approveAllPhase}
                onRerunFromBackground={rerunFromBackground}
                sessionId={phaseSessionId}
                companyName={companyName}
                jobTitle={jobTitle}
                location={location}
                language={language}
                salary={salary}
                requirements={requirements}
                onCompanyNameChange={setCompanyName}
                onJobTitleChange={setJobTitle}
                onLocationChange={setLocation}
                onLanguageChange={setLanguage}
                onSalaryChange={setSalary}
                onRequirementsChange={setRequirements}
                onApproveExtraction={approveExtraction}
                extractionLoading={false}
                extractionError={extractionError}
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
                onClick={() => retryVendor(vendor)}
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
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
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

      {activeTab === "compose" ? renderCompose() : <DocumentsPage />}

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

