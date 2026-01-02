import React, { useState, useEffect, useRef } from "react";

// Card status enum - cards report their status to phases
const CardStatus = {
  PENDING: 'pending',
  READY: 'ready',
  APPROVED: 'approved',
};

// Feedback type descriptions for tooltips (based on actual prompts in generation.py)
const FEEDBACK_DESCRIPTIONS = {
  'instruction': 'Checks the letter for consistency with the style instructions. Flags any strong inconsistencies with the specified writing style and tone.',
  'instruction_feedback': 'Checks the letter for consistency with the style instructions. Flags any strong inconsistencies with the specified writing style and tone.',
  'accuracy': 'Verifies factual accuracy against your CV. Checks if claims are coherent with themselves and supported by your CV. Flags unsupported expertise claims or inconsistencies.',
  'accuracy_feedback': 'Verifies factual accuracy against your CV. Checks if claims are coherent with themselves and supported by your CV. Flags unsupported expertise claims or inconsistencies.',
  'precision': 'Evaluates how well the letter addresses job requirements. Checks if all required competencies are addressed (or substituted), flags superfluous claims, and verifies company-related claims match the company report.',
  'precision_feedback': 'Evaluates how well the letter addresses job requirements. Checks if all required competencies are addressed (or substituted), flags superfluous claims, and verifies company-related claims match the company report.',
  'company_fit': 'Assesses alignment with the company\'s values, mission, tone, and culture. Checks if the letter feels personalized for the company rather than generic.',
  'company_fit_feedback': 'Assesses alignment with the company\'s values, mission, tone, and culture. Checks if the letter feels personalized for the company rather than generic.',
  'user_fit': 'Compares the letter to your previous cover letters. Checks if it matches the same writing style, pays attention to the same aspects, and highlights strengths/negotiates weaknesses in the same way.',
  'user_fit_feedback': 'Compares the letter to your previous cover letters. Checks if it matches the same writing style, pays attention to the same aspects, and highlights strengths/negotiates weaknesses in the same way.',
  'human': 'Analyzes patterns from your previous letter revisions. Flags elements that were typically changed or removed in your past edits, based on your review history.',
  'human_feedback': 'Analyzes patterns from your previous letter revisions. Flags elements that were typically changed or removed in your past edits, based on your review history.',
};

// Tooltip component
function InfoTooltip({ text, children }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipRef = useRef(null);

  useEffect(() => {
    if (showTooltip && tooltipRef.current) {
      const handleMouseLeave = () => setShowTooltip(false);
      const element = tooltipRef.current;
      element.addEventListener('mouseleave', handleMouseLeave);
      return () => element.removeEventListener('mouseleave', handleMouseLeave);
    }
  }, [showTooltip]);

  return (
    <span
      ref={tooltipRef}
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {children}
      {showTooltip && text && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: '4px',
            padding: '6px 10px',
            backgroundColor: 'var(--bg-color)',
            color: 'var(--text-color)',
            border: '1px solid var(--border-color)',
            borderRadius: '4px',
            fontSize: '12px',
            zIndex: 1000,
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
            maxWidth: '250px',
            whiteSpace: 'normal',
            textAlign: 'left',
          }}
        >
          {text}
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              width: 0,
              height: 0,
              borderLeft: '6px solid transparent',
              borderRight: '6px solid transparent',
              borderTop: '6px solid var(--bg-color)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              width: 0,
              height: 0,
              borderLeft: '7px solid transparent',
              borderRight: '7px solid transparent',
              borderTop: '7px solid var(--border-color)',
              zIndex: -1,
            }}
          />
        </div>
      )}
    </span>
  );
}

function InputRow({ label, value, onChange, placeholder }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
      <span style={{ fontWeight: 600 }}>{label}</span>
      <input
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        placeholder={placeholder}
        style={{ padding: 8, border: "1px solid #e5e7eb", borderRadius: 4 }}
      />
    </label>
  );
}

function PhaseSection({
  title,
  children,
  collapsed,
  onToggle,
  onApproveAll,
  approveAllDisabled,
  showApproveAll,
  readyCount,
  totalCount,
  gridAutoColumns = "340px",
}) {
  // Always show count format when we have counts: "Approve (X/Y)"
  // Only show "Approve all" when all are ready (readyCount === totalCount > 0)
  const approveButtonText = readyCount !== undefined && totalCount !== undefined
    ? readyCount === totalCount && readyCount > 0
      ? "Approve all"
      : `Approve (${readyCount}/${totalCount})`
    : "Approve all";
  
  return (
    <details open={!collapsed} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 8 }}>
      <summary
        style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", listStyle: "none" }}
        onClick={onToggle}
      >
        <h3 style={{ margin: 0 }}>{title}</h3>
        {showApproveAll && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onApproveAll?.();
            }}
            disabled={approveAllDisabled || readyCount === 0}
            style={{ fontSize: 12, padding: "4px 8px", opacity: (approveAllDisabled || readyCount === 0) ? 0.6 : 1 }}
          >
            {approveButtonText}
          </button>
        )}
      </summary>
      <div
        style={{
          display: "grid",
          gridAutoFlow: "column",
          gridAutoColumns,
          gridAutoRows: "1fr",
          gap: 12,
          marginTop: 8,
          overflowX: "auto",
          alignItems: "stretch",
        }}
      >
        {children}
      </div>
    </details>
  );
}

function EditableField({ label, value, minHeight = 120, placeholder, onSave, disabled = false }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");

  useEffect(() => {
    if (!editing) {
      setDraft(value || "");
    }
  }, [value, editing]);

  return (
    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <label style={{ fontWeight: 600, fontSize: 13, flex: 1 }}>{label}</label>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={disabled}
            style={{ 
              fontSize: 12, 
              padding: "4px 8px",
              opacity: disabled ? 0.6 : 1,
              cursor: disabled ? "not-allowed" : "pointer"
            }}
          >
            ✎ Edit
          </button>
        )}
      </div>

      {editing ? (
        <>
          <textarea
            style={{ width: "100%", minHeight, padding: 8 }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={placeholder}
            disabled={disabled}
            // allow long URLs to wrap
            wrap="soft"
            spellCheck={true}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => {
                onSave(draft);
                setEditing(false);
              }}
              disabled={disabled}
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(value || "");
                setEditing(false);
              }}
              disabled={disabled}
            >
              Discard
            </button>
          </div>
        </>
      ) : (
        <div
          style={{
            width: "100%",
            minHeight,
            padding: 8,
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            background: "#f9fafb",
            whiteSpace: "pre-wrap",
            fontSize: 13,
          }}
        >
          {value || placeholder || ""}
        </div>
      )}
    </div>
  );
}

function EditableFeedback({
  label,
  value,
  placeholder,
  onSave,
  approved,
  onApprove,
  hasContent,
  isModified,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");

  useEffect(() => {
    if (!editing) {
      setDraft(value || "");
    }
  }, [value, editing]);

  const statusColor = hasContent ? "#2563eb" : "#9ca3af"; // comment presence
  const approveColor = approved ? "#16a34a" : "#9ca3af";

  const feedbackDescription = FEEDBACK_DESCRIPTIONS[label] || `Feedback about ${label.replace(/_/g, ' ')}.`;

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid #e5e7eb", borderRadius: 6, background: "#f9fafb" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, fontWeight: 600 }}>
          {label}
          <InfoTooltip text={feedbackDescription}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '12px',
                fontWeight: 'normal',
                color: 'var(--text-color)',
                opacity: 0.6,
                cursor: 'help',
                lineHeight: '1',
                fontStyle: 'italic',
                marginLeft: '4px',
              }}
              title={feedbackDescription}
            >
              (i)
            </span>
          </InfoTooltip>
        </div>
        {!editing && (
          <>
            {hasContent && (
              <button 
                type="button" 
                onClick={() => onSave("NO COMMENT")} 
                style={{ 
                  fontSize: 12, 
                  padding: "4px 8px",
                  border: "1px solid #dc2626",
                  background: "#fff",
                  color: "#dc2626",
                  cursor: "pointer",
                }}
              >
                Remove
              </button>
            )}
            <button type="button" onClick={() => setEditing(true)} style={{ fontSize: 12, padding: "4px 8px" }}>
              Edit
            </button>
          </>
        )}
        {isModified ? (
          <span
            style={{
              fontSize: 12,
              padding: "4px 8px",
              border: "1px solid #fca5a5",
              background: "#fff1f2",
              color: "#b91c1c",
              borderRadius: 4,
            }}
          >
            Edited
          </span>
        ) : (
          <button
            type="button"
            onClick={onApprove}
            style={{
              fontSize: 12,
              padding: "4px 8px",
              border: "1px solid #16a34a",
              background: approved ? "#dcfce7" : "#fff",
              color: "#166534",
              cursor: approved ? "default" : "pointer",
            }}
            disabled={approved}
          >
            {approved ? "Approved" : "Approve"}
          </button>
        )}
      </div>

      {editing ? (
        <>
          <textarea
            style={{ width: "100%", minHeight: 120, padding: 8 }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={placeholder}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
            <button
              type="button"
              onClick={() => {
                onSave(draft);
                setEditing(false);
              }}
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(value || "");
                setEditing(false);
              }}
            >
              Discard
            </button>
          </div>
        </>
      ) : (
        <div
          style={{
            width: "100%",
            minHeight: 80,
            padding: 8,
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            background: "#fff",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            overflowWrap: "anywhere",
            fontSize: 13,
          }}
        >
          {value || placeholder || ""}
        </div>
      )}
    </div>
  );
}

function ExtractionCard({
  vendor,
  data,
  edits,
  onChange,
  onApprove,
  loading,
  error,
  approved,
}) {
  const fields = [
    { key: "company_name", label: "Company", placeholder: "Detected company name (required)" },
    { key: "job_title", label: "Job title", placeholder: "e.g. Senior Backend Engineer" },
    { key: "location", label: "Location", placeholder: "e.g. Remote, Berlin, Hybrid" },
    { key: "language", label: "Language", placeholder: "Primary language" },
    { key: "salary", label: "Salary", placeholder: "Salary range or notes" },
  ];

  const requirementsValue = Array.isArray(edits?.requirements)
    ? edits.requirements.join("\n")
    : edits?.requirements || data?.requirements?.join?.("\n") || data?.requirements || "";

  return (
    <div style={{ ...cardStyle, flex: "1 1 360px", maxWidth: 420 }}>
      <h3 style={{ marginTop: 0, marginBottom: 6 }}>1) Extract job info ({vendor})</h3>
      <div style={{ fontSize: 13, color: "#374151", marginBottom: 8 }}>
        We parsed the job description. Tweak any fields, then approve to run background search.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8 }}>
        {fields.map(({ key, label, placeholder }) => (
          <label key={key} style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
            <span style={{ fontWeight: 600 }}>{label}</span>
            <input
              value={edits?.[key] ?? data?.[key] ?? ""}
              onChange={(e) => onChange?.(key, e.target.value)}
              placeholder={placeholder}
              style={{ padding: 8, border: "1px solid #e5e7eb", borderRadius: 4 }}
            />
          </label>
        ))}

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
          <span style={{ fontWeight: 600 }}>Main requirements</span>
          <textarea
            value={requirementsValue}
            onChange={(e) =>
              onChange?.(
                "requirements",
                e.target.value
                  .split("\n")
                  .map((line) => line.trim())
                  .filter(Boolean)
              )
            }
            placeholder="One per line"
            style={{ padding: 8, minHeight: 90, border: "1px solid #e5e7eb", borderRadius: 4 }}
          />
        </label>
      </div>

      {error && (
        <div style={{
          marginTop: 8,
          color: "var(--error-text)",
          fontSize: 12,
          padding: 8,
          background: "var(--error-bg)",
          border: "1px solid var(--error-border)",
          borderRadius: 4
        }}>
          {error}
        </div>
      )}

      <div style={{ ...buttonBarStyle, position: "static", marginTop: 12 }}>
        <button
          onClick={() => onApprove(vendor)}
          disabled={loading || !(edits?.company_name || data?.company_name)}
          style={{
            padding: "8px 12px",
            opacity: loading || !(edits?.company_name || data?.company_name) ? 0.6 : 1,
            cursor: loading || !(edits?.company_name || data?.company_name) ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Running background..." : approved ? "Re-run background" : "Approve & run background"}
        </button>
      </div>
    </div>
  );
}

const cardStyle = {
  border: "1px solid #e5e7eb",
  borderRadius: 8,
  padding: 12,
  paddingBottom: 36, // reserve space for bottom action buttons
  background: "#fafafa",
  display: "flex",
  flexDirection: "column",
  gap: 8,
  flex: "0 0 340px",
  maxWidth: 340,
  position: "relative",
  boxSizing: "border-box",
};

const contentContainerStyle = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  overflowY: "auto",
  paddingRight: 2,
  paddingBottom: 8,
  boxSizing: "border-box",
};

const buttonBarStyle = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
  position: "absolute",
  bottom: 12,
  left: 12,
  right: 12,
};

function VendorCard({
  vendor,
  // Phase structure - for navigation only, not for state
  phases, // Array of phase objects
  phaseObj, // The phase object this card belongs to: { phase: "background", previous: null, next: <phaseObj>, ... }
  // Card owns its own state
  data = {}, // The phase data for this vendor
  approved = false, // Whether this card is approved
  edits = {}, // The edits for this vendor in this phase
  previousPhaseApproved = true, // Whether the previous phase is approved for this vendor
  allPhasesDone = false, // Whether all phases are done for this vendor
  phaseCost = 0, // Cost for this phase
  runningTotal = 0, // Running total cost from the beginning
  onEditChange,
  onSaveFeedbackOverride,
  onApprove,
  sessionId, // Required: session ID for API calls
  onStatusChange, // Callback to register status with phase: (status: CardStatus) => void
  onRerunFromBackground,
  disabled = false,
  // Form data for extraction phase
  companyName,
  jobTitle,
  location,
  language,
  salary,
  requirements,
  onCompanyNameChange,
  onJobTitleChange,
  onLocationChange,
  onLanguageChange,
  onSalaryChange,
  onRequirementsChange,
  onApproveExtraction,
  extractionLoading = false,
  extractionError,
  phaseError = null, // Error from parent phaseErrors state
}) {
  // This card knows which phase it belongs to
  const cardPhase = phaseObj?.phase || null;
  
  // Card owns its state - use props directly
  const cardPhaseData = data || {};
  const isCardPhaseApproved = approved || false;
  const cardPhaseEdits = edits || {};
  
  // This card's loading state - source of truth for THIS card
  // Initialize as loading if no data
  const hasInitialData = cardPhaseData && Object.keys(cardPhaseData).length > 0;
  const [isLoading, setIsLoading] = useState(!hasInitialData);
  const [cardError, setCardError] = useState(null);
  
  // Sync phaseError from parent to cardError state
  useEffect(() => {
    if (phaseError) {
      // Parse error message - it might be a JSON string with detail field
      let errorMessage = phaseError;
      try {
        // Handle "API error occurred: Status XXX. Body: {...}" format
        if (phaseError.includes('API error occurred:')) {
          // Try to extract JSON from "Body: {...}" part
          const bodyMatch = phaseError.match(/Body:\s*({[\s\S]*})/);
          if (bodyMatch) {
            try {
              const body = JSON.parse(bodyMatch[1]);
              errorMessage = body.detail || body.message || errorMessage;
            } catch (e) {
              // If parsing fails, try to extract just the detail value directly
              const detailMatch = phaseError.match(/"detail"\s*:\s*"([^"]+)"/);
              if (detailMatch) {
                errorMessage = detailMatch[1];
              }
            }
          } else {
            // Try to extract detail value directly even without full JSON
            const detailMatch = phaseError.match(/"detail"\s*:\s*"([^"]+)"/);
            if (detailMatch) {
              errorMessage = detailMatch[1];
            }
          }
        } else if (phaseError.trim().startsWith('{')) {
          // Try to parse as JSON if it looks like JSON
          const parsed = JSON.parse(phaseError);
          if (parsed.detail) {
            errorMessage = parsed.detail;
          } else if (parsed.message) {
            errorMessage = parsed.message;
          }
        } else if (phaseError.includes('detail')) {
          // Try to extract detail from string that contains "detail"
          const detailMatch = phaseError.match(/"detail"\s*:\s*"([^"]+)"/);
          if (detailMatch) {
            errorMessage = detailMatch[1];
          }
        }
      } catch (e) {
        // If parsing fails, use original error message
      }
      setCardError(errorMessage);
      // When there's an error, stop loading
      setIsLoading(false);
    } else {
      setCardError(null);
    }
  }, [phaseError]);
  
  // Card-specific UI state
  const [selectedFeedbackTab, setSelectedFeedbackTab] = useState(null);
  const [feedbackApprovals, setFeedbackApprovals] = useState({});
  const [collapsed, setCollapsed] = useState(false);

  const error = cardError;

  // Update loading state when data arrives
  useEffect(() => {
    const hasDataNow = cardPhaseData && Object.keys(cardPhaseData).length > 0;
    if (hasDataNow && isLoading) {
      // Data arrived - stop loading
      setIsLoading(false);
    } else if (!hasDataNow && !isLoading && cardPhase) {
      // Data was cleared or we're in a loading state but isLoading wasn't set
      setIsLoading(true);
    }
  }, [cardPhaseData, isLoading, cardPhase]);
  
  // Track current registered status to avoid infinite loops
  const registeredStatusRef = useRef(null);
  
  // Register status changes with phase (only when status actually changes)
  useEffect(() => {
    if (!cardPhase || !onStatusChange) return;
    
    const hasDataNow = cardPhaseData && Object.keys(cardPhaseData).length > 0;
    
    let newStatus = null;
    if (isCardPhaseApproved) {
      newStatus = CardStatus.APPROVED;
    } else if (isLoading && !hasDataNow) {
      newStatus = CardStatus.PENDING;
    } else if (!isLoading && hasDataNow) {
      newStatus = CardStatus.READY;
    }
    
    // Only register if status changed
    if (newStatus && newStatus !== registeredStatusRef.current) {
      registeredStatusRef.current = newStatus;
      onStatusChange(newStatus);
    }
  }, [isLoading, cardPhaseData, isCardPhaseApproved, cardPhase, onStatusChange]);
  const renderExtraction = () => {
    // For extraction phase, approved means background phase has started (has data)
    // We can't check this directly since we don't have background data here
    // This should be passed as a prop if needed, or checked differently
    const isExtractionApproved = false; // TODO: pass as prop if needed
    const isExtractionLoading = extractionLoading;
    
    const requirementsValue = Array.isArray(requirements)
      ? requirements.join("\n")
      : requirements || "";
    const isBusy = isExtractionLoading;
    const hasCompany = (companyName || "").trim().length > 0;

    return (
      <>
        <div style={{ fontSize: 13, color: "#374151" }}>
          We parsed the job description. Tweak any fields, then approve to run background search.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8 }}>
          <InputRow
            label="Company"
            value={companyName || ""}
            onChange={(val) => onCompanyNameChange?.(val)}
            placeholder="Detected company name (required)"
          />
          <InputRow
            label="Job title"
            value={jobTitle || ""}
            onChange={(val) => onJobTitleChange?.(val)}
            placeholder="e.g. Senior Backend Engineer"
          />
          <InputRow
            label="Location"
            value={location || ""}
            onChange={(val) => onLocationChange?.(val)}
            placeholder="e.g. Remote, Berlin, Hybrid"
          />
          <InputRow
            label="Language"
            value={language || ""}
            onChange={(val) => onLanguageChange?.(val)}
            placeholder="Primary language"
          />
          <InputRow
            label="Salary"
            value={salary || ""}
            onChange={(val) => onSalaryChange?.(val)}
            placeholder="Salary range or notes"
          />
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
            <span style={{ fontWeight: 600 }}>Main requirements</span>
            <textarea
              value={requirementsValue}
              onChange={(e) =>
                onRequirementsChange?.(
                  e.target.value
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean)
                )
              }
              placeholder="One per line"
              style={{ padding: 8, minHeight: 90, border: "1px solid #e5e7eb", borderRadius: 4 }}
            />
          </label>
        </div>
        {extractionError && (
          <div style={{ marginTop: 8, color: "red", fontSize: 12 }}>
            {extractionError}
          </div>
        )}
        <div style={{ ...buttonBarStyle, position: "static", marginTop: 12 }}>
          <button
            onClick={() => onApproveExtraction?.(vendor)}
            disabled={isBusy || !hasCompany}
            style={{
              padding: "8px 12px",
              opacity: isBusy || !hasCompany ? 0.6 : 1,
              cursor: isBusy || !hasCompany ? "not-allowed" : "pointer",
            }}
          >
            {isBusy ? "Running background..." : isExtractionApproved ? "Re-run background" : "Approve background → generate letter"}
          </button>
        </div>
      </>
    );
  };

  // Phase-agnostic: work with phase objects from phase-centric structure
  const thisPhaseData = cardPhaseData;
  const thisPhaseApproved = isCardPhaseApproved;
  
  // Check if this card's phase data is dirty (edits differ from data) - phase-agnostic
  const thisPhaseDirty = phaseObj ? Object.keys(cardPhaseEdits).some(key => {
    const editValue = (cardPhaseEdits[key] ?? '').toString().trim();
    const dataValue = (thisPhaseData[key] ?? '').toString().trim();
    return editValue !== dataValue;
  }) : false;
  
  // Check if all phases are done (for "done" state) - use prop
  const isDone = allPhasesDone;
  
  // For refine-specific features (feedback) - initialize tab when feedback data arrives
  useEffect(() => {
    if (cardPhase === "refine") {
      const feedback = cardPhaseData?.feedback || {};
      const feedbackKeys = Object.keys(feedback);
      if (feedbackKeys.length > 0 && !selectedFeedbackTab) {
        setSelectedFeedbackTab(feedbackKeys[0]);
        // Initialize approvals as all unreviewed
        const initialApprovals = {};
        feedbackKeys.forEach(k => {
          initialApprovals[k] = false;
        });
        setFeedbackApprovals(initialApprovals);
      }
    }
  }, [cardPhase, cardPhaseData, selectedFeedbackTab]);
  
  // For refine-specific features (feedback)
  const feedback = cardPhase === "refine" ? (cardPhaseData?.feedback || {}) : {};
  const feedbackKeys = Object.keys(feedback);
  const feedbackOverrides = cardPhase === "refine" ? (cardPhaseEdits?.feedback_overrides || {}) : {};
  const activeFeedbackKey = selectedFeedbackTab || feedbackKeys[0] || null;

  // Helper function to find the next unseen feedback tab
  const findNextUnseenFeedback = (currentKey, approvals, overrides, feedbackData) => {
    if (feedbackKeys.length === 0) return null;
    
    // Helper to check if a feedback is "seen" based on human status
    // A feedback is "seen" if human status is not "❔" (i.e., it's 👍, ✏️, or ✅)
    const isSeen = (key) => {
      const isApproved = approvals[key] === true;
      
      const baseVal = feedbackData[key] || "";
      const overrideVal = overrides[key];
      const isModified = overrideVal !== undefined && overrideVal !== baseVal;

      return isApproved || isModified
    };
    
    // Find current index
    const currentIndex = feedbackKeys.indexOf(currentKey);
    
    // Start searching from the next item after current
    for (let i = 1; i < feedbackKeys.length; i++) {
      const nextIndex = (currentIndex + i) % feedbackKeys.length;
      const nextKey = feedbackKeys[nextIndex];
      if (!isSeen(nextKey)) {
        return nextKey;
      }
    }
    
    // All feedbacks are seen, return null
    return null;
  };
  
  // Auto-collapse when done
  useEffect(() => {
    if (isDone && !collapsed) {
      setCollapsed(true);
    }
  }, [isDone, collapsed]);
  
  // Previous phase approval status - use prop (calculated in renderVendor)
  // Determine stage from this card's phase and approval status
  let stage = "done";
  if (!isCardPhaseApproved && cardPhase) {
    const hasData = cardPhaseData && Object.keys(cardPhaseData).length > 0;
    stage = hasData ? cardPhase : "pending-refine";
  }

  const phaseToRender = cardPhase || stage;
  const isPendingRefine = stage === "pending-refine";
  const pendingLabel = isPendingRefine ? "Running next phase..." : null;

  // Phase-agnostic check: show loading UI when loading and no data yet
  // When re-running, old data is cleared so we go back to loading state
  const hasPhaseData = cardPhase && cardPhaseData && Object.keys(cardPhaseData).length > 0;
  const isLoadingWithoutData = isLoading && !hasPhaseData && !isCardPhaseApproved;

  return (
    <div style={{ ...cardStyle, opacity: disabled ? 0.6 : 1, pointerEvents: disabled ? "none" : "auto" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 8 }}>
        <h4 style={{ margin: 0, flex: 1, textTransform: "capitalize" }}>{vendor}</h4>
        {(phaseCost > 0 || runningTotal > 0) && (
          <div style={{ fontSize: "11px", color: "var(--secondary-text-color)", textAlign: "right" }}>
            <div>${phaseCost.toFixed(4)}</div>
            <div style={{ fontSize: "10px", opacity: 0.8 }}>Total: ${runningTotal.toFixed(4)}</div>
          </div>
        )}
        {isDone && (
          <button onClick={() => setCollapsed(!collapsed)} style={{ fontSize: 12, padding: "4px 8px" }}>
            {collapsed ? "Expand" : "Collapse"}
          </button>
        )}
      </div>

      {isLoadingWithoutData && (
        <div style={{ padding: 6, color: "#6b7280", fontSize: 12 }}>
          {pendingLabel || "Loading..."}
        </div>
      )}

      {error && !isLoadingWithoutData && (
        <div style={{
          color: "var(--error-text)",
          marginBottom: 8,
          fontSize: 13,
          padding: 8,
          background: "var(--error-bg)",
          border: "1px solid var(--error-border)",
          borderRadius: 4
        }}>
          {error}
        </div>
      )}

      {!isLoadingWithoutData && (
      <div style={contentContainerStyle}>
        {phaseToRender === "extraction" && (
          renderExtraction()
        )}
        {/* Render content for this card's phase - phase-agnostic */}
        {cardPhase === "background" && (phaseToRender === "background" || (isDone && !collapsed)) && (
          <>
            <div style={{ fontSize: 13, color: "#374151" }}>
              Review the background search. Edit if needed, then approve to generate the letter.
            </div>
            <EditableField
              label="Company report"
              value={cardPhaseEdits.company_report ?? thisPhaseData.company_report ?? ""}
              minHeight={140}
              placeholder="Company research"
              onSave={(val) => onEditChange(vendor, cardPhase, "company_report", val)}
              disabled={isLoading}
            />
          </>
        )}

        {cardPhase === "refine" && (phaseToRender === "refine" || (isDone && !collapsed)) && (
          <>
            <div style={{ fontSize: 13, color: "#374151" }}>
              {!previousPhaseApproved
                ? `${phaseObj?.previous?.phase ? phaseObj.previous.phase.charAt(0).toUpperCase() + phaseObj.previous.phase.slice(1) : "Previous"} approval required before ${cardPhase} phase.`
                : thisPhaseApproved
                  ? "Draft letter is approved. Edit to rerun refinement if needed."
                  : "Edit if desired, then approve to move to assembly."}
            </div>
            <EditableField
              label="Draft letter"
              value={cardPhaseEdits.draft_letter ?? thisPhaseData.draft_letter ?? ""}
              minHeight={220}
              placeholder="Draft letter"
              onSave={(val) => onEditChange(vendor, cardPhase, "draft_letter", val)}
              disabled={isLoading}
            />
            {feedbackKeys.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {feedbackKeys.map((key) => {
                    const overriddenVal = feedbackOverrides[key];
                    const baseVal = feedback[key] || "";
                    const displayVal = overriddenVal !== undefined ? overriddenVal : baseVal;
                    const trimmedUpper = (displayVal || "").trim().toUpperCase();
                    const isNoComment = trimmedUpper === "" || trimmedUpper.endsWith("NO COMMENT");
                    const hasContent = !isNoComment;
                    const approved = feedbackApprovals[key];
                    const isModified = overriddenVal !== undefined && overriddenVal !== baseVal;

                    // Machine block: 🤖 | status
                    // Robot should remain 📜 if base value had content, even if user changed it to NO COMMENT
                    const baseHasContent = (baseVal || "").trim().length > 0 && 
                      !(baseVal || "").trim().toUpperCase().endsWith("NO COMMENT");
                    const machineStatus = baseHasContent ? "📜" : "✅";

                    // Human block: 🧑 | status (stacked with thick divider between machine and human)
                    // Human status rules:
                    // - ✅ only when the user edited a non-NO COMMENT to NO COMMENT
                    // - 👍 when the user approved without changing content
                    // - ✏️ when the user edited but did not clear issues
                    // - ❔ otherwise
                    const baseNoComment = (baseVal || "").trim().toUpperCase().endsWith("NO COMMENT");
                    let humanStatus = "❔";
                    const userClearedIssue = isModified && isNoComment && !baseNoComment;
                    if (userClearedIssue) {
                      humanStatus = "✅";
                    } else if (approved) {
                      humanStatus = "👍";
                    } else if (isModified) {
                      humanStatus = "✏️";
                    }

                    const isSelected = activeFeedbackKey === key;
                    return (
                      <button
                        key={`${vendor}-tab-${key}`}
                        onClick={() => setSelectedFeedbackTab(key)}
                        style={{
                          padding: "4px 8px",
                          fontSize: 12,
                          borderRadius: 4,
                          border: isSelected ? "1px solid #2563eb" : "1px solid #ccc",
                          background: isSelected ? "#e0e7ff" : "#f9fafb",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {key}
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 0, marginLeft: 4 }}>
                          <div style={{ display: "inline-flex", alignItems: "center", gap: 2, padding: "0 4px" }}>
                            🤖 {machineStatus}
                          </div>
                          <div style={{ width: 2, background: "#d1d5db", height: 14, margin: "0 4px" }} />
                          <div style={{ display: "inline-flex", alignItems: "center", gap: 2, padding: "0 4px" }}>
                            🧑 {humanStatus}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    onClick={() => {
                      const allKeys = feedbackKeys;
                      allKeys.forEach((k) => {
                        setFeedbackApprovals(prev => ({ ...prev, [k]: true }));
                      });
                    }}
                    style={{ padding: "4px 8px", fontSize: 12 }}
                  >
                    Approve all comments
                  </button>
                </div>
                {activeFeedbackKey && (feedback[activeFeedbackKey] !== undefined || feedbackOverrides[activeFeedbackKey] !== undefined) && (
                  <EditableFeedback
                    label={activeFeedbackKey}
                    value={feedbackOverrides[activeFeedbackKey] ?? feedback[activeFeedbackKey] ?? ""}
                    placeholder="Feedback"
                    approved={feedbackApprovals[activeFeedbackKey]}
                    hasContent={(feedback[activeFeedbackKey] || "").trim().length > 0}
                    onApprove={() => {
                      setFeedbackApprovals(prev => {
                        const next = { ...prev, [activeFeedbackKey]: true };
                        // Move to next unseen feedback after approval
                        const nextUnseen = findNextUnseenFeedback(
                          activeFeedbackKey,
                          next,
                          feedbackOverrides,
                          feedback
                        );
                        if (nextUnseen) {
                          setSelectedFeedbackTab(nextUnseen);
                        }
                        return next;
                      });
                    }}
                    onSave={(val) => {
                      // Construct updated overrides before calling onSaveFeedbackOverride
                      // (since state update is async, we need to use the updated value for the check)
                      const updatedOverrides = { ...feedbackOverrides, [activeFeedbackKey]: val };
                      onSaveFeedbackOverride(activeFeedbackKey, val);
                      // After saving, move to next unseen feedback
                      const nextUnseen = findNextUnseenFeedback(
                        activeFeedbackKey,
                        feedbackApprovals,
                        updatedOverrides,
                        feedback
                      );
                      if (nextUnseen) {
                        setSelectedFeedbackTab(nextUnseen);
                      }
                    }}
                    isModified={
                      feedbackOverrides[activeFeedbackKey] !== undefined &&
                      feedbackOverrides[activeFeedbackKey] !== feedback[activeFeedbackKey]
                    }
                  />
                )}
              </div>
            )}
          </>
        )}
      </div>
      )}

      {!isLoadingWithoutData && (
      <div style={buttonBarStyle}>
        {cardPhase === "background" && (phaseToRender === "background" || (isDone && !collapsed)) && (
          <button
            onClick={() => {
              // When re-running (has data but dirty), clear data and set loading
              if (hasPhaseData && thisPhaseDirty) {
                setIsLoading(true);
                if (onStatusChange) onStatusChange(CardStatus.PENDING);
              }
              onApprove(cardPhase, vendor);
            }}
            disabled={
              isLoading ||
              (thisPhaseApproved && !thisPhaseDirty)
            }
            style={{
              opacity: isLoading || (thisPhaseApproved && !thisPhaseDirty) ? 0.6 : 1,
              cursor: isLoading || (thisPhaseApproved && !thisPhaseDirty) ? "not-allowed" : "pointer",
            }}
          >
            {isLoading
              ? "Processing..."
              : thisPhaseApproved
                ? thisPhaseDirty
                  ? "Save and restart from here"
                  : "Edit to restart from here"
                : "Approve background → generate letter"}
          </button>
        )}
        {cardPhase === "background" && (phaseToRender === "background" || (isDone && !collapsed && !forcePhase)) && isDone && (
          <button
            onClick={() => {
              onRerunFromBackground(vendor);
            }}
            style={{ opacity: 0.8 }}
          >
            Rebuild letter from edited background
          </button>
        )}

        {cardPhase === "refine" && (phaseToRender === "refine" || (isDone && !collapsed)) && (
          <button
            onClick={() => {
              // When re-running (has data but dirty), clear data and set loading
              if (hasPhaseData && thisPhaseDirty) {
                setIsLoading(true);
                if (onStatusChange) onStatusChange(CardStatus.PENDING);
              }
              onApprove(cardPhase, vendor);
            }}
            style={{
              opacity:
                isLoading ||
                !previousPhaseApproved ||
                (thisPhaseApproved && !thisPhaseDirty) ||
                (feedbackKeys.length > 0 &&
                  feedbackKeys.some((k) => {
                    // Feedback is reviewed if: approved OR edited (has override)
                    // Editing includes removing (setting to NO COMMENT)
                    const isApproved = feedbackApprovals[k] === true;
                    const isEdited = feedbackOverrides[k] !== undefined;
                    // Not reviewed if neither approved nor edited
                    return !isApproved && !isEdited;
                  }))
                  ? 0.6
                  : 1,
              cursor:
                isLoading ||
                !previousPhaseApproved ||
                (thisPhaseApproved && !thisPhaseDirty) ||
                (feedbackKeys.length > 0 &&
                  feedbackKeys.some((k) => {
                    const isApproved = feedbackApprovals[k] === true;
                    const isEdited = feedbackOverrides[k] !== undefined;
                    const baseVal = feedback[k] || "";
                    const overrideVal = feedbackOverrides[k];
                    const displayVal = overrideVal !== undefined ? overrideVal : baseVal;
                    const trimmedUpper = (displayVal || "").trim().toUpperCase();
                    const isRemoved = trimmedUpper === "" || trimmedUpper.endsWith("NO COMMENT");
                    return !isApproved && !isEdited && !isRemoved;
                  }))
                  ? "not-allowed"
                  : "pointer",
            }}
            disabled={
              isLoading ||
              !previousPhaseApproved ||
              (thisPhaseApproved && !thisPhaseDirty) ||
              (feedbackKeys.length > 0 &&
                feedbackKeys.some((k) => {
                  const isApproved = feedbackApprovals[k] === true;
                  const isEdited = feedbackOverrides[k] !== undefined;
                  const baseVal = feedback[k] || "";
                  const overrideVal = feedbackOverrides[k];
                  const displayVal = overrideVal !== undefined ? overrideVal : baseVal;
                  const trimmedUpper = (displayVal || "").trim().toUpperCase();
                  const isRemoved = trimmedUpper === "" || trimmedUpper.endsWith("NO COMMENT");
                  return !isApproved && !isEdited && !isRemoved;
                }))
            }
          >
            {isLoading
              ? "Processing..."
              : thisPhaseApproved
                ? thisPhaseDirty
                  ? "Save and restart from here"
                  : "Edit to restart from here"
                : "Approve refined letter"}
          </button>
        )}
      </div>
      )}
    </div>
  );
}

// Transform vendor-indexed state to phase-indexed structure with cards containing their state
// Input: phaseState[vendor][phase] = { data: {...}, approved: bool }, phaseEdits[vendor][phase] = {...}
// Output: phases = [{ phase: "background", previous: null, next: <phaseObj>, cards: [{vendor, data, approved, edits}, ...], readyCount, pendingCount }, ...]
function transformToPhaseStructure(vendorsList, phaseState, phaseEdits, setPhaseUpdateTrigger, phaseCounters, setPhaseCounters) {
  const phaseOrder = ["background", "refine"];
  
  // First pass: create all phase objects with cards containing their state
  const phaseObjects = phaseOrder.map((phaseName, index) => {
    // Create cards array - each card owns its state
    const cards = vendorsList.map(vendor => {
      const vendorPhaseState = phaseState[vendor]?.[phaseName] || {};
      const vendorPhaseEdits = phaseEdits[vendor]?.[phaseName] || {};
      return {
        vendor,
        data: vendorPhaseState.data || {},
        approved: vendorPhaseState.approved || false,
        edits: vendorPhaseEdits,
      };
    });
    
    // Get or initialize counters (preserve state across re-renders)
    const existingCounters = phaseCounters && phaseCounters[phaseName];
    const vendorCount = vendorsList.length;
    
    let readyCount = existingCounters?.readyCount ?? 0;
    let pendingCount = existingCounters?.pendingCount ?? vendorCount;
    
    if (!existingCounters) {
      // Initialize counters based on current card states
      const approvedCount = cards.filter(card => card.approved).length;
      pendingCount = vendorCount - approvedCount;
      
      // Count ready cards (have data, not approved)
      readyCount = cards.filter(card => {
        if (card.approved) return false;
        const hasData = !!(card.data && Object.keys(card.data).length > 0);
        const hasUserData = !!Object.keys(card.edits || {}).some(key => {
          const editValue = card.edits[key];
          return editValue && typeof editValue === 'string' && editValue.trim().length > 0;
        });
        return hasData || hasUserData;
      }).length;
      
      // Store initial counters
      setPhaseCounters(prev => ({
        ...prev,
        [phaseName]: { readyCount, pendingCount }
      }));
    }
    
    const phaseObj = {
      phase: phaseName,
      previous: null, // Will be set in second pass
      next: null, // Will be set in second pass
      cards, // Cards with their state - cards own their state
      readyCount, // Number of cards ready for approval
      pendingCount, // Number of cards pending (not approved)
      // Status registration function - updates counters
      // Status parameter IS the card's status - no need to look it up
      registerStatus: (vendor, status) => {
        switch (status) {
          case CardStatus.PENDING:
            // Card is loading - decrement readyCount if it was ready (but don't change pendingCount)
            if (phaseObj.readyCount > 0) {
              phaseObj.readyCount--;
            }
            break;
          case CardStatus.READY:
            // Card has data and is ready - increment readyCount
            phaseObj.readyCount++;
            break;
          case CardStatus.APPROVED:
            // Card is approved - decrement both counters
            if (phaseObj.readyCount > 0) {
              phaseObj.readyCount--;
            }
            if (phaseObj.pendingCount > 0) {
              phaseObj.pendingCount--;
            }
            break;
          default:
            // Unknown status - ignore
            break;
        }
        
        // Update stored counters
        setPhaseCounters(prev => ({
          ...prev,
          [phaseName]: { readyCount: phaseObj.readyCount, pendingCount: phaseObj.pendingCount }
        }));
        
        // Force re-render
        setPhaseUpdateTrigger(prev => prev + 1);
      },
      // Function to approve all ready cards (have data, not approved)
      // Look up from cards array
      approveAllReady: () => {
        const approvedVendors = [];
        phaseObj.cards.forEach(card => {
          if (!card.approved) {
            const hasData = !!(card.data && Object.keys(card.data).length > 0);
            const hasUserData = !!Object.keys(card.edits || {}).some(key => {
              const editValue = card.edits[key];
              return editValue && typeof editValue === 'string' && editValue.trim().length > 0;
            });
            // Ready if has data - if loading, approve will be no-op
            if (hasData || hasUserData) {
              approvedVendors.push(card.vendor);
            }
          }
        });
        
        const approvedCount = approvedVendors.length;
        
        // Update counters: readyCount becomes 0, pendingCount decreases by approvedCount
        phaseObj.readyCount = 0; // All ready ones were approved
        phaseObj.pendingCount = Math.max(0, phaseObj.pendingCount - approvedCount);
        
        // Update stored counters
        setPhaseCounters(prev => ({
          ...prev,
          [phaseName]: { readyCount: phaseObj.readyCount, pendingCount: phaseObj.pendingCount }
        }));
        
        // Force re-render
        setPhaseUpdateTrigger(prev => prev + 1);
        
        return approvedVendors;
      }
    };
    
    return phaseObj;
  });
  
  // Second pass: link phase objects with actual object references
  phaseObjects.forEach((phaseObj, index) => {
    phaseObj.previous = index > 0 ? phaseObjects[index - 1] : null;
    phaseObj.next = index < phaseObjects.length - 1 ? phaseObjects[index + 1] : null;
  });
  
  return phaseObjects;
}

export default function PhaseFlow({
  vendorsList,
  phaseState,
  phaseEdits,
  errors, // Deprecated - cards manage their own errors
  onEditChange,
  onApprove,
  onApproveAll,
  onRerunFromBackground,
  sessionId, // Required for cards to make API calls
  // Form data for extraction phase
  companyName,
  jobTitle,
  location,
  language,
  salary,
  requirements,
  onCompanyNameChange,
  onJobTitleChange,
  onLocationChange,
  onLanguageChange,
  onSalaryChange,
  onRequirementsChange,
  onApproveExtraction,
  extractionLoading,
  extractionError,
}) {
  // Helper function to calculate phase cost and running total for a vendor/phase
  const calculateCosts = (vendor, phaseName) => {
    const cardData = phaseState[vendor]?.[phaseName]?.data || {};
    const currentCumulativeCost = phaseState[vendor]?.cost ?? 0;
    
    // Use cost from API response data if available, otherwise use cumulative cost
    const cumulativeCost = cardData.cost ?? currentCumulativeCost;
    
    // Calculate phase cost by subtracting previous phase's cumulative cost
    let phaseCost = cumulativeCost;
    if (phaseName === "refine") {
      // Refine phase includes both draft and refine steps
      // The refine.data.cost is cumulative (background + draft + refine)
      // background.data.cost is just background cost
      // So refine phase cost = refine cumulative - background cost = draft + refine
      const backgroundData = phaseState[vendor]?.background?.data || {};
      const backgroundCost = backgroundData.cost ?? 0;
      phaseCost = cumulativeCost - backgroundCost;
    } else if (phaseName === "background") {
      // Background phase: cost is just the cumulative cost at this point
      phaseCost = cumulativeCost;
    }
    
    return {
      phaseCost: Math.max(0, phaseCost), // Ensure non-negative
      runningTotal: cumulativeCost,
    };
  };
  const [collapsedPhases, setCollapsedPhases] = useState({
    background: false, // first phase starts open
    refine: true,
  });
  
  // Track phase updates to trigger re-renders when status changes
  const [phaseUpdateTrigger, setPhaseUpdateTrigger] = useState(0);
  
  // Store counters per phase (preserved across re-renders)
  // readyCount: number of cards ready for approval (starts at 0, incremented when card becomes ready)
  // pendingCount: number of cards pending (starts at vendor count, decremented on error/approval)
  const [phaseCounters, setPhaseCounters] = useState({}); // { phaseName: { readyCount: 0, pendingCount: vendorCount } }
  
  // Transform vendor-indexed state to phase-indexed structure
  // Each phase contains all vendor states for that phase
  const phases = transformToPhaseStructure(vendorsList, phaseState, phaseEdits, setPhaseUpdateTrigger, phaseCounters, setPhaseCounters);
  
  // Callback for cards to report their loading state
  const onCardLoadingChange = (vendor, phase, loading) => {
    setCardLoadingStates(prev => ({
      ...prev,
      [`${vendor}-${phase}`]: loading,
    }));
  };

  // Cards manage their own state - no need to track here

  // Track previous approval states to only auto-collapse on transition
  const prevApprovalStatesRef = useRef({}); // { phaseName: allApproved }

  // Auto-collapse/expand phases based on previous phase completion
  useEffect(() => {
    setCollapsedPhases((prev) => {
      const next = { ...prev };
      let changed = false;

      phases.forEach(phaseObj => {
        // Background phase: no previous phase, so it manages itself
        if (!phaseObj.previous) {
          // Background collapses when all its cards are approved
          const allApproved = phaseObj.cards.length > 0 && phaseObj.cards.every(card => card.approved);
          const prevAllApproved = prevApprovalStatesRef.current[phaseObj.phase] || false;
          
          // Only auto-collapse on transition from "not all approved" to "all approved"
          // Don't re-collapse if user manually expanded it
          if (allApproved && !prevAllApproved && !prev[phaseObj.phase]) {
            next[phaseObj.phase] = true;
            changed = true;
          }
          
          // Update ref for next comparison
          prevApprovalStatesRef.current[phaseObj.phase] = allApproved;
        } else {
          // Other phases: expand when previous phase is fully approved
          const previousPhase = phaseObj.previous;
          const previousAllApproved = previousPhase.cards.length > 0 && previousPhase.cards.every(card => card.approved);
          if (previousAllApproved && prev[phaseObj.phase]) {
            next[phaseObj.phase] = false;
            changed = true;
          }
        }
      });

      return changed ? next : prev;
    });
  }, [phases, phaseState, vendorsList]);

  const saveFeedbackOverride = (vendor, key, val) => {
    if (!vendor || !key) return;
    // Look up card from refine phase's cards array
    const refinePhase = phases.find(p => p.phase === "refine");
    const card = refinePhase?.cards.find(c => c.vendor === vendor);
    const current = card?.edits?.feedback_overrides || {};
    const next = { ...current, [key]: val };
    onEditChange(vendor, "refine", "feedback_overrides", next);
  };

  // Add rendering configuration to phase objects
  phases.forEach(phaseObj => {
    const phaseName = phaseObj.phase;
    const title = phaseName === "background" ? "Background" : "Refine";
    
    // Visibility: phase is visible if no previous phase OR at least one vendor in previous phase is approved
    let visible = true;
    if (phaseObj.previous) {
      // Phase becomes visible when first card in previous phase is approved
      const previousHasApproved = phaseObj.previous.cards.some(card => card.approved);
      // Also visible if any card has data in this phase (already started)
      const hasData = phaseObj.cards.some(card => {
        return card.data && Object.keys(card.data).length > 0;
      });
      visible = previousHasApproved || hasData;
    }
    
    phaseObj.title = title;
    phaseObj.visible = visible;
    phaseObj.collapsed = collapsedPhases[phaseName] || false;
    phaseObj.toggle = () => setCollapsedPhases((prev) => ({ ...prev, [phaseName]: !prev[phaseName] }));
    phaseObj.renderVendor = (vendor) => {
      // Find card in this phase's cards array
      const card = phaseObj.cards.find(c => c.vendor === vendor);
      if (!card) return null;
      
      // Calculate previous phase approval status for this vendor
      const previousPhaseApproved = phaseObj.previous 
        ? (phaseObj.previous.cards.find(c => c.vendor === vendor)?.approved || false)
        : true;
      
      // Calculate if all phases are done for this vendor
      const allPhasesDone = phases.every(p => 
        p.cards.find(c => c.vendor === vendor)?.approved || false
      );
      
      // Calculate costs for this phase
      const costs = calculateCosts(vendor, phaseName);
      
      return (
        <VendorCard
          key={`${phaseName}-${vendor}`}
          vendor={vendor}
          phases={phases}
          phaseObj={phaseObj}
          data={card.data}
          approved={card.approved}
          edits={card.edits}
          previousPhaseApproved={previousPhaseApproved}
          allPhasesDone={allPhasesDone}
          phaseCost={costs.phaseCost}
          runningTotal={costs.runningTotal}
          onEditChange={onEditChange}
          onApprove={onApprove}
          sessionId={sessionId}
          phaseError={errors?.[vendor] || null}
          onStatusChange={(status) => phaseObj.registerStatus?.(vendor, status)}
          onSaveFeedbackOverride={(key, val) => saveFeedbackOverride(vendor, key, val)}
          onRerunFromBackground={onRerunFromBackground}
          companyName={companyName}
          jobTitle={jobTitle}
          location={location}
          language={language}
          salary={salary}
          requirements={requirements}
          onCompanyNameChange={onCompanyNameChange}
          onJobTitleChange={onJobTitleChange}
          onLocationChange={onLocationChange}
          onLanguageChange={onLanguageChange}
          onSalaryChange={onSalaryChange}
          onRequirementsChange={onRequirementsChange}
          onApproveExtraction={onApproveExtraction}
          extractionLoading={extractionLoading}
          extractionError={extractionError}
        />
      );
    };
  });

  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
      {phases.filter((phase) => phase.visible).map((phase) => (
        <PhaseSection
          key={phase.phase}
          title={phase.title}
          collapsed={phase.collapsed}
          onToggle={phase.toggle}
          showApproveAll={phase.cards && phase.cards.length > 0}
          approveAllDisabled={false}
          readyCount={phase.readyCount || 0}
          totalCount={phase.pendingCount || 0}
          onApproveAll={() => {
            // Approve all ready vendors
            const approvedVendors = phase.approveAllReady?.() || [];
            // Call individual approve for each approved vendor
            approvedVendors.forEach(vendor => {
              onApprove(phase.phase, vendor);
            });
            // Also call parent's onApproveAll if provided
            if (onApproveAll) {
              onApproveAll(phase.phase);
            }
          }}
        >
          {vendorsList.map((vendor) => phase.renderVendor(vendor))}
        </PhaseSection>
      ))}
    </div>
  );
}

