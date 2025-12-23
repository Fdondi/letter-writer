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

  const persistFinalLetter = async (finalText) => {
    if (!documentId || !finalText) return;
    try {
      setSavingFinal(true);
      const res = await fetch(`/api/documents/${documentId}/`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          letter_text: finalText,
          company_name: companyName,
          job_text: jobText,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
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

    try {
      const res = await fetch("/api/phases/start/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_text: jobText,
          company_name: companyName,
          vendors: [vendor],
        }),
      });

      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Failed to restart flow for ${vendor}`);
      }

      const data = await res.json();
      if (!documentId && data.document?.id) {
        setDocumentId(data.document.id);
      }

      const vendorData = data.vendors?.[vendor] || {};

      setPhaseSessions((prev) => ({ ...prev, [vendor]: data.session_id }));
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
            background_summary: vendorData.background_summary || "",
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
      setError(String(e));
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
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setLetters({});
    setVendorCosts({});
    setFailedVendors({});
    setVendorParagraphs({});
    setFinalParagraphs([]);
    setLoadingVendors(new Set());
    setDocumentId(null);
    const vendorList = Array.from(selectedVendors);

    setLoadingVendors(new Set(vendorList));
    try {
      const results = await Promise.all(
        vendorList.map(async (vendor) => {
          const res = await fetch("/api/phases/start/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              job_text: jobText,
              company_name: companyName,
              vendors: [vendor],
            }),
          });
          if (!res.ok) {
            const detail = await res.text();
            throw new Error(detail || `Failed to start phased flow for ${vendor}`);
          }
          const data = await res.json();
          if (!documentId && data.document?.id) {
            setDocumentId(data.document.id);
          }
          return { vendor, data };
        })
      );

      const nextState = {};
      const nextEdits = {};
      const nextSessions = {};

      results.forEach(({ vendor, data }) => {
        const vendorData = data.vendors?.[vendor] || {};
        nextSessions[vendor] = data.session_id;
        nextState[vendor] = {
          background: { data: vendorData, approved: false },
          refine: { data: null, approved: false },
          cost: vendorData.cost || 0,
        };
        nextEdits[vendor] = {
          background: {
            company_report: vendorData.company_report || "",
            background_summary: vendorData.background_summary || "",
          },
          refine: { final_letter: "", draft_letter: "" },
        };
      });

      setPhaseSessions(nextSessions);
      setPhaseSessionId(null); // no shared session anymore
      setPhaseState(nextState);
      setPhaseEdits(nextEdits);
      setPhaseErrors({});
      setShowInput(false);
      setUiStage("phases");
    } catch (e) {
      console.error("Start phased flow error", e);
      setError(String(e));
    } finally {
      setLoading(false);
      setLoadingVendors(new Set());
    }
  };

  const approvePhase = async (phase, vendor) => {
    if (phase === "background") {
      setPhaseErrors((prev) => ({ ...prev, [vendor]: null }));
      setLoadingVendors((prev) => new Set(prev).add(vendor));
      const edits = phaseEdits[vendor]?.background || {};
      const sessionId = phaseSessions[vendor] || phaseSessionId;

      try {
        const res = await fetch("/api/phases/draft/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            vendor,
            // background is user-editable; always send current edits to override cached
            company_report: edits.company_report,
            background_summary: edits.background_summary,
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
              background_summary: data.background_summary ?? edits.background_summary ?? "",
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
        (bgEdits.company_report ?? "") !== (bg.company_report ?? "") ||
        (bgEdits.background_summary ?? "") !== (bg.background_summary ?? "");
      const feedbackOverrides = phaseEdits[vendor]?.refine?.feedback_overrides || {};
      const hasFeedbackOverrides = Object.keys(feedbackOverrides).length > 0;

      try {
        const payload = {
          session_id: sessionId,
          vendor,
          draft_letter: editedFinal || phaseState[vendor]?.refine?.data?.draft_letter || "",
        };
        // Only send background overrides if the user changed them
        if (backgroundDirty) {
          payload.company_report = bgEdits.company_report ?? "";
          payload.background_summary = bgEdits.background_summary ?? "";
        }
        if (hasFeedbackOverrides) {
          payload.feedback_override = feedbackOverrides;
        }

        const res = await fetch("/api/phases/refine/", {
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
      const pending = Array.from(selectedVendors).filter(
        (v) => !(phaseState[v]?.background?.approved)
      );
      await Promise.all(pending.map((v) => approvePhase("background", v)));
    } else if (phase === "refine") {
      Array.from(selectedVendors).forEach((v) => {
        if (!phaseState[v]?.refine?.approved && phaseState[v]?.refine?.data) {
          approvePhase("refine", v);
        }
      });
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
          <input
            type="text"
            placeholder="Company name"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            style={{
              width: "100%",
              marginTop: 10,
              padding: 8,
              backgroundColor: "var(--input-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
            }}
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
          <button
            onClick={handleSubmit}
            disabled={loading || !jobText || !companyName || selectedVendors.size === 0}
            style={{
              marginTop: 10,
              padding: "10px 20px",
              backgroundColor:
                loading || !jobText || !companyName || selectedVendors.size === 0
                  ? "var(--header-bg)"
                  : "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor:
                loading || !jobText || !companyName || selectedVendors.size === 0
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

