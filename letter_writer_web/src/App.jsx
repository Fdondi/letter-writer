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
  const [vendorCosts, setVendorCosts] = useState({}); // vendor -> cost
  const [failedVendors, setFailedVendors] = useState({}); // vendor -> error message
  const [loading, setLoading] = useState(false);
  const [loadingVendors, setLoadingVendors] = useState(new Set()); // vendors currently loading
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

  // Update colors when system theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      setVendorColors(generateColors(vendors));
    };
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [vendors]);

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
    try {
      const res = await fetch("/api/extract/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_text: jobText }),
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
    } catch (e) {
      console.error("Extract error", e);
      setExtractionError(e?.message || String(e));
    } finally {
      setExtracting(false);
    }
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
    setLoadingVendors((prev) => new Set(prev).add(vendor));
    setFailedVendors((prev) => {
      const next = { ...prev };
      delete next[vendor];
      return next;
    });
    const extractionPayload = {
      company_name: companyName,
      job_title: jobTitle,
      location: location,
      language: language,
      salary: salary,
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
    };

    try {
      const res = await fetch(`/api/phases/background/${vendor}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: phaseSessionId,
          job_text: jobText,
          extraction: extractionPayload,
        }),
      });

      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Failed to restart background for ${vendor}`);
      }

      const data = await res.json();
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }

      const vendorData = data.vendors?.[vendor] || {};
      setPhaseSessions((prev) => ({ ...prev, [vendor]: data.session_id || phaseSessionId }));
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
          refine: { final_letter: "" },
        },
      }));
      setPhaseErrors((prev) => ({ ...prev, [vendor]: null }));
      setUiStage("phases");
      setShowInput(false);
    } catch (e) {
      console.error("Retry vendor error", e);
      setFailedVendors((prev) => ({ ...prev, [vendor]: String(e) }));
      setPhaseErrors((prev) => ({ ...prev, [vendor]: String(e) }));
    } finally {
      setLoadingVendors((prev) => {
        const next = new Set(prev);
        next.delete(vendor);
        return next;
      });
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
        (phase === "refine" && field === "final_letter")) {
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
    const extractionPayload = {
      company_name: companyName,
      job_title: jobTitle,
      location: location,
      language: language,
      salary: salary,
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
    };

    setError(null);
    setLoadingVendors((prev) => new Set(prev).add(vendor));

    try {
      const res = await fetch(`/api/phases/background/${vendor}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: phaseSessionId,
          extraction: extractionPayload,
          job_text: jobText,
        }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || "Failed to start background phase");
      }
      const data = await res.json();
      const vendorData = data.vendors?.[vendor] || {};

      setPhaseSessions((prev) => ({ ...prev, [vendor]: data.session_id || phaseSessionId }));
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
          refine: { final_letter: "", draft_letter: "" },
        },
      }));
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }
    } catch (e) {
      console.error("Background phase error", e);
      const message = e?.message || String(e);
      setPhaseErrors((prev) => ({ ...prev, [vendor]: message }));
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
    setLoadingVendors(new Set());
    setDocumentId(null);
    setShowInput(false);
    setUiStage("phases");
    setPhaseState({});
    setPhaseEdits({});
    setPhaseErrors({});
    setPhaseSessions({});
    
    const vendorList = Array.from(selectedVendors);
    const initialSessionId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2);

    const extractionPayload = {
      company_name: companyName,
      job_title: jobTitle,
      location: location,
      language: language,
      salary: salary,
      requirements: Array.isArray(requirements) ? requirements : requirements ? [requirements] : [],
    };

    // Start background phase for all vendors in parallel, updating state immediately as each completes
    // Each vendor runs independently - no waiting for others
    vendorList.forEach((vendor) => {
      // Each vendor runs independently, updating state immediately on completion/failure
      (async () => {
        try {
          const res = await fetch(`/api/phases/background/${vendor}/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              session_id: initialSessionId,
              extraction: extractionPayload,
              job_text: jobText,
            }),
          });
          if (!res.ok) {
            const detail = await res.text();
            throw new Error(detail || `Failed to start background for ${vendor}`);
          }
          const data = await res.json();
          const vendorData = data.vendors?.[vendor] || {};
          
          // Update state for this vendor immediately on success
          setPhaseSessions((prev) => ({ ...prev, [vendor]: data.session_id || initialSessionId }));
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
              refine: { final_letter: "", draft_letter: "" },
            },
          }));
          
          // Clear any previous error for this vendor
          setPhaseErrors((prev) => {
            const next = { ...prev };
            delete next[vendor];
            return next;
          });
          
          // Set session ID from first successful response
          setPhaseSessionId((prev) => prev || data.session_id || initialSessionId);
          
          if (!documentId && data.document?.id) {
            setDocumentId(data.document.id);
          }
        } catch (e) {
          // Update error state immediately for this vendor
          const errorMsg = e?.message || String(e);
          setPhaseErrors((prev) => ({ ...prev, [vendor]: errorMsg }));
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
      setLoadingVendors((prev) => new Set(prev).add(vendor));
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
          const detail = await res.text();
          throw new Error(detail || "Failed to generate draft");
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
              company_report: data.company_report ?? edits.company_report ?? "",
            },
            refine: {
              // Initialize editable draft in the refine stage; final letter will be produced later
              draft_letter: data.draft_letter || "",
              final_letter: data.draft_letter || "",
              feedback_overrides: {},
            },
          },
        }));
      } catch (e) {
        console.error("Draft generation error", e);
        setPhaseErrors((prev) => ({ ...prev, [vendor]: String(e) }));
      } finally {
        setLoadingVendors((prev) => {
          const next = new Set(prev);
          next.delete(vendor);
          return next;
        });
      }
    } else if (phase === "refine") {
      const editedFinal =
        (phaseEdits[vendor]?.refine?.final_letter ??
          phaseState[vendor]?.refine?.data?.final_letter ??
          "").trim();
      setPhaseErrors((prev) => ({ ...prev, [vendor]: null }));
      setLoadingVendors((prev) => new Set(prev).add(vendor));
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
          draft_letter: editedFinal || phaseState[vendor]?.refine?.data?.draft_letter || "",
        };
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
          const detail = await res.text();
          throw new Error(detail || "Failed to refine letter");
        }
        const data = await res.json();

        let allDone = false;
        setPhaseState((prev) => {
          const next = {
            ...prev,
            [vendor]: {
              ...(prev[vendor] || {}),
              refine: { data, approved: true },
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
              final_letter: data.final_letter || editedFinal,
              draft_letter: data.draft_letter || "",
            },
          },
        }));
        const finalText = data.final_letter || editedFinal;
        setLetters((prev) => ({ ...prev, [vendor]: finalText }));
        setVendorParagraphs((prev) => ({
          ...prev,
          [vendor]: splitIntoParagraphs(finalText, vendor),
        }));
        setVendorCosts((prev) => ({
          ...prev,
          [vendor]: data.cost ?? prev[vendor]?.cost ?? 0,
        }));

        if (allDone) {
          setUiStage("assembly");
          setShowInput(false);
          setAssemblyVisible(true);
        }
      } catch (e) {
        console.error("Refine approve error", e);
        setPhaseErrors((prev) => ({ ...prev, [vendor]: String(e) }));
      } finally {
        setLoadingVendors((prev) => {
          const next = new Set(prev);
          next.delete(vendor);
          return next;
        });
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
        refine: { final_letter: "" },
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
    setLoadingVendors(new Set());
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
          loadingVendors={loadingVendors}
          errors={phaseErrors}
          onEditChange={updatePhaseEdit}
          onApprove={approvePhase}
          onApproveAll={approveAllPhase}
          onRerunFromBackground={rerunFromBackground}
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
                finalParagraphs={finalParagraphs}
                setFinalParagraphs={setFinalParagraphs}
                originalText={jobText}
                vendorColors={vendorColors}
                failedVendors={failedVendors}
                loadingVendors={loadingVendors}
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
                loadingVendors={loadingVendors}
                errors={phaseErrors}
                onEditChange={updatePhaseEdit}
                onApprove={approvePhase}
                onApproveAll={approveAllPhase}
                onRerunFromBackground={rerunFromBackground}
                extraction={extractionData}
                extractionEdits={extractionEdits}
                onExtractionChange={updateExtractionEdit}
                onApproveExtraction={approveExtraction}
                extractionApproved={extractionApproved}
                extractionLoading={extractionLoading}
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
                disabled={loadingVendors.has(vendor)}
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
                {loadingVendors.has(vendor) ? "Retrying..." : "Retry"}
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

