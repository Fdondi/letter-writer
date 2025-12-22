import React, { useState, useEffect } from "react";

const stageLabels = {
  background: "Background search",
  refine: "Letter generation & checks",
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
  onApprove,
  selectedFeedbackTab,
  onSelectFeedbackTab,
  feedbackApprovals,
  onApproveFeedback,
  collapsed,
  onToggleCollapsed,
  onRerunFromBackground,
  forcePhase,
}) {
  const backgroundData = state?.background?.data || {};
  const refineData = state?.refine?.data || {};
  const feedback = refineData.feedback || {};
  const feedbackKeys = Object.keys(feedback || {});

  const isDone = state?.background?.approved && state?.refine?.approved;

  let stage = "done";
  if (!state?.background?.approved) stage = "background";
  else if (!state?.refine?.approved) stage = refineData && Object.keys(refineData).length ? "refine" : "pending-refine";

  const phaseToRender = forcePhase || stage;

  const isPendingRefine = stage === "pending-refine";
  const pendingLabel = isPendingRefine ? "Running next phase..." : null;
  const badgeLabel = stageLabels[stage] || "Complete";

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
      <div style={{ display: "flex", alignItems: "center", marginBottom: 8, gap: 8 }}>
        <h4 style={{ margin: 0, flex: 1, textTransform: "capitalize" }}>{vendor}</h4>
        <StageBadge label={badgeLabel} />
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

      {error && <div style={{ color: "red", marginBottom: 8, fontSize: 13 }}>{error}</div>}

      {isDone && collapsed && (
        <div style={{ color: "#059669", fontWeight: 600 }}>
          Ready for assembly. Expand to edit & rerun a phase.
        </div>
      )}

      {(phaseToRender === "background" || (isDone && !collapsed && !forcePhase)) && (
        <>
          <div style={{ fontSize: 13, color: "#374151" }}>
            Review the background search. Edit if needed, then approve to generate the letter.
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
                  <li key={`${vendor}-mp-${idx}`} style={{ fontSize: 13 }}>
                    {p}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
            <button onClick={() => onApprove("background", vendor)}>
              {isDone ? "Save background → rebuild letter" : "Approve background → generate letter"}
            </button>
            {isDone && (
              <button onClick={() => onRerunFromBackground(vendor)}>Rebuild letter from edited background</button>
            )}
          </div>
        </>
      )}

      {(phaseToRender === "refine" || (isDone && !collapsed && !forcePhase)) && (
        <>
          <div style={{ fontSize: 13, color: "#374151" }}>
            Final letter ready. Edit if desired, then approve to move to assembly.
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
                <div
                  style={{
                    marginTop: 8,
                    padding: 10,
                    border: "1px solid #e5e7eb",
                    borderRadius: 6,
                    background: "#f9fafb",
                  }}
                >
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
            onClick={() => onApprove("refine", vendor)}
            style={{ marginTop: 10 }}
            disabled={
              feedbackKeys.length > 0 &&
              feedbackKeys.some((k) => feedbackApprovals[k] === false || feedbackApprovals[k] === undefined)
            }
          >
            {isDone ? "Update final letter" : "Approve refined letter"}
          </button>
        </>
      )}

      {stage === "done" && !collapsed && (
        <div style={{ color: "#059669", fontWeight: 600, marginTop: 8 }}>
          Ready for assembly. Edit above to rerun a phase if needed.
        </div>
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
  onApprove,
  onApproveAll,
  onRerunFromBackground,
}) {
  const [selectedFeedbackTab, setSelectedFeedbackTab] = useState({});
  const [feedbackApprovals, setFeedbackApprovals] = useState({});
  const [collapsedCards, setCollapsedCards] = useState({});
  const [collapsedPhases, setCollapsedPhases] = useState({
    background: false,
    refine: true,
  });

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

      if (backgroundDone && prev.background === false) {
        next.background = true;
        changed = true;
      }
      if (backgroundDone && refineVisible && prev.refine === true) {
        next.refine = false; // open refine when first refine appears
        changed = true;
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

  const pendingBackground = vendorsList.filter((v) => !(phaseState[v]?.background?.approved));
  const pendingRefine = vendorsList.filter(
    (v) => phaseState[v]?.background?.approved && !phaseState[v]?.refine?.approved && phaseState[v]?.refine?.data
  );

  return (
    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Background phase */}
      <details open={!collapsedPhases.background} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 8 }}>
        <summary
          style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", listStyle: "none" }}
            onClick={() => {
              setCollapsedPhases((prev) => ({ ...prev, background: !prev.background }));
            }}
        >
          <h3 style={{ margin: 0 }}>Background</h3>
          <StageBadge label={backgroundDone ? "Complete" : "In progress"} />
          {pendingBackground.length > 1 && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                  onApproveAll("background");
              }}
              style={{ fontSize: 12, padding: "4px 8px" }}
            >
              Approve all background
            </button>
          )}
        </summary>
        <div
          style={{
            display: "flex",
            flexWrap: "nowrap",
            gap: 12,
            marginTop: 8,
            overflowX: "auto",
          }}
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
        </div>
      </details>

      {/* Refine phase */}
      {refineVisible && (
        <details open={!collapsedPhases.refine} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 8 }}>
          <summary
            style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", listStyle: "none" }}
            onClick={() => {
              setCollapsedPhases((prev) => ({ ...prev, refine: !prev.refine }));
            }}
          >
            <h3 style={{ margin: 0 }}>Refine</h3>
            <StageBadge label={refineDone ? "Complete" : "In progress"} />
            {pendingRefine.length > 1 && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onApproveAll("refine");
                }}
                style={{ fontSize: 12, padding: "4px 8px" }}
              >
                Approve all refined letters
              </button>
            )}
          </summary>
        <div
          style={{
            display: "flex",
            flexWrap: "nowrap",
            gap: 12,
            marginTop: 8,
            overflowX: "auto",
          }}
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
          </div>
        </details>
      )}
    </div>
  );
}

