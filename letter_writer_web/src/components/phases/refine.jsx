import React from "react";
import { FeedbackItemsPanel } from "./FeedbackItemsPanel";
import {
  mergeCategoryItems,
  categoryHasPleaseFix,
  categoryAllItemsApproved,
  findNextUnseenCategory,
} from "./feedbackItemUtils";

/**
 * Refine phase module - handles the review of the draft and feedback
 * The data for this phase (draft + feedback) comes from the background phase's approval (draft API call).
 */

export function getPhaseTitle() {
  return "Refine";
}

export function initializeEditsFromData(data) {
  if (!data) {
    return {};
  }

  const draft_letter = data.draft_letter;
  if (draft_letter && typeof draft_letter === "string" && draft_letter.trim()) {
    return { draft_letter: draft_letter, feedback_overrides: {} };
  }

  return {};
}

export function initializeFeedbackFromData(data) {
  if (!data) {
    return null;
  }

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

export function findNextUnseenFeedback(currentKey, itemApprovals, overrides, feedbackData, feedbackKeys) {
  return findNextUnseenCategory(currentKey, feedbackKeys, feedbackData, overrides, itemApprovals);
}

export function computeReadyForApproval({
  isLoading,
  approved,
  thisPhaseDirty,
  previousPhaseApproved,
  feedbackKeys,
  feedbackItemApprovals,
  feedbackOverrides,
  feedback,
}) {
  if (isLoading) return false;
  if (approved && !thisPhaseDirty) return false;
  if (!previousPhaseApproved) return false;

  if (feedbackKeys.length > 0) {
    const allFeedbackReviewed = feedbackKeys.every((k) => {
      const items = mergeCategoryItems(feedback, feedbackOverrides, k);
      return categoryAllItemsApproved(items, feedbackItemApprovals);
    });
    if (!allFeedbackReviewed) return false;
  }

  return true;
}

export function handleRetryResult(data, callbacks) {
  // Logic handled in App.jsx approvePhase
}

export function renderContent({
  EditableField,
  cardPhaseEdits,
  cardPhaseData,
  handleEditChange,
  isLoading,
  previousPhaseApproved,
  approved,
  cardPhase,
  vendor,
  feedback,
  feedbackKeys,
  feedbackOverrides,
  activeFeedbackKey,
  feedbackItemApprovals,
  setFeedbackItemApprovals,
  setSelectedFeedbackTab,
  handleSaveFeedbackOverride,
  translation,
  inputClusterText,
  broadcastInputCluster,
}) {
  const duplicateLinkFlat = React.useMemo(() => {
    const out = [];
    for (const k of feedbackKeys) {
      for (const it of mergeCategoryItems(feedback, feedbackOverrides, k)) {
        if (it.duplicate_group_id || it.input_cluster_key) {
          out.push({
            id: it.id,
            categoryKey: k,
            duplicate_group_id: it.duplicate_group_id,
            input_cluster_key: it.input_cluster_key,
          });
        }
      }
    }
    return out;
  }, [feedback, feedbackOverrides, feedbackKeys]);

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
              const baseItems = mergeCategoryItems(feedback, {}, key);
              const displayItems = mergeCategoryItems(feedback, feedbackOverrides, key);
              const machineStatus = categoryHasPleaseFix(baseItems) ? "📜" : "✅";
              const humanOk = categoryAllItemsApproved(displayItems, feedbackItemApprovals);
              const humanStatus = displayItems.length === 0 ? "✅" : humanOk ? "👍" : "❔";

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
          {activeFeedbackKey && (
            <FeedbackItemsPanel
              categoryKey={activeFeedbackKey}
              items={mergeCategoryItems(feedback, feedbackOverrides, activeFeedbackKey)}
              feedbackItemApprovals={feedbackItemApprovals}
              setFeedbackItemApprovals={setFeedbackItemApprovals}
              handleSaveFeedbackOverride={handleSaveFeedbackOverride}
              feedbackKeys={feedbackKeys}
              feedback={feedback}
              feedbackOverrides={feedbackOverrides}
              activeFeedbackKey={activeFeedbackKey}
              setSelectedFeedbackTab={setSelectedFeedbackTab}
              disabled={isLoading || !previousPhaseApproved}
              translation={translation}
              duplicateLinkFlat={duplicateLinkFlat}
              inputClusterText={inputClusterText || {}}
              onInputClusterBroadcast={broadcastInputCluster}
            />
          )}
        </div>
      )}
    </>
  );
}
