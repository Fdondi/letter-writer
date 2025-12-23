import React, { useState, useEffect } from "react";

function EditableField({ label, value, minHeight = 120, placeholder, onSave }) {
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
            style={{ fontSize: 12, padding: "4px 8px" }}
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
          <button type="button" onClick={() => setEditing(true)} style={{ fontSize: 12, padding: "4px 8px" }}>
            ✎ Edit
          </button>
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

const cardStyle = {
  border: "1px solid #e5e7eb",
  borderRadius: 8,
  padding: 12,
  background: "#fafafa",
  minHeight: 180,
  display: "flex",
  flexDirection: "column",
  gap: 8,
  flex: "0 0 340px",
  maxWidth: 340,
  height: "100%",
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
}) {
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
    (edits?.background?.background_summary ?? "").trim() !== (backgroundData.background_summary ?? "").trim() ||
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
    <div style={cardStyle}>
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

      {error && <div style={{ color: "red", marginBottom: 8, fontSize: 13 }}>{error}</div>}

      {(phaseToRender === "background" || (isDone && !collapsed && !forcePhase)) && (
        <>
          <div style={{ fontSize: 13, color: "#374151" }}>
            Review the background search. Edit if needed, then approve to generate the letter.
          </div>
          <EditableField
            label="Summary"
            value={edits?.background?.background_summary ?? backgroundData.background_summary ?? ""}
            minHeight={80}
            placeholder="Background summary"
            onSave={(val) => onEditChange(vendor, "background", "background_summary", val)}
          />
          <EditableField
            label="Company report"
            value={edits?.background?.company_report ?? backgroundData.company_report ?? ""}
            minHeight={140}
            placeholder="Company research"
            onSave={(val) => onEditChange(vendor, "background", "company_report", val)}
          />
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
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: "auto" }}>
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
            {isDone && (
              <button
                onClick={() => onRerunFromBackground(vendor)}
                style={{ opacity: 0.8 }}
              >
                Rebuild letter from edited background
              </button>
            )}
          </div>
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
          />
          {feedbackKeys.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {feedbackKeys.map((key) => {
                  const overriddenVal = feedbackOverrides[key];
                  const baseVal = feedback[key] || "";
                  const displayVal = overriddenVal !== undefined ? overriddenVal : baseVal;
                  const trimmedUpper = (displayVal || "").trim().toUpperCase();
                  const isNoComment = trimmedUpper === "" || trimmedUpper === "NO COMMENT";
                  const hasContent = !isNoComment;
                  const approved = feedbackApprovals[key];
                  const isModified = overriddenVal !== undefined && overriddenVal !== baseVal;

                  // Machine block: 🤖 | status
                  const machineStatus = hasContent ? "📜" : "✅";

                  // Human block: 🧑 | status (stacked with thick divider between machine and human)
                  let humanStatus = "❔";
                  if (approved) {
                    humanStatus = isNoComment ? "✅" : "👍";
                  } else if (isModified) {
                    humanStatus = isNoComment ? "✅" : "✏️";
                  } else if (!hasContent && !approved) {
                    humanStatus = "❔";
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
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: "auto" }}>
            <button
              onClick={() => onApprove("refine", vendor)}
              style={{ marginTop: 10,
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
          </div>
        </>
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

  const saveFeedbackOverride = (vendor, key, val) => {
    if (!vendor || !key) return;
    const current = phaseEdits[vendor]?.refine?.feedback_overrides || {};
    const next = { ...current, [key]: val };
    onEditChange(vendor, "refine", "feedback_overrides", next);
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
            alignItems: "stretch",
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
                  Approve all comments & write final letters
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
            alignItems: "stretch",
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
          </div>
        </details>
      )}
    </div>
  );
}

