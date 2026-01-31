/**
 * PHASED EXECUTION MODEL - ARCHITECTURAL OVERVIEW
 * 
 * This component implements a reactive, "Passive Card" model.
 * 
 * DATA FLOW:
 * 1. Actor (App.jsx): Launches API calls (initial start, approval, or retry).
 * 2. Shelf (cardData): App.jsx populates the 'shelf' for the target phase.
 * 3. Observer (VendorCardWrapper): Detects data on the shelf and renders.
 * 
 * PHASES IN THIS PIPELINE:
 * - BACKGROUND: Corresponds to /api/phases/background/. Approving this calls /api/phases/draft/
 *               to populate the 'refine' shelf.
 * - REFINE: Corresponds to /api/phases/draft/ (displaying draft + feedback). Approving this 
 *           calls /api/phases/refine/ to generate the final letter.
 * - ASSEMBLY: A separate UI rendered by App.jsx that holds the result of the refine call.
 * 
 * KEY RULES:
 * - NO CARD FETCHES ITS OWN DATA: VendorCardWrapper has no fetch logic.
 * - LOADING STATE: If a phase is 'approved' but its shelf is empty, the 
 *   card automatically shows "Loading...".
 * - RE-RENDERING: App.jsx triggers a re-render of PhaseFlow whenever 
 *   the shelf is updated.
 */
import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { createPortal } from "react-dom";
import { phases as phaseModules } from "./phases";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { useTranslation } from "../utils/useTranslation";
import LanguageSelector from "./LanguageSelector";

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

function EditableField({ label, value, minHeight = 120, placeholder, onSave, disabled = false, fieldId, translation }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");

  useEffect(() => {
    if (!editing) {
      setDraft(value || "");
    }
  }, [value, editing]);

  // Reset translation when source text changes
  useEffect(() => {
    if (translation && fieldId) {
      translation.resetFieldTranslation(fieldId, value || "");
    }
  }, [value, fieldId, translation]);

  // Get displayed text (translated or original)
  const displayedText = translation && fieldId
    ? translation.getTranslatedText(fieldId, value || "")
    : (value || placeholder || "");

  // Get field-specific view language
  const fieldViewLanguage = translation && fieldId
    ? translation.getFieldViewLanguage(fieldId)
    : "source";

  // Handle field-specific language change
  const handleFieldLanguageChange = async (code) => {
    if (!translation || !fieldId) return;
    
    translation.setFieldViewLanguage(fieldId, code);
    
    if (code === "source") {
      return; // No translation needed for source
    }
    
    const sourceText = value || "";
    if (sourceText) {
      await translation.translateField(fieldId, sourceText, code);
    }
  };

  return (
    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 12 }}>
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
        <div style={{ position: "relative" }}>
          {translation && fieldId && (
            <div style={{ 
              position: "absolute", 
              right: -1, 
              top: -10, 
              zIndex: 10,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderLeft: "none",
              borderTopRightRadius: 4,
              borderBottomRightRadius: 4,
              padding: "2px 2px 2px 4px",
            }}>
              <LanguageSelector
                languages={translation.languages}
                viewLanguage={fieldViewLanguage}
                onLanguageChange={handleFieldLanguageChange}
                hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
                disabled={disabled}
                isTranslating={translation.isTranslating[fieldId] || false}
                size="tiny"
              />
            </div>
          )}
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
            {displayedText}
          </div>
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
  fieldId,
  translation,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");

  useEffect(() => {
    if (!editing) {
      setDraft(value || "");
    }
  }, [value, editing]);

  // Reset translation when source text changes
  useEffect(() => {
    if (translation && fieldId) {
      translation.resetFieldTranslation(fieldId, value || "");
    }
  }, [value, fieldId, translation]);

  // Get displayed text (translated or original)
  const displayedText = translation && fieldId
    ? translation.getTranslatedText(fieldId, value || "")
    : (value || placeholder || "");

  // Get field-specific view language
  const fieldViewLanguage = translation && fieldId
    ? translation.getFieldViewLanguage(fieldId)
    : "source";

  // Handle field-specific language change
  const handleFieldLanguageChange = async (code) => {
    if (!translation || !fieldId) return;
    
    translation.setFieldViewLanguage(fieldId, code);
    
    if (code === "source") {
      return; // No translation needed for source
    }
    
    const sourceText = value || "";
    if (sourceText) {
      await translation.translateField(fieldId, sourceText, code);
    }
  };

  const statusColor = hasContent ? "#2563eb" : "#9ca3af"; // comment presence
  const approveColor = approved ? "#16a34a" : "#9ca3af";

  const feedbackDescription = FEEDBACK_DESCRIPTIONS[label] || `Feedback about ${label.replace(/_/g, ' ')}.`;

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid #e5e7eb", borderRadius: 6, background: "#f9fafb" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
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
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {hasContent && (
              <button 
                type="button" 
                onClick={() => onSave("NO COMMENT")} 
                style={{ 
                  fontSize: 11, 
                  padding: "2px 6px",
                  border: "1px solid #dc2626",
                  background: "#fff",
                  color: "#dc2626",
                  cursor: "pointer",
                  borderRadius: 3,
                }}
              >
                Remove
              </button>
            )}
            <button 
              type="button" 
              onClick={() => setEditing(true)} 
              style={{ 
                fontSize: 11, 
                padding: "2px 6px",
                borderRadius: 3,
              }}
            >
              Edit
            </button>
            {isModified ? (
              <span
                style={{
                  fontSize: 11,
                  padding: "2px 6px",
                  border: "1px solid #fca5a5",
                  background: "#fff1f2",
                  color: "#b91c1c",
                  borderRadius: 3,
                }}
              >
                Edited
              </span>
            ) : (
              <button
                type="button"
                onClick={onApprove}
                style={{
                  fontSize: 11,
                  padding: "2px 6px",
                  border: "1px solid #16a34a",
                  background: approved ? "#dcfce7" : "#fff",
                  color: "#166534",
                  cursor: approved ? "default" : "pointer",
                  borderRadius: 3,
                }}
                disabled={approved}
              >
                {approved ? "Approved" : "Approve"}
              </button>
            )}
          </div>
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
        <div style={{ position: "relative" }}>
          {translation && fieldId && (
            <div style={{ 
              position: "absolute", 
              right: -1, 
              top: -10, 
              zIndex: 10,
              background: "#fff",
              border: "1px solid #e5e7eb",
              borderLeft: "none",
              borderTopRightRadius: 4,
              borderBottomRightRadius: 4,
              padding: "2px 2px 2px 4px",
            }}>
              <LanguageSelector
                languages={translation.languages}
                viewLanguage={fieldViewLanguage}
                onLanguageChange={handleFieldLanguageChange}
                hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
                disabled={false}
                isTranslating={translation.isTranslating[fieldId] || false}
                size="tiny"
              />
            </div>
          )}
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
            {displayedText}
          </div>
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
    { key: "company_name", label: "Company", placeholder: "Detected company name" },
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

// VendorCardWrapper - handles data from the "shelf" (pre-fetched by previous phase)
function VendorCardWrapper({
  phaseName,
  vendor,
  phaseObj,
  phaseModule,
  sessionId,
  onEditChange,
  onApprove,
  onSaveFeedbackOverride,
  onRerunFromBackground,
  onPhaseComplete,
  triggerUpdate,
  onExpand,
  isExpanded,
  onCloseExpand,
  useOverlayWidth,
  onAfterApproveInExpanded,
}) {
  // Get previous phase data (to check if we SHOULD be loading)
  const previousPhaseApproved = phaseObj.previous ? phaseObj.previous.approvedVendors.has(vendor) : true;
  
  // Get data for THIS phase from the shelf
  const currentPhaseData = phaseObj.cardData?.[vendor] || null;
  
  // Local state for UI only
  const [error, setError] = React.useState(null);

  // Sync currentPhaseData to VendorCard
  // We don't need a complex useEffect with fetch anymore.
  // The card is purely a consumer of phaseObj.cardData[vendor].
  
  // Status logic:
  // - "error" if we have an error (takes priority)
  // - "success" if we have data (already processed)
  // - "loading" only if previous phase is approved AND we don't have data (triggers API call)
  // - "idle" otherwise (waiting for previous phase or no data)
  // Note: When navigating back from assembly, data should already be in shelf, so status will be "success"
  const status = error
    ? "error"
    : currentPhaseData 
      ? "success" 
      : (previousPhaseApproved ? "loading" : "idle");

  return (
    <VendorCard
      key={`${phaseName}-${vendor}`}
      vendor={vendor}
      phases={[]} 
      phaseObj={phaseObj}
      previousPhaseApproved={previousPhaseApproved}
      allPhasesDone={false}
      data={currentPhaseData}
      status={status}
      error={error}
      onEditChange={onEditChange}
      onApprove={onApprove}
      sessionId={sessionId}
      onStatusChange={useOverlayWidth ? undefined : (status) => phaseObj.registerStatus?.(vendor, status)}
      onSaveFeedbackOverride={(key, val) => {
        // Use the onSaveFeedbackOverride prop (which is the saveFeedbackOverride callback from parent)
        if (typeof onSaveFeedbackOverride === 'function') {
          onSaveFeedbackOverride(vendor, key, val);
        } else {
          // Fallback: use onEditChange if available
          if (onEditChange) {
            onEditChange(vendor, "refine", "feedback_overrides", { [key]: val });
          }
        }
      }}
      onRerunFromBackground={onRerunFromBackground}
      onPhaseComplete={(vendor, phase, completionData) => {
        // Completion data is already handled by the onApprove caller (App.jsx)
        // which populates the shelf. We just need to ensure the current phase
        // is marked as approved and downstream is cleared.
        
        // Mark current phase as approved
        if (phaseObj.approvedVendors) {
          phaseObj.approvedVendors.add(vendor);
        }

        // Clear downstream (App.jsx also handles this via populatePhaseShelf re-render,
        // but we do it here for extra safety)
        let current = phaseObj.next;
        while (current) {
          // If we just got data for the immediate next phase, don't clear its shelf
          if (current !== phaseObj.next && current.cardData) delete current.cardData[vendor];
          if (current.approvedVendors) current.approvedVendors.delete(vendor);
          current = current.next;
        }

        if (triggerUpdate) triggerUpdate();
        if (onPhaseComplete) onPhaseComplete(vendor, phase, completionData);
      }}
      setStatus={() => {}} // No-op, status is computed
      setData={() => {}}   // No-op, data comes from shelf
      setError={setError}
      onExpand={onExpand}
      isExpanded={isExpanded}
      onCloseExpand={onCloseExpand}
      useOverlayWidth={useOverlayWidth}
      onAfterApproveInExpanded={onAfterApproveInExpanded}
    />
  );
}

function VendorCard({
  vendor,
  // Phase structure - for navigation only, not for state
  phases, // Array of phase objects
  phaseObj, // The phase object this card belongs to: { phase: "background", previous: null, next: <phaseObj>, ... }
  // Data from outer component
  data = null, // Data from API (passed from wrapper)
  status = "idle", // "idle" | "loading" | "success" | "error"
  error = null, // Error message if status === "error"
  previousPhaseApproved = true, // Whether the previous phase is approved for this vendor
  allPhasesDone = false, // Whether all phases are done for this vendor
  onEditChange,
  onSaveFeedbackOverride,
  onApprove,
  sessionId, // Required: session ID for API calls
  onStatusChange, // Callback to register status with phase: (status: CardStatus) => void
  onRerunFromBackground,
  disabled = false,
  // Callbacks for when card completes phases (to update parent state)
  onPhaseComplete, // (vendor, phase, data) => void - called when phase completes
  // State setters from wrapper (for rerun functionality)
  setStatus,
  setData,
  setError,
  onExpand,
  isExpanded,
  onCloseExpand,
  useOverlayWidth,
  onAfterApproveInExpanded,
}) {
  // This card knows which phase it belongs to
  const cardPhase = phaseObj?.phase || null;
  
  // Card owns its approval and edit state (but not data fetching)
  const [approved, setApproved] = React.useState(false);
  const [edits, setEdits] = React.useState({});
  const [phaseCost, setPhaseCost] = React.useState(0);
  const [runningTotal, setRunningTotal] = React.useState(0);
  
  // Initialize edits and costs when data arrives
  React.useEffect(() => {
    if (data && status === "success") {
      try {
        // Initialize edits with data values using phase module
        const phaseModule = phaseModules[cardPhase];
        if (phaseModule && phaseModule.initializeEditsFromData) {
          const initialEdits = phaseModule.initializeEditsFromData(data);
          if (initialEdits && Object.keys(initialEdits).length > 0) {
            setEdits(initialEdits);
          }
        }
        
        // Update costs
        if (data.cost !== undefined) {
          setRunningTotal(data.cost);
          setPhaseCost(data.cost);
        }
      } catch (e) {
        console.error(`Error initializing edits from data for ${cardPhase}:`, e, data);
        setError(`Failed to parse ${cardPhase} data: ${e.message}`);
      }
    }
  }, [data, status, cardPhase]);
  
  // Use data from props
  const cardPhaseData = data || {};
  const isCardPhaseApproved = approved;
  const cardPhaseEdits = edits;
  const isLoading = status === "loading";
  const cardError = error;
  
  // Card-specific UI state
  const [selectedFeedbackTab, setSelectedFeedbackTab] = useState(null);
  const [feedbackApprovals, setFeedbackApprovals] = useState({});
  const [collapsed, setCollapsed] = useState(false);
  
  // Translation support for this card
  const translation = useTranslation();
  
  // Track current registered status to avoid infinite loops
  const registeredStatusRef = useRef(null);
  
  // Register status changes with phase (only when status actually changes)
  React.useEffect(() => {
    if (!cardPhase || !onStatusChange) return;
    
    const hasData = data !== null && Object.keys(data).length > 0;
    
    let newStatus = null;
    if (approved) {
      newStatus = CardStatus.APPROVED;
    } else if (status === "loading") {
      newStatus = CardStatus.PENDING;
    } else if (status === "error") {
      // Errors are treated as pending - user needs to retry
      newStatus = CardStatus.PENDING;
    } else if (status === "success" && hasData) {
      newStatus = CardStatus.READY;
    }
    
    // Only register if status changed
    if (newStatus && newStatus !== registeredStatusRef.current) {
      registeredStatusRef.current = newStatus;
      onStatusChange(newStatus);
    }
  }, [status, data, approved, cardPhase, onStatusChange]);
  
  // Get phase module
  const phaseModule = phaseModules[cardPhase];
  
  // Initialize refine-specific feedback state from phase module
  React.useEffect(() => {
    if (cardPhase && phaseModule?.initializeFeedbackFromData && data) {
      try {
        const feedbackData = phaseModule.initializeFeedbackFromData(data);
        if (feedbackData && feedbackData.feedbackKeys && feedbackData.feedbackKeys.length > 0 && !selectedFeedbackTab) {
          setSelectedFeedbackTab(feedbackData.feedbackKeys[0]);
          // Initialize approvals as all unreviewed
          const initialApprovals = {};
          feedbackData.feedbackKeys.forEach(k => {
            initialApprovals[k] = false;
          });
          setFeedbackApprovals(initialApprovals);
        }
      } catch (e) {
        console.error(`Error initializing feedback from data for ${cardPhase}:`, e, data);
        // Don't set error here - feedback is optional, just log it
      }
    }
  }, [cardPhase, data, selectedFeedbackTab, phaseModule]);
  
  // Get feedback data using phase module (with error handling)
  let feedbackData = null;
  let feedback = {};
  let feedbackKeys = [];
  try {
    if (cardPhase && phaseModule?.initializeFeedbackFromData && data) {
      feedbackData = phaseModule.initializeFeedbackFromData(data);
      feedback = feedbackData?.feedback || {};
      feedbackKeys = feedbackData?.feedbackKeys || [];
    }
  } catch (e) {
    console.error(`Error getting feedback data for ${cardPhase}:`, e, data);
    // Fallback to empty feedback
    feedback = {};
    feedbackKeys = [];
  }
  
  // Handle edit changes - update local edits state
  const handleEditChange = (field, value) => {
    setEdits(prev => ({
      ...prev,
      [field]: value,
    }));
    // Also notify parent if callback provided
    if (onEditChange) {
      onEditChange(vendor, cardPhase, field, value);
    }
  };

  // Check if this card's phase data is dirty (edits differ from data) - phase-agnostic
  const thisPhaseDirty = phaseObj ? Object.keys(cardPhaseEdits).some(key => {
    const editValue = cardPhaseEdits[key];
    const dataValue = cardPhaseData[key];
    
    // Handle objects (like feedback_overrides) - check if they differ in content
    if (editValue && typeof editValue === 'object') {
      const editKeys = Object.keys(editValue);
      const dataKeys = dataValue && typeof dataValue === 'object' ? Object.keys(dataValue) : [];
      
      if (editKeys.length === 0 && dataKeys.length === 0) return false;
      
      // For simple objects like feedback_overrides, check if values differ
      if (editKeys.length !== dataKeys.length) return true;
      return editKeys.some(k => editValue[k] !== dataValue[k]);
    }
    
    const editStr = (editValue ?? '').toString().trim();
    const dataStr = (dataValue ?? '').toString().trim();
    return editStr !== dataStr;
  }) : false;
  
  // Check if all phases are done (for "done" state) - use prop
  const isDone = allPhasesDone;
  
  // Get feedback overrides - phase-specific
  const feedbackOverrides = feedbackData ? (edits?.feedback_overrides || {}) : {};
  const activeFeedbackKey = selectedFeedbackTab || feedbackKeys[0] || null;
  
  // Handle feedback override save
  const handleSaveFeedbackOverride = (key, val) => {
    const currentOverrides = edits?.feedback_overrides || {};
    const updatedOverrides = { ...currentOverrides, [key]: val };
    handleEditChange("feedback_overrides", updatedOverrides);
    // Also notify parent if callback provided
    if (onSaveFeedbackOverride) {
      onSaveFeedbackOverride(key, val);
    }
  };

  // Get findNextUnseenFeedback from phase module (refine-specific)
  const findNextUnseenFeedback = phaseModule?.findNextUnseenFeedback || (() => null);
  
  // Auto-collapse when done
  useEffect(() => {
    if (isDone && !collapsed) {
      setCollapsed(true);
    }
  }, [isDone, collapsed]);
  
  // Phase-agnostic check: show loading UI when loading and no data yet
  // When re-running, old data is cleared so we go back to loading state
  const hasPhaseData = cardPhase && data !== null && Object.keys(data).length > 0;
  const isLoadingWithoutData = status === "loading" && !hasPhaseData && !approved;
  
  // Compute ready state - use phase module function
  const readyForApproval = React.useMemo(() => {
    if (!cardPhase || !phaseModule?.computeReadyForApproval) {
      // Fallback for phases without computeReadyForApproval
      if (isLoading) return false;
      if (approved && !thisPhaseDirty) return false;
      return true;
    }
    return phaseModule.computeReadyForApproval({
      isLoading,
      approved,
      thisPhaseDirty,
      previousPhaseApproved,
      feedbackKeys,
      feedbackApprovals,
      feedbackOverrides,
      feedback,
    });
  }, [isLoading, approved, thisPhaseDirty, cardPhase, previousPhaseApproved, feedbackKeys, feedbackApprovals, feedbackOverrides, feedback, phaseModule]);

  // Helper to check if any field has translation for a language
  const hasAnyTranslation = useCallback((code) => {
    if (cardPhase === "background") {
      return translation.hasTranslation("company_report");
    } else if (cardPhase === "refine") {
      return translation.hasTranslation("draft_letter") || 
             feedbackKeys.some(k => translation.hasTranslation(`feedback_${k}`));
    }
    return false;
  }, [cardPhase, translation, feedbackKeys]);

  // Handle language change
  const handleLanguageChange = useCallback(async (code) => {
    // Set view language immediately
    translation.setViewLanguage(code);
    
    if (code === "source") {
      return; // No translation needed for source
    }
    
    // Translate all fields in this card if not already cached
    if (cardPhase === "background" && cardPhaseData.company_report) {
      const sourceText = cardPhaseEdits.company_report ?? cardPhaseData.company_report ?? "";
      if (sourceText) {
        await translation.translateField("company_report", sourceText, code);
      }
    } else if (cardPhase === "refine") {
      // Translate draft and all feedback fields independently in parallel
      const translationPromises = [];
      
      // Translate draft independently
      const draftText = cardPhaseEdits.draft_letter ?? cardPhaseData.draft_letter ?? "";
      if (draftText) {
        translationPromises.push(
          translation.translateField("draft_letter", draftText, code)
        );
      }
      
      // Translate each feedback field independently
      for (const key of feedbackKeys) {
        const feedbackValue = feedbackOverrides[key] ?? feedback[key] ?? "";
        if (feedbackValue) {
          translationPromises.push(
            translation.translateField(`feedback_${key}`, feedbackValue, code)
          );
        }
      }
      
      // Execute all translations in parallel
      await Promise.all(translationPromises);
    }
  }, [cardPhase, cardPhaseData, cardPhaseEdits, translation, feedbackKeys, feedbackOverrides, feedback]);

  const effectiveCardStyle = useOverlayWidth
    ? { ...cardStyle, width: "100%", minWidth: 0, minHeight: 0, flex: "1 1 auto", maxWidth: "none" }
    : cardStyle;

  return (
    <div style={{ ...effectiveCardStyle, opacity: disabled ? 0.6 : 1, pointerEvents: disabled ? "none" : "auto" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 8, flexWrap: "wrap" }}>
        <h4 style={{ margin: 0, flex: 1, textTransform: "capitalize" }}>{vendor}</h4>
        {onExpand && !isExpanded && (
          <button
            type="button"
            onClick={onExpand}
            title="Expand to 80% width"
            style={{
              fontSize: 12,
              padding: "2px 8px",
              background: "var(--panel-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            Expand
          </button>
        )}
        {isExpanded && onCloseExpand && (
          <button
            type="button"
            onClick={onCloseExpand}
            title="Close expanded view"
            style={{
              fontSize: 12,
              padding: "2px 8px",
              background: "var(--panel-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            × Close
          </button>
        )}
        {isDone && (
          <button onClick={() => setCollapsed(!collapsed)} style={{ fontSize: 12, padding: "4px 8px" }}>
            {collapsed ? "Expand" : "Collapse"}
          </button>
        )}
      </div>
      
      {/* Cost and Translation bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8, gap: 8, flexWrap: "wrap" }}>
        {(phaseCost > 0 || runningTotal > 0) && (
          <div style={{ fontSize: "11px", color: "var(--secondary-text-color)", whiteSpace: "nowrap" }}>
            ${phaseCost.toFixed(4)} <span style={{ fontSize: "10px", opacity: 0.8 }}>(Total: ${runningTotal.toFixed(4)})</span>
          </div>
        )}
        {/* Only show card-level language selector for phases without per-field selectors */}
        {/* Background and refine phases have per-field selectors, so hide card-level selector */}
        {cardPhase !== "refine" && cardPhase !== "background" && (
          <LanguageSelector
            languages={translation.languages}
            viewLanguage={translation.viewLanguage}
            onLanguageChange={handleLanguageChange}
            hasTranslation={hasAnyTranslation}
            disabled={isLoading}
            isTranslating={translation.isAnyTranslating}
            size="small"
          />
        )}
      </div>
      {/* Translation errors */}
      {Object.keys(translation.translationErrors).length > 0 && (
        <div style={{ color: "var(--error-text)", fontSize: "12px", marginBottom: 8 }}>
          {Object.values(translation.translationErrors)[0]}
        </div>
      )}

      {isLoadingWithoutData && (
        <div style={{ padding: 6, color: "#6b7280", fontSize: 12 }}>
          Loading...
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
        {/* Render content for this card's phase using phase module */}
        {cardPhase && phaseModule?.renderContent && (
          phaseModule.renderContent({
            EditableField,
            EditableFeedback,
            cardPhaseEdits,
            cardPhaseData,
            handleEditChange,
            isLoading,
            previousPhaseApproved,
            approved,
            phaseObj,
            cardPhase,
            vendor,
            feedback,
            feedbackKeys,
            feedbackOverrides,
            activeFeedbackKey,
            feedbackApprovals,
            setSelectedFeedbackTab,
            setFeedbackApprovals,
            findNextUnseenFeedback: (currentKey, approvals, overrides, feedbackData) => 
              findNextUnseenFeedback(currentKey, approvals, overrides, feedbackData, feedbackKeys),
            handleSaveFeedbackOverride,
            translation,
          })
        )}
      </div>
      )}

      {!isLoadingWithoutData && (
      <div style={buttonBarStyle}>
        {cardPhase && phaseModule && (
          <button
            onClick={async () => {
              // If already approved (and not dirty/re-running), do nothing.
              // This is a safety check against double-clicks if the button isn't disabled fast enough.
              if (approved && !thisPhaseDirty) return;

              // Clear any previous error when retrying
              if (error) {
                setError(null);
              }
              
              // When re-running (has data but dirty), clear data and set loading
              if (hasPhaseData && thisPhaseDirty) {
                setStatus("loading");
                setData(null);
                if (onStatusChange) onStatusChange(CardStatus.PENDING);
              }
              
              try {
                // Call parent's approve handler - this triggers the API and returns data for the next phase
                if (onApprove) {
                  // Mark as approved locally IMMEDIATELY
                  setApproved(true);
                  // Notify parent IMMEDIATELY that this card is approved
                  // This will cause the next phase's card to mount in "Loading" state
                  if (onPhaseComplete) {
                    onPhaseComplete(vendor, cardPhase, null);
                  }
                  // Switch to next card immediately (don't wait for API) so the slow call doesn't block UX
                  if (onAfterApproveInExpanded) {
                    onAfterApproveInExpanded();
                  }

                  const nextPhaseData = await onApprove(cardPhase, vendor, cardPhaseEdits);
                  // Handle 202 heartbeat response - request is still processing
                  if (nextPhaseData === null) {
                    // Request is still in flight (got 202), don't notify of data yet
                    // The original request will complete and update state via the effect
                    console.log(`Phase ${cardPhase} for ${vendor} still processing (heartbeat)`);
                    return; 
                  }
                  // Notify parent AGAIN when data actually arrives
                  // The next phase card will pick this up and stop its own loading state
                  if (onPhaseComplete && nextPhaseData) {
                    onPhaseComplete(vendor, cardPhase, nextPhaseData);
                  }
                }
              } catch (e) {
                setError(e.message || String(e));
                // Status is computed by wrapper based on error state
                setApproved(false); // Revert approval on error
              }
            }}
            disabled={!readyForApproval || (approved && !thisPhaseDirty)}
            style={{
              opacity: readyForApproval ? 1 : 0.6,
              cursor: readyForApproval ? "pointer" : "not-allowed",
            }}
          >
            {isLoading
              ? "Processing..."
              : approved
                ? thisPhaseDirty
                  ? "Save and restart from here"
                  : "Approved"
                : "Approve"}
          </button>
        )}
        {cardPhase && phaseModule?.renderAdditionalButtons && (
          phaseModule.renderAdditionalButtons({
            isDone,
            cardPhase,
            collapsed,
            onRerunFromBackground,
            vendor,
          })
        )}
      </div>
      )}
    </div>
  );
}

// Transform to phase-indexed structure - cards now own their state, so we just create phase objects
// Output: phases = [{ phase: "background", previous: null, next: <phaseObj>, readyCount, pendingCount }, ...]
function transformToPhaseStructure(vendorsList, setPhaseUpdateTrigger, phaseCounters, setPhaseCounters) {
  // Use a stable phase order - "draft" phase was removed, logic merged into refine
  const phaseOrder = ["background", "refine"];
  
  // First pass: create all phase objects - cards will own their own state
  const phaseObjects = phaseOrder.map((phaseName, index) => {
    
    // Get or initialize counters (preserve state across re-renders)
    const existingCounters = phaseCounters && phaseCounters[phaseName];
    const vendorCount = vendorsList.length;
    
    let readyCount = existingCounters?.readyCount ?? 0;
    let pendingCount = existingCounters?.pendingCount ?? vendorCount;
    
    if (!existingCounters) {
      // Initialize counters - all cards start as pending
      pendingCount = vendorCount;
      readyCount = 0;
      
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
      readyCount, // Number of cards ready for approval
      pendingCount, // Number of cards pending (not approved)
      // Store completion data per vendor (for next phase to access)
      cardData: {}, // { vendor: completionData }
      approvedVendors: new Set(), // Track which vendors are approved in this phase
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
      // Function to approve all ready cards - cards will handle their own approval
      // This is now just a callback that can be used by the phase section
      approveAllReady: () => {
        // Cards will handle their own approval via onApprove callback
        // Return empty array - parent will need to track which vendors to approve
        return [];
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
  onEditChange,
  onApprove,
  onApproveAll,
  onRerunFromBackground,
  // Required for cards to make API calls
  sessionId, 
  // Callback for when a phase completes
  onPhaseComplete, // (vendor, phase, data) => void
  // Callback to register the phase objects with the parent
  onRegisterPhases, // (phases) => void
}) {
  const [collapsedPhases, setCollapsedPhases] = useState({
    background: false, // first phase starts open
    refine: true,
  });

  const [expandedCard, setExpandedCard] = useState(null); // { phase, vendor } | null
  const toggleExpand = useCallback((phase, vendor) => {
    setExpandedCard((prev) =>
      prev?.phase === phase && prev?.vendor === vendor ? null : { phase, vendor }
    );
  }, []);
  const closeExpand = useCallback(() => setExpandedCard(null), []);
  
  // Track phase updates to trigger re-renders when status changes
  const [phaseUpdateTrigger, setPhaseUpdateTrigger] = useState(0);
  
  // Store counters per phase (preserved across re-renders)
  // readyCount: number of cards ready for approval (starts at 0, incremented when card becomes ready)
  // pendingCount: number of cards pending (starts at vendor count, decremented on error/approval)
  const [phaseCounters, setPhaseCounters] = useState({}); // { phaseName: { readyCount: 0, pendingCount: vendorCount } }
  
  // Use ref to store stable phase objects - only recreate when vendorsList length changes
  const phasesRef = useRef(null);
  const vendorsListLengthRef = useRef(vendorsList.length);
  
  if (!phasesRef.current || vendorsListLengthRef.current !== vendorsList.length) {
    phasesRef.current = transformToPhaseStructure(vendorsList, setPhaseUpdateTrigger, phaseCounters, setPhaseCounters);
    vendorsListLengthRef.current = vendorsList.length;
    
    // Notify parent of the new phase structure
    if (onRegisterPhases) {
      // Use setTimeout to avoid updating parent during render
      setTimeout(() => onRegisterPhases(phasesRef.current), 0);
    }
  }
  
  const phases = phasesRef.current;
  
  // Update phase counters in the ref when they change
  useEffect(() => {
    if (phasesRef.current) {
      phasesRef.current.forEach(phaseObj => {
        const phaseName = phaseObj.phase;
        const counters = phaseCounters[phaseName];
        if (counters) {
          phaseObj.readyCount = counters.readyCount;
          phaseObj.pendingCount = counters.pendingCount;
        }
      });
    }
  }, [phaseCounters]);

  const expandedPhase = expandedCard ? phases.find((p) => p.phase === expandedCard.phase) : null;
  const vendorIdx = expandedCard ? vendorsList.indexOf(expandedCard.vendor) : -1;
  const isFirstVendor = vendorIdx <= 0;
  const isLastVendor = vendorIdx >= vendorsList.length - 1;
  const nextPhase = expandedPhase?.next ?? null;
  const hasNextPhase = !!nextPhase;

  const goLeft = useCallback(() => {
    if (!expandedCard || isFirstVendor) return;
    const idx = vendorsList.indexOf(expandedCard.vendor);
    if (idx <= 0) return;
    setExpandedCard({ phase: expandedCard.phase, vendor: vendorsList[idx - 1] });
  }, [expandedCard, vendorsList, isFirstVendor]);

  const goRight = useCallback(() => {
    if (!expandedCard) return;
    const idx = vendorsList.indexOf(expandedCard.vendor);
    if (idx < 0) return;
    if (idx < vendorsList.length - 1) {
      setExpandedCard({ phase: expandedCard.phase, vendor: vendorsList[idx + 1] });
      return;
    }
    if (nextPhase) {
      setExpandedCard({ phase: nextPhase.phase, vendor: vendorsList[0] });
    }
  }, [expandedCard, vendorsList, nextPhase]);

  const onAfterApproveInExpanded = useCallback(() => {
    if (!expandedCard) return;
    const idx = vendorsList.indexOf(expandedCard.vendor);
    if (idx < 0) return;
    if (idx < vendorsList.length - 1) {
      setExpandedCard({ phase: expandedCard.phase, vendor: vendorsList[idx + 1] });
      return;
    }
    if (nextPhase) {
      setExpandedCard({ phase: nextPhase.phase, vendor: vendorsList[0] });
    }
  }, [expandedCard, vendorsList, nextPhase]);

  useEffect(() => {
    if (!expandedCard) return;
    const handler = (e) => {
      const tag = e.target?.tagName?.toLowerCase();
      const ce = e.target?.getAttribute?.("contenteditable") === "true";
      if (tag === "input" || tag === "textarea" || tag === "select" || ce) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goLeft();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goRight();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [expandedCard, goLeft, goRight]);

  // Stabilize saveFeedbackOverride with useCallback
  const saveFeedbackOverride = useCallback((vendor, key, val) => {
    if (!vendor || !key) return;
    // Cards now own their state, so we just notify parent if callback provided
    if (onEditChange) {
      onEditChange(vendor, "refine", "feedback_overrides", { [key]: val });
    }
  }, [onEditChange]);

  // Add rendering configuration to phase objects - use useMemo to stabilize renderVendor
  const memoizedRenderVendors = useMemo(() => {
    const renderFunctions = new Map();
    phases.forEach(phaseObj => {
      const phaseName = phaseObj.phase;
      const phaseModule = phaseModules[phaseName];
      renderFunctions.set(phaseName, (vendor, overlayMode = false) => (
        <VendorCardWrapper
          key={`${phaseName}-${vendor}-wrapper${overlayMode ? "-overlay" : ""}`}
          phaseName={phaseName}
          vendor={vendor}
          phaseObj={phaseObj}
          phaseModule={phaseModule}
          sessionId={sessionId}
          onEditChange={onEditChange}
          onApprove={onApprove}
          onSaveFeedbackOverride={saveFeedbackOverride}
          onRerunFromBackground={onRerunFromBackground}
          onPhaseComplete={onPhaseComplete}
          triggerUpdate={() => setPhaseUpdateTrigger(prev => prev + 1)}
          onExpand={overlayMode ? undefined : () => toggleExpand(phaseName, vendor)}
          isExpanded={overlayMode}
          onCloseExpand={overlayMode ? closeExpand : undefined}
          useOverlayWidth={overlayMode}
          onAfterApproveInExpanded={overlayMode ? onAfterApproveInExpanded : undefined}
        />
      ));
    });
    return renderFunctions;
  }, [phases, sessionId, onEditChange, onApprove, onRerunFromBackground, onPhaseComplete, saveFeedbackOverride, toggleExpand, closeExpand, onAfterApproveInExpanded]);
  
  phases.forEach(phaseObj => {
    const phaseName = phaseObj.phase;
    const phaseModule = phaseModules[phaseName];
    const title = phaseModule?.getPhaseTitle() || phaseName;
    
    // Visibility: phase is visible if no previous phase
    // Cards will manage their own visibility based on their state
    let visible = true;
    if (phaseObj.previous) {
      // Phase becomes visible when previous phase has at least one approved card
      // Since cards own their state, we'll show it and let cards handle their own logic
      visible = true;
    }
    
    phaseObj.title = title;
    phaseObj.visible = visible;
    phaseObj.collapsed = collapsedPhases[phaseName] || false;
    phaseObj.toggle = () => setCollapsedPhases((prev) => ({ ...prev, [phaseName]: !prev[phaseName] }));
    phaseObj.renderVendor = memoizedRenderVendors.get(phaseName);
  });

  return (
    <>
      {expandedCard && expandedPhase && createPortal(
        <div
          role="presentation"
          onClick={closeExpand}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            padding: 24,
            boxSizing: "border-box",
            background: "rgba(0,0,0,0.2)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
          }}
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); goLeft(); }}
            disabled={isFirstVendor}
            title="Previous (←)"
            style={{
              flexShrink: 0,
              width: 44,
              height: 44,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "rgba(0,0,0,0.25)",
              color: "rgba(255,255,255,0.9)",
              border: "none",
              cursor: isFirstVendor ? "not-allowed" : "pointer",
              opacity: isFirstVendor ? 0.4 : 1,
              fontSize: "22px",
            }}
          >
            ‹
          </button>
          <div
            role="dialog"
            aria-label={`Expanded: ${expandedCard.vendor}`}
            onClick={(e) => e.stopPropagation()}
            style={{
              flex: "1 1 0",
              minWidth: 0,
              maxWidth: 1200,
              height: "85vh",
              maxHeight: "85vh",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
              background: "var(--card-bg)",
              border: "1px solid var(--border-color)",
              borderRadius: 8,
              boxShadow: "0 12px 40px rgba(0,0,0,0.15)",
            }}
          >
            {expandedPhase.renderVendor(expandedCard.vendor, true)}
          </div>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); goRight(); }}
            disabled={isLastVendor && !hasNextPhase}
            title="Next (→)"
            style={{
              flexShrink: 0,
              width: 44,
              height: 44,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "rgba(0,0,0,0.25)",
              color: "rgba(255,255,255,0.9)",
              border: "none",
              cursor: (isLastVendor && !hasNextPhase) ? "not-allowed" : "pointer",
              opacity: (isLastVendor && !hasNextPhase) ? 0.4 : 1,
              fontSize: "22px",
            }}
          >
            ›
          </button>
        </div>,
        document.body
      )}
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
      {phases.filter((phase) => phase.visible).map((phase) => (
        <PhaseSection
          key={phase.phase}
          title={phase.title}
          collapsed={phase.collapsed}
          onToggle={phase.toggle}
          showApproveAll={vendorsList.length > 0}
          approveAllDisabled={false}
          readyCount={phase.readyCount || 0}
          totalCount={phase.pendingCount || 0}
          onApproveAll={() => {
            // Approve all ready vendors
            // Use the parent's handler if provided - it handles parallel requests efficiently
            if (onApproveAll) {
              onApproveAll(phase.phase);
            }
            
            // Mark all vendors as approved in the local phase state
            // This ensures the NEXT phase shows "Loading..." immediately
            vendorsList.forEach(vendor => {
              if (phase.approvedVendors) {
                phase.approvedVendors.add(vendor);
              }
            });
            
            // Force re-render to update UI (show loading on next phase)
            setPhaseUpdateTrigger(prev => prev + 1);
          }}
        >
          {vendorsList
            .filter((v) => !(expandedCard?.phase === phase.phase && expandedCard?.vendor === v))
            .map((vendor) => phase.renderVendor(vendor))}
        </PhaseSection>
      ))}
      </div>
    </>
  );
}

