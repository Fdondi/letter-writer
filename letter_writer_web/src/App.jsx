import React, { useState, useEffect } from "react";
import ModelSelector from "./components/ModelSelector";
import LetterTabs from "./components/LetterTabs";
import StyleInstructionsBlade from "./components/StyleInstructionsBlade";
import PhaseFlow from "./components/PhaseFlow";
import { splitIntoParagraphs } from "./utils/split";

function generateColors(vendors) {
  const step = 360 / vendors.length;
  const isDarkMode = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  return vendors.reduce((acc, v, idx) => {
    const hue = Math.round(idx * step);
    acc[v] = isDarkMode 
      ? `hsl(${hue}, 40%, 30%)` 
      : `hsl(${hue}, 70%, 85%)`;
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

  // Update colors when system theme changes
  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = () => {
      setVendorColors(generateColors(vendors));
    };
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
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

const retryVendor = (vendor) => {
  console.warn("Retry vendor not implemented for phased flow yet:", vendor);
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
    const vendorList = Array.from(selectedVendors);

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
          draft: { data: null, approved: false },
          refine: { data: null, approved: false },
          cost: vendorData.cost || 0,
        };
        nextEdits[vendor] = {
          background: {
            company_report: vendorData.company_report || "",
            background_summary: vendorData.background_summary || "",
          },
          draft: { draft_letter: "" },
          refine: { final_letter: "" },
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
    }
  };

  const advanceFromBackground = async (vendor) => {
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
          company_report: edits.company_report,
          background_summary: edits.background_summary,
        }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || "Failed to build draft");
      }
      const data = await res.json();

      setPhaseState((prev) => ({
        ...prev,
        [vendor]: {
          ...(prev[vendor] || {}),
          background: { ...(prev[vendor]?.background || {}), approved: true },
          draft: { data, approved: false },
          refine: prev[vendor]?.refine || { data: null, approved: false },
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
          draft: { draft_letter: data.draft_letter || "" },
          refine: prev[vendor]?.refine || { final_letter: "" },
        },
      }));
    } catch (e) {
      console.error("Draft phase error", e);
      setPhaseErrors((prev) => ({ ...prev, [vendor]: String(e) }));
    } finally {
      setLoadingVendors((prev) => {
        const next = new Set(prev);
        next.delete(vendor);
        return next;
      });
    }
  };

  const advanceFromDraft = async (vendor) => {
    setPhaseErrors((prev) => ({ ...prev, [vendor]: null }));
    setLoadingVendors((prev) => new Set(prev).add(vendor));
    const draftText =
      phaseEdits[vendor]?.draft?.draft_letter ||
      phaseState[vendor]?.draft?.data?.draft_letter ||
      "";
    const sessionId = phaseSessions[vendor] || phaseSessionId;

    try {
      const res = await fetch("/api/phases/refine/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          vendor,
          draft_letter: draftText,
        }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || "Failed to refine");
      }
      const data = await res.json();

      setPhaseState((prev) => ({
        ...prev,
        [vendor]: {
          ...(prev[vendor] || {}),
          draft: { ...(prev[vendor]?.draft || {}), approved: true },
          refine: { data, approved: false },
          cost: data.cost ?? prev[vendor]?.cost ?? 0,
        },
      }));

      setPhaseEdits((prev) => ({
        ...prev,
        [vendor]: {
          ...(prev[vendor] || {}),
          draft: {
            draft_letter: draftText,
          },
          refine: { final_letter: data.final_letter || "" },
        },
      }));
    } catch (e) {
      console.error("Refine phase error", e);
      setPhaseErrors((prev) => ({ ...prev, [vendor]: String(e) }));
    } finally {
      setLoadingVendors((prev) => {
        const next = new Set(prev);
        next.delete(vendor);
        return next;
      });
    }
  };

  const approveRefinement = (vendor) => {
    const finalText =
      (phaseEdits[vendor]?.refine?.final_letter ??
        phaseState[vendor]?.refine?.data?.final_letter ??
        "").trim();

    setPhaseState((prev) => {
      const next = {
        ...prev,
        [vendor]: {
          ...(prev[vendor] || {}),
          refine: {
            data: {
              ...(prev[vendor]?.refine?.data || {}),
              final_letter: finalText,
            },
            approved: true,
          },
        },
      };

      const done = Array.from(selectedVendors).every(
        (v) => next[v]?.refine?.approved || v === vendor
      );
      if (done) {
        setUiStage("assembly");
        setShowInput(false);
      }

      return next;
    });

    setLetters((prev) => ({
      ...prev,
      [vendor]: finalText,
    }));
    setVendorParagraphs((prev) => ({
      ...prev,
      [vendor]: splitIntoParagraphs(finalText, vendor),
    }));
    setVendorCosts((prev) => ({
      ...prev,
      [vendor]: phaseState[vendor]?.cost || 0,
    }));
  };

  const approveAllBackground = async () => {
    const pending = Array.from(selectedVendors).filter(
      (v) => !(phaseState[v]?.background?.approved)
    );
    await Promise.all(pending.map((v) => advanceFromBackground(v)));
  };

  const approveAllDrafts = async () => {
    const pending = Array.from(selectedVendors).filter(
      (v) => phaseState[v]?.background?.approved && !phaseState[v]?.draft?.approved
    );
    await Promise.all(pending.map((v) => advanceFromDraft(v)));
  };

  const approveAllRefinements = () => {
    Array.from(selectedVendors).forEach((v) => {
      if (!phaseState[v]?.refine?.approved && phaseState[v]?.refine?.data) {
        approveRefinement(v);
      }
    });
  };

  const onAddParagraph = (paraObj) => {
    setFinalParagraphs((prev) => [...prev, { ...paraObj }]);
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
  };

  const vendorsList = Array.from(selectedVendors);

  return (
    <div style={{ padding: 20, backgroundColor: 'var(--bg-color)', color: 'var(--text-color)', minHeight: '100vh' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, color: 'var(--text-color)' }}>Letter Writer</h1>
        <button
          onClick={() => setShowStyleBlade(true)}
          style={{
            padding: '8px 16px',
            border: '1px solid var(--border-color)',
            borderRadius: '4px',
            backgroundColor: 'var(--button-bg)',
            color: 'var(--button-text)',
            cursor: 'pointer',
            fontSize: '14px'
          }}
        >
          ⚙️ Style Settings
        </button>
      </div>
      {uiStage === "input" ? (
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
              backgroundColor: 'var(--input-bg)',
              color: 'var(--text-color)',
              border: '1px solid var(--border-color)',
              borderRadius: '4px'
            }}
          />
          <textarea
            style={{ 
              width: "100%", 
              height: 150, 
              marginTop: 10,
              backgroundColor: 'var(--input-bg)',
              color: 'var(--text-color)',
              border: '1px solid var(--border-color)',
              borderRadius: '4px',
              padding: 8
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
              padding: '10px 20px',
              backgroundColor: loading || !jobText || !companyName || selectedVendors.size === 0 ? 'var(--header-bg)' : '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: loading || !jobText || !companyName || selectedVendors.size === 0 ? 'not-allowed' : 'pointer'
            }}
          >
            {loading ? "Starting..." : "Start phased flow"}
          </button>
        </>
      ) : (
        <button 
          onClick={resetForm} 
          style={{ 
            marginBottom: 10,
            padding: '8px 16px',
            backgroundColor: 'var(--button-bg)',
            color: 'var(--button-text)',
            border: '1px solid var(--border-color)',
            borderRadius: '4px',
            cursor: 'pointer'
          }}
        >
          ← Back to Input
        </button>
      )}
      {error && <p style={{ color: "var(--error-text)" }}>{error}</p>}

      {uiStage === "phases" && (
        <PhaseFlow
          vendorsList={vendorsList}
          phaseState={phaseState}
          phaseEdits={phaseEdits}
          loadingVendors={loadingVendors}
          errors={phaseErrors}
          onEditChange={updatePhaseEdit}
          onApproveBackground={advanceFromBackground}
          onApproveDraft={advanceFromDraft}
          onApproveRefine={approveRefinement}
          onApproveAllBackground={approveAllBackground}
          onApproveAllDraft={approveAllDrafts}
          onApproveAllRefine={approveAllRefinements}
        />
      )}

      {Object.keys(failedVendors).length > 0 && (
        <div style={{ 
          marginTop: 10, 
          padding: 10, 
          background: "var(--warning-bg)", 
          border: "1px solid var(--warning-border)",
          color: "var(--text-color)",
          borderRadius: '4px'
        }}>
          <h3 style={{ marginTop: 0 }}>Failed Vendors:</h3>
          {Object.entries(failedVendors).map(([vendor, errorMsg]) => (
            <div key={vendor} style={{ marginBottom: 10 }}>
              <strong style={{ color: 'var(--text-color)' }}>{vendor}:</strong> {errorMsg}
              <button
                onClick={() => retryVendor(vendor)}
                disabled={loadingVendors.has(vendor)}
                style={{ 
                  marginLeft: 10,
                  padding: '4px 8px',
                  backgroundColor: 'var(--button-bg)',
                  color: 'var(--button-text)',
                  border: '1px solid var(--border-color)',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                {loadingVendors.has(vendor) ? "Retrying..." : "Retry"}
              </button>
            </div>
          ))}
        </div>
      )}

      {uiStage === "assembly" && vendorsList.length > 0 && (
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
          onRetry={() => {}}
          onAddParagraph={onAddParagraph}
        />
      )}

      <StyleInstructionsBlade
        isOpen={showStyleBlade}
        onClose={() => setShowStyleBlade(false)}
      />
    </div>
  );
} 