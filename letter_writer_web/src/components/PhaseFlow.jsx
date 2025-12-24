import React, { useState, useEffect } from "react";

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
  // Show remaining count: if 2/6 ready, after approving 2, show 0/4 remaining
  const approveButtonText = readyCount !== undefined && totalCount !== undefined
    ? readyCount < totalCount
      ? `Approve (${readyCount}/${totalCount})`
      : readyCount > 0
        ? "Approve all"
        : "Approve all"
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

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid #e5e7eb", borderRadius: 6, background: "#f9fafb" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, fontWeight: 600 }}>{label}</div>
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
  state,
  edits,
  onEditChange,
  onSaveFeedbackOverride,
  loading,
  error,
  onApprove,
  selectedFeedbackTab,
  onSelectFeedbackTab,
  feedbackApprovals,
  onApproveFeedback,
  collapsed,
  onToggleCollapsed,
  onRerunFromBackground,
  forcePhase,
  disabled = false,
  extractionData,
  extractionEdits,
  onExtractionChange,
  onApproveExtraction,
  extractionApproved = false,
  extractionLoading = false,
  extractionError,
}) {
  const renderExtraction = () => {
    const requirementsValue = Array.isArray(extractionEdits?.requirements)
      ? extractionEdits.requirements.join("\n")
      : extractionEdits?.requirements ||
        extractionData?.requirements?.join?.("\n") ||
        extractionData?.requirements ||
        "";
    const isBusy = extractionLoading;
    const hasCompany = (extractionEdits?.company_name || extractionData?.company_name || "").trim().length > 0;

    return (
      <>
        <div style={{ fontSize: 13, color: "#374151" }}>
          We parsed the job description. Tweak any fields, then approve to run background search.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8 }}>
          <InputRow
            label="Company"
            value={extractionEdits?.company_name ?? extractionData?.company_name ?? ""}
            onChange={(val) => onExtractionChange?.(vendor, "company_name", val)}
            placeholder="Detected company name (required)"
          />
          <InputRow
            label="Job title"
            value={extractionEdits?.job_title ?? extractionData?.job_title ?? ""}
            onChange={(val) => onExtractionChange?.(vendor, "job_title", val)}
            placeholder="e.g. Senior Backend Engineer"
          />
          <InputRow
            label="Location"
            value={extractionEdits?.location ?? extractionData?.location ?? ""}
            onChange={(val) => onExtractionChange?.(vendor, "location", val)}
            placeholder="e.g. Remote, Berlin, Hybrid"
          />
          <InputRow
            label="Language"
            value={extractionEdits?.language ?? extractionData?.language ?? ""}
            onChange={(val) => onExtractionChange?.(vendor, "language", val)}
            placeholder="Primary language"
          />
          <InputRow
            label="Salary"
            value={extractionEdits?.salary ?? extractionData?.salary ?? ""}
            onChange={(val) => onExtractionChange?.(vendor, "salary", val)}
            placeholder="Salary range or notes"
          />
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
            <span style={{ fontWeight: 600 }}>Main requirements</span>
            <textarea
              value={requirementsValue}
              onChange={(e) =>
                onExtractionChange?.(
                  vendor,
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
            {isBusy ? "Running background..." : extractionApproved ? "Re-run background" : "Approve background → generate letter"}
          </button>
        </div>
      </>
    );
  };

  const backgroundData = state?.background?.data || {};
  const refineData = state?.refine?.data || {};
  const feedback = refineData.feedback || {};
  const feedbackKeys = Object.keys(feedback || {});
  const feedbackOverrides = edits?.refine?.feedback_overrides || {};
  const activeFeedbackKey = selectedFeedbackTab || feedbackKeys[0] || null;

  const isDone = state?.background?.approved && state?.refine?.approved;
  const backgroundApproved = !!state?.background?.approved;
  const refineApproved = !!state?.refine?.approved;

  const backgroundDirty =
    (edits?.background?.company_report ?? "").trim() !== (backgroundData.company_report ?? "").trim();
  const refineDirty =
    (edits?.refine?.final_letter ?? "").trim() !== (refineData.final_letter ?? "").trim();

  let stage = "done";
  if (!state?.background?.approved) stage = "background";
  else if (!state?.refine?.approved) stage = refineData && Object.keys(refineData).length ? "refine" : "pending-refine";

  const phaseToRender = forcePhase || stage;

  const isPendingRefine = stage === "pending-refine";
  const pendingLabel = isPendingRefine ? "Running next phase..." : null;

  return (
    <div style={{ ...cardStyle, opacity: disabled ? 0.6 : 1, pointerEvents: disabled ? "none" : "auto" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 8 }}>
        <h4 style={{ margin: 0, flex: 1, textTransform: "capitalize" }}>{vendor}</h4>
        {isDone && (
          <button onClick={onToggleCollapsed} style={{ fontSize: 12, padding: "4px 8px" }}>
            {collapsed ? "Expand" : "Collapse"}
          </button>
        )}
      </div>

      {!isDone && loading && (
        <div style={{ padding: 6, color: "#6b7280", fontSize: 12 }}>
          {pendingLabel || "Preparing next phase..."}
        </div>
      )}

      {error && (
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

      <div style={contentContainerStyle}>
        {phaseToRender === "extraction" && (
          renderExtraction()
        )}
        {(phaseToRender === "background" || (isDone && !collapsed && !forcePhase)) && (
          <>
            <div style={{ fontSize: 13, color: "#374151" }}>
              Review the background search. Edit if needed, then approve to generate the letter.
            </div>
            <EditableField
              label="Company report"
              value={edits?.background?.company_report ?? backgroundData.company_report ?? ""}
              minHeight={140}
              placeholder="Company research"
              onSave={(val) => onEditChange(vendor, "background", "company_report", val)}
              disabled={loading}
            />
          </>
        )}

        {(phaseToRender === "refine" || (isDone && !collapsed && !forcePhase)) && (
          <>
            <div style={{ fontSize: 13, color: "#374151" }}>
              {!backgroundApproved
                ? "Background approval required before refining this vendor."
                : refineApproved
                  ? "Final letter is approved. Edit to rerun refinement if needed."
                  : "Edit if desired, then approve to move to assembly."}
            </div>
            <EditableField
              label="Final letter"
              value={edits?.refine?.final_letter ?? refineData.final_letter ?? ""}
              minHeight={220}
              placeholder="Final letter"
              onSave={(val) => onEditChange(vendor, "refine", "final_letter", val)}
              disabled={loading}
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
                        onClick={() => onSelectFeedbackTab(key)}
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
                      allKeys.forEach((k) => onApproveFeedback(k));
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
                    onApprove={() => onApproveFeedback(activeFeedbackKey)}
                    onSave={(val) => onSaveFeedbackOverride(activeFeedbackKey, val)}
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

      <div style={buttonBarStyle}>
        {(phaseToRender === "background" || (isDone && !collapsed && !forcePhase)) && (
          <button
            onClick={() => onApprove("background", vendor)}
            disabled={
              loading ||
              (backgroundApproved && !backgroundDirty)
            }
            style={{
              opacity: loading || (backgroundApproved && !backgroundDirty) ? 0.6 : 1,
              cursor: loading || (backgroundApproved && !backgroundDirty) ? "not-allowed" : "pointer",
            }}
          >
            {loading
              ? "Processing..."
              : backgroundApproved
                ? backgroundDirty
                  ? "Save and restart from here"
                  : "Edit to restart from here"
                : "Approve background → generate letter"}
          </button>
        )}
        {(phaseToRender === "background" || (isDone && !collapsed && !forcePhase)) && isDone && (
          <button
            onClick={() => onRerunFromBackground(vendor)}
            style={{ opacity: 0.8 }}
          >
            Rebuild letter from edited background
          </button>
        )}

        {(phaseToRender === "refine" || (isDone && !collapsed && !forcePhase)) && (
          <button
            onClick={() => onApprove("refine", vendor)}
            style={{
              opacity:
                loading ||
                !backgroundApproved ||
                (refineApproved && !refineDirty) ||
                (feedbackKeys.length > 0 &&
                  feedbackKeys.some((k) => feedbackApprovals[k] === false || feedbackApprovals[k] === undefined))
                  ? 0.6
                  : 1,
              cursor:
                loading ||
                !backgroundApproved ||
                (refineApproved && !refineDirty) ||
                (feedbackKeys.length > 0 &&
                  feedbackKeys.some((k) => feedbackApprovals[k] === false || feedbackApprovals[k] === undefined))
                  ? "not-allowed"
                  : "pointer",
            }}
            disabled={
              loading ||
              !backgroundApproved ||
              (refineApproved && !refineDirty) ||
              (feedbackKeys.length > 0 &&
                feedbackKeys.some((k) => feedbackApprovals[k] === false || feedbackApprovals[k] === undefined))
            }
          >
            {loading
              ? "Processing..."
              : refineApproved
                ? refineDirty
                  ? "Save and restart from here"
                  : "Edit to restart from here"
                : "Approve refined letter"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function PhaseFlow({
  vendorsList,
  phaseState,
  phaseEdits,
  loadingVendors,
  errors,
  onEditChange,
  onApprove,
  onApproveAll,
  onRerunFromBackground,
}) {
  const [selectedFeedbackTab, setSelectedFeedbackTab] = useState({});
  const [feedbackApprovals, setFeedbackApprovals] = useState({});
  const [collapsedCards, setCollapsedCards] = useState({});
  const [collapsedPhases, setCollapsedPhases] = useState({
    background: false, // first phase starts open
    refine: true,
  });

  useEffect(() => {
    // initialize tabs and approvals when refine data arrives; reset per session
    const nextSelected = {};
    const nextApprovals = {};
    vendorsList.forEach((vendor) => {
      const feedback = phaseState[vendor]?.refine?.data?.feedback || {};
      const keys = Object.keys(feedback || {});
      if (keys.length > 0) {
        nextSelected[vendor] = keys[0];
        nextApprovals[vendor] = {};
        keys.forEach((k) => {
          // Start all as unreviewed (❔)
          nextApprovals[vendor][k] = false;
        });
      }
    });
    setSelectedFeedbackTab(nextSelected);
    setFeedbackApprovals(nextApprovals);
  }, [vendorsList, phaseState]);

  useEffect(() => {
    // auto-collapse vendors once they are fully done
    setCollapsedCards((prev) => {
      const next = { ...prev };
      let changed = false;

      vendorsList.forEach((v) => {
        const done = phaseState[v]?.refine?.approved;
        if (done && next[v] === undefined) {
          next[v] = true;
          changed = true;
        }
        if (!done && next[v] === true) {
          // keep expanded for in-progress vendors
          next[v] = false;
          changed = true;
        }
      });

      Object.keys(next).forEach((v) => {
        if (!vendorsList.includes(v)) {
          delete next[v];
          changed = true;
        }
      });

      return changed ? next : prev;
    });
  }, [vendorsList, phaseState]);

  const backgroundDone = vendorsList.length > 0 && vendorsList.every((v) => phaseState[v]?.background?.approved);
  const refineVisible = vendorsList.some((v) => phaseState[v]?.refine?.data);
  const refineDone = vendorsList.length > 0 && vendorsList.every((v) => phaseState[v]?.refine?.approved);

  useEffect(() => {
    setCollapsedPhases((prev) => {
      const next = { ...prev };
      let changed = false;

      // If background completes, collapse background and open refine
      if (backgroundDone) {
        if (!prev.background) {
          next.background = true;
          changed = true;
        }
        if (prev.refine) {
          next.refine = false;
          changed = true;
        }
      }

      return changed ? next : prev;
    });
  }, [backgroundDone, refineVisible]);

  const approveFeedback = (vendor, key) => {
    setFeedbackApprovals((prev) => ({
      ...prev,
      [vendor]: {
        ...(prev[vendor] || {}),
        [key]: true,
      },
    }));
  };

  const saveFeedbackOverride = (vendor, key, val) => {
    if (!vendor || !key) return;
    const current = phaseEdits[vendor]?.refine?.feedback_overrides || {};
    const next = { ...current, [key]: val };
    onEditChange(vendor, "refine", "feedback_overrides", next);
  };

  const pendingBackground = vendorsList.filter((v) => !(phaseState[v]?.background?.approved));
  const readyBackground = vendorsList.filter((v) => {
    if (phaseState[v]?.background?.approved) return false;
    // Vendor is ready if they have data from API OR user has manually entered data
    const hasApiData = !!phaseState[v]?.background?.data;
    const hasUserData = !!(phaseEdits[v]?.background?.company_report?.trim());
    return hasApiData || hasUserData;
  });
  const pendingRefine = vendorsList.filter(
    (v) => phaseState[v]?.background?.approved && !phaseState[v]?.refine?.approved && phaseState[v]?.refine?.data
  );
  const readyRefine = vendorsList.filter((v) => {
    if (phaseState[v]?.refine?.approved) return false;
    // Vendor is ready if they have data from API OR user has manually entered data
    const hasApiData = !!phaseState[v]?.refine?.data;
    const hasUserData = !!(phaseEdits[v]?.refine?.final_letter?.trim());
    return hasApiData || hasUserData;
  });

  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Background phase */}
      <PhaseSection
        title="Background"
        collapsed={collapsedPhases.background}
        onToggle={() => setCollapsedPhases((prev) => ({ ...prev, background: !prev.background }))}
        showApproveAll={pendingBackground.length > 1}
        approveAllDisabled={false}
        readyCount={readyBackground.length}
        totalCount={pendingBackground.length}
        onApproveAll={() => onApproveAll("background")}
      >
        {vendorsList.map((vendor) => (
          <VendorCard
            key={`bg-${vendor}`}
            vendor={vendor}
            state={phaseState[vendor]}
            edits={phaseEdits[vendor]}
            onEditChange={onEditChange}
            loading={loadingVendors.has(vendor)}
            error={errors[vendor]}
            onApprove={onApprove}
            selectedFeedbackTab={selectedFeedbackTab[vendor]}
            onSelectFeedbackTab={(tab) => setSelectedFeedbackTab((prev) => ({ ...prev, [vendor]: tab }))}
            feedbackApprovals={feedbackApprovals[vendor] || {}}
            onApproveFeedback={(key) => approveFeedback(vendor, key)}
            onSaveFeedbackOverride={(key, val) => saveFeedbackOverride(vendor, key, val)}
            collapsed={!!collapsedCards[vendor]}
            onToggleCollapsed={() =>
              setCollapsedCards((prev) => ({
                ...prev,
                [vendor]: !prev[vendor],
              }))
            }
            onRerunFromBackground={onRerunFromBackground}
            forcePhase="background"
          />
        ))}
      </PhaseSection>

      {/* Refine phase */}
      {refineVisible && (
        <PhaseSection
          title="Refine"
          collapsed={collapsedPhases.refine}
          onToggle={() => setCollapsedPhases((prev) => ({ ...prev, refine: !prev.refine }))}
          showApproveAll={pendingRefine.length > 1}
          approveAllDisabled={false}
          readyCount={readyRefine.length}
          totalCount={pendingRefine.length}
          onApproveAll={() => onApproveAll("refine")}
        >
          {vendorsList.map((vendor) => (
            <VendorCard
              key={`refine-${vendor}`}
              vendor={vendor}
              state={phaseState[vendor]}
              edits={phaseEdits[vendor]}
              onEditChange={onEditChange}
              loading={loadingVendors.has(vendor)}
              error={errors[vendor]}
              onApprove={onApprove}
              selectedFeedbackTab={selectedFeedbackTab[vendor]}
              onSelectFeedbackTab={(tab) => setSelectedFeedbackTab((prev) => ({ ...prev, [vendor]: tab }))}
              feedbackApprovals={feedbackApprovals[vendor] || {}}
              onApproveFeedback={(key) => approveFeedback(vendor, key)}
              onSaveFeedbackOverride={(key, val) => saveFeedbackOverride(vendor, key, val)}
              collapsed={!!collapsedCards[vendor]}
              onToggleCollapsed={() =>
                setCollapsedCards((prev) => ({
                  ...prev,
                  [vendor]: !prev[vendor],
                }))
              }
              onRerunFromBackground={onRerunFromBackground}
              forcePhase="refine"
            />
          ))}
        </PhaseSection>
      )}
    </div>
  );
}

