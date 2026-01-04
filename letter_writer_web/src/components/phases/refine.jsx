import React from "react";

/**
 * Refine phase module - handles the review of the draft and feedback
 * The data for this phase (draft + feedback) comes from the background phase's approval (draft API call).
 */

/**
 * Returns the title for refine phase
 */
export function getPhaseTitle() {
  return "Refine";
}

/**
 * Initializes edits from data for refine phase
 */
export function initializeEditsFromData(data) {
  if (!data) {
    return {};
  }
  
  // Handle draft_letter - might be null, undefined, or empty string
  const draft_letter = data.draft_letter;
  if (draft_letter && typeof draft_letter === "string" && draft_letter.trim()) {
    return { draft_letter: draft_letter, feedback_overrides: {} };
  }
  
  return {};
}

/**
 * Initializes feedback state from data for refine phase
 * Returns { feedback, feedbackKeys } or null if no feedback data
 */
export function initializeFeedbackFromData(data) {
  if (!data) {
    return null;
  }
  
  // Handle feedback - it might be null, undefined, empty object, or a dict
  const feedback = data.feedback;
  if (!feedback || typeof feedback !== "object") {
    return null;
  }
  
  const feedbackKeys = Object.keys(feedback);
  if (feedbackKeys.length === 0) {
    return null;
  }
  
  return { feedback, feedbackKeys };
}

/**
 * Helper function to find the next unseen feedback tab
 */
export function findNextUnseenFeedback(currentKey, approvals, overrides, feedbackData, feedbackKeys) {
  if (feedbackKeys.length === 0) return null;
  
  const isSeen = (key) => {
    const isApproved = approvals[key] === true;
    const baseVal = feedbackData[key] || "";
    const overrideVal = overrides[key];
    const isModified = overrideVal !== undefined && overrideVal !== baseVal;
    return isApproved || isModified;
  };
  
  const currentIndex = feedbackKeys.indexOf(currentKey);
  for (let i = 1; i < feedbackKeys.length; i++) {
    const nextIndex = (currentIndex + i) % feedbackKeys.length;
    const nextKey = feedbackKeys[nextIndex];
    if (!isSeen(nextKey)) {
      return nextKey;
    }
  }
  return null;
}

/**
 * Computes readyForApproval for refine phase
 */
export function computeReadyForApproval({
  isLoading,
  approved,
  thisPhaseDirty,
  previousPhaseApproved,
  feedbackKeys,
  feedbackApprovals,
  feedbackOverrides,
  feedback,
}) {
  if (isLoading) return false;
  if (approved && !thisPhaseDirty) return false;
  if (!previousPhaseApproved) return false;
  
  if (feedbackKeys.length > 0) {
    const allFeedbackReviewed = feedbackKeys.every((k) => {
      const isApproved = feedbackApprovals[k] === true;
      const isEdited = feedbackOverrides[k] !== undefined;
      const baseVal = feedback[k] || "";
      const overrideVal = feedbackOverrides[k];
      const displayVal = overrideVal !== undefined ? overrideVal : baseVal;
      const trimmedUpper = (displayVal || "").trim().toUpperCase();
      const isRemoved = trimmedUpper === "" || trimmedUpper.endsWith("NO COMMENT");
      return isApproved || isEdited || isRemoved;
    });
    if (!allFeedbackReviewed) return false;
  }
  
  return true;
}

/**
 * Handles retry result for refine phase
 */
export function handleRetryResult(data, callbacks) {
  // Logic handled in App.jsx approvePhase
}

/**
 * Renders the content for refine phase
 */
export function renderContent({
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
  findNextUnseenFeedback,
  handleSaveFeedbackOverride,
  translation,
}) {
  return (
    <>
      <div style={{ fontSize: 13, color: "#374151" }}>
        {!previousPhaseApproved
          ? `Background approval required before ${cardPhase} phase.`
          : approved
            ? "Draft letter is approved. Edit to rerun refinement if needed."
            : "Review the draft and feedback, then approve to generate the final letter."}
      </div>
      <EditableField
        label="Draft letter"
        value={cardPhaseEdits.draft_letter ?? cardPhaseData.draft_letter ?? ""}
        minHeight={220}
        placeholder="Draft letter"
        onSave={(val) => handleEditChange("draft_letter", val)}
        disabled={isLoading}
        fieldId="draft_letter"
        translation={translation}
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
              const approved = feedbackApprovals[key];
              const isModified = overriddenVal !== undefined && overriddenVal !== baseVal;

              const baseHasContent = (baseVal || "").trim().length > 0 && 
                !(baseVal || "").trim().toUpperCase().endsWith("NO COMMENT");
              const machineStatus = baseHasContent ? "📜" : "✅";

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
                  const nextUnseen = findNextUnseenFeedback(
                    activeFeedbackKey,
                    next,
                    feedbackOverrides,
                    feedback,
                    feedbackKeys
                  );
                  if (nextUnseen) {
                    setSelectedFeedbackTab(nextUnseen);
                  }
                  return next;
                });
              }}
              onSave={(val) => {
                const updatedOverrides = { ...feedbackOverrides, [activeFeedbackKey]: val };
                handleSaveFeedbackOverride(activeFeedbackKey, val);
                const nextUnseen = findNextUnseenFeedback(
                  activeFeedbackKey,
                  feedbackApprovals,
                  updatedOverrides,
                  feedback,
                  feedbackKeys
                );
                if (nextUnseen) {
                  setSelectedFeedbackTab(nextUnseen);
                }
              }}
              isModified={
                feedbackOverrides[activeFeedbackKey] !== undefined &&
                feedbackOverrides[activeFeedbackKey] !== feedback[activeFeedbackKey]
              }
              fieldId={`feedback_${activeFeedbackKey}`}
              translation={translation}
            />
          )}
        </div>
      )}
    </>
  );
}
