import React, { useState, useEffect } from "react";

const stageLabels = {
  background: "Background search",
  draft: "Draft generation",
  refine: "Refinement checks",
};

const StageBadge = ({ label }) => (
  <span
    style={{
      display: "inline-block",
      padding: "2px 8px",
      borderRadius: 999,
      background: "#eef2ff",
      color: "#3730a3",
      fontSize: 11,
      marginLeft: 8,
    }}
  >
    {label}
  </span>
);

function TextArea({ value, onChange, minHeight = 120, placeholder }) {
  return (
    <textarea
      style={{ width: "100%", minHeight, padding: 8, marginTop: 6 }}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
    />
  );
}

function VendorCard({
  vendor,
  state,
  edits,
  onEditChange,
  loading,
  error,
  onApproveBackground,
  onApproveDraft,
  onApproveRefine,
  selectedFeedbackTab,
  onSelectFeedbackTab,
  feedbackApprovals,
  onApproveFeedback,
}) {
  const backgroundData = state?.background?.data || {};
  const draftData = state?.draft?.data || {};
  const refineData = state?.refine?.data || {};
  const feedback = refineData.feedback || {};
  const feedbackKeys = Object.keys(feedback || {});

  let stage = "done";
  if (!state?.background?.approved) stage = "background";
  else if (!state?.draft?.approved) stage = draftData && Object.keys(draftData).length ? "draft" : "pending-draft";
  else if (!state?.refine?.approved) stage = refineData && Object.keys(refineData).length ? "refine" : "pending-refine";

  const pendingLabel = stage === "pending-draft" ? "Building draft..." : stage === "pending-refine" ? "Running refinement..." : null;
  const badgeLabel =
    stage === "pending-draft"
      ? "Building draft"
      : stage === "pending-refine"
      ? "Running checks"
      : stageLabels[stage] || "Complete";

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 12,
        background: "#fafafa",
        minHeight: 180,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
        <h4 style={{ margin: 0, flex: 1, textTransform: "capitalize" }}>{vendor}</h4>
        <StageBadge label={badgeLabel} />
      </div>

      {loading && (
        <div style={{ padding: 12, color: "#6b7280" }}>{pendingLabel || "Working..."}</div>
      )}

      {error && (
        <div style={{ color: "red", marginBottom: 8, fontSize: 13 }}>{error}</div>
      )}

      {!loading && stage === "background" && (
        <>
          <div style={{ fontSize: 13, color: "#374151" }}>
            Review the background search. Edit if needed, then approve to generate the draft.
          </div>
          <div style={{ marginTop: 8 }}>
            <label style={{ fontWeight: 600, fontSize: 13 }}>Summary</label>
            <TextArea
              value={edits?.background_summary ?? backgroundData.background_summary ?? ""}
              onChange={(val) => onEditChange(vendor, "background", "background_summary", val)}
              minHeight={80}
              placeholder="Background summary"
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <label style={{ fontWeight: 600, fontSize: 13 }}>Company report</label>
            <TextArea
              value={edits?.company_report ?? backgroundData.company_report ?? ""}
              onChange={(val) => onEditChange(vendor, "background", "company_report", val)}
              minHeight={140}
              placeholder="Company research"
            />
          </div>
          {backgroundData.main_points?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>Main points</div>
              <ul style={{ paddingLeft: 18, marginTop: 4 }}>
                {backgroundData.main_points.map((p, idx) => (
                  <li key={`${vendor}-mp-${idx}`} style={{ fontSize: 13 }}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          <button
            onClick={() => onApproveBackground(vendor)}
            style={{ marginTop: 10 }}
          >
            Approve background → build draft
          </button>
        </>
      )}

      {!loading && stage === "draft" && (
        <>
          <div style={{ fontSize: 13, color: "#374151" }}>
            Review and edit the draft before running refinement.
          </div>
          <TextArea
            value={edits?.draft_letter ?? draftData.draft_letter ?? ""}
            onChange={(val) => onEditChange(vendor, "draft", "draft_letter", val)}
            minHeight={200}
            placeholder="Draft letter"
          />
          <button
            onClick={() => onApproveDraft(vendor)}
            style={{ marginTop: 10 }}
          >
            Approve draft → run refinement
          </button>
        </>
      )}

      {!loading && stage === "refine" && (
        <>
          <div style={{ fontSize: 13, color: "#374151" }}>
            Final refinements ready. Edit if desired, then approve to move to assembly.
          </div>
          <TextArea
            value={edits?.final_letter ?? refineData.final_letter ?? ""}
            onChange={(val) => onEditChange(vendor, "refine", "final_letter", val)}
            minHeight={220}
            placeholder="Final letter"
          />
          {feedbackKeys.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {feedbackKeys.map((key) => (
                  <button
                    key={`${vendor}-tab-${key}`}
                    onClick={() => onSelectFeedbackTab(key)}
                    style={{
                      padding: "4px 8px",
                      fontSize: 12,
                      borderRadius: 4,
                      border: selectedFeedbackTab === key ? "1px solid #2563eb" : "1px solid #ccc",
                      background: selectedFeedbackTab === key ? "#e0e7ff" : "#f9fafb",
                      cursor: "pointer",
                    }}
                  >
                    {key}
                    {feedbackApprovals[key] ? " ✓" : ""}
                  </button>
                ))}
              </div>
              {selectedFeedbackTab && feedback[selectedFeedbackTab] && (
                <div style={{ marginTop: 8, padding: 10, border: "1px solid #e5e7eb", borderRadius: 6, background: "#f9fafb" }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{selectedFeedbackTab}</div>
                  <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{feedback[selectedFeedbackTab]}</div>
                  <button
                    onClick={() => onApproveFeedback(selectedFeedbackTab)}
                    style={{ marginTop: 8 }}
                    disabled={feedbackApprovals[selectedFeedbackTab]}
                  >
                    {feedbackApprovals[selectedFeedbackTab] ? "Approved" : "Approve this feedback"}
                  </button>
                </div>
              )}
            </div>
          )}
          <button
            onClick={() => onApproveRefine(vendor)}
            style={{ marginTop: 10 }}
            disabled={
              feedbackKeys.length > 0 &&
              feedbackKeys.some(
                (k) =>
                  feedbackApprovals[k] === false ||
                  feedbackApprovals[k] === undefined
              )
            }
          >
            Approve refined letter
          </button>
        </>
      )}

      {stage === "done" && (
        <div style={{ color: "#059669", fontWeight: 600 }}>Ready for assembly.</div>
      )}
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
  onApproveBackground,
  onApproveDraft,
  onApproveRefine,
  onApproveAllBackground,
  onApproveAllDraft,
  onApproveAllRefine,
}) {
  const [selectedFeedbackTab, setSelectedFeedbackTab] = useState({});
  const [feedbackApprovals, setFeedbackApprovals] = useState({});

  useEffect(() => {
    // initialize tabs and approvals when refine data arrives
    const nextSelected = {};
    const nextApprovals = {};
    vendorsList.forEach((vendor) => {
      const feedback = phaseState[vendor]?.refine?.data?.feedback || {};
      const keys = Object.keys(feedback || {});
      if (keys.length > 0) {
        nextSelected[vendor] = nextSelected[vendor] || keys[0];
        nextApprovals[vendor] = nextApprovals[vendor] || {};
        keys.forEach((k) => {
          const text = feedback[k] || "";
          // Auto-approve if no actionable comment
          const auto = text.trim().toUpperCase().includes("NO COMMENT");
          if (nextApprovals[vendor][k] === undefined) {
            nextApprovals[vendor][k] = auto;
          }
        });
      }
    });
    if (Object.keys(nextSelected).length) setSelectedFeedbackTab((prev) => ({ ...prev, ...nextSelected }));
    if (Object.keys(nextApprovals).length) setFeedbackApprovals((prev) => ({ ...prev, ...nextApprovals }));
  }, [vendorsList, phaseState]);

  const approveFeedback = (vendor, key) => {
    setFeedbackApprovals((prev) => ({
      ...prev,
      [vendor]: {
        ...(prev[vendor] || {}),
        [key]: true,
      },
    }));
  };

  const pendingBackground = vendorsList.filter(
    (v) => !(phaseState[v]?.background?.approved)
  );
  const pendingDraft = vendorsList.filter(
    (v) =>
      phaseState[v]?.background?.approved &&
      !phaseState[v]?.draft?.approved &&
      phaseState[v]?.draft?.data
  );
  const pendingRefine = vendorsList.filter(
    (v) =>
      phaseState[v]?.draft?.approved &&
      !phaseState[v]?.refine?.approved &&
      phaseState[v]?.refine?.data
  );

  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {pendingBackground.length > 1 && (
          <button onClick={onApproveAllBackground}>Approve all background</button>
        )}
        {pendingDraft.length > 1 && (
          <button onClick={onApproveAllDraft}>Approve all drafts</button>
        )}
        {pendingRefine.length > 1 && (
          <button onClick={onApproveAllRefine}>Approve all refined letters</button>
        )}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 12,
        }}
      >
        {vendorsList.map((vendor) => (
          <VendorCard
            key={vendor}
            vendor={vendor}
            state={phaseState[vendor]}
            edits={phaseEdits[vendor]}
            onEditChange={onEditChange}
            loading={loadingVendors.has(vendor)}
            error={errors[vendor]}
            onApproveBackground={onApproveBackground}
            onApproveDraft={onApproveDraft}
            onApproveRefine={() => onApproveRefine(vendor)}
            selectedFeedbackTab={selectedFeedbackTab[vendor]}
            onSelectFeedbackTab={(tab) => setSelectedFeedbackTab((prev) => ({ ...prev, [vendor]: tab }))}
            feedbackApprovals={feedbackApprovals[vendor] || {}}
            onApproveFeedback={(key) => approveFeedback(vendor, key)}
          />
        ))}
      </div>
    </div>
  );
}

