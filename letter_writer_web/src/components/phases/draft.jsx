import React from "react";
import { FeedbackItemsPanel } from "./FeedbackItemsPanel";
import { KnownWeaknessesPanel } from "./KnownWeaknessesPanel";
import {
  mergeCategoryItems,
  categoryHasPleaseFix,
  categoryAllItemsApproved,
  findNextUnseenCategory,
} from "./feedbackItemUtils";

/**
 * Draft phase — full letter plus machine feedback.
 * When the plan step is included, this runs after Plan is approved; otherwise it is the first phase.
 * Approving triggers the refine API to produce the final letter.
 *
 * Background search data (company_report, top_docs) is gathered during the
 * initial phase (extraction or standalone), before the phased flow starts.
 */

/**
 * Returns API configuration for draft phase
 */
export function getApiConfig(vendor, sessionId) {
  return {
    url: `/api/phases/draft/${vendor}/`,
    body: { session_id: sessionId },
  };
}

/**
 * Returns the title for draft phase
 */
export function getPhaseTitle() {
  return "Draft";
}

/**
 * Initializes edits from data for draft phase
 */
export function initializeEditsFromData(data) {
  if (!data) {
    return {};
  }

  const out = { feedback_overrides: {} };
  const draft_letter = data.draft_letter;
  if (draft_letter && typeof draft_letter === "string" && draft_letter.trim()) {
    out.draft_letter = draft_letter;
  }
  if (!out.draft_letter) {
    return {};
  }
  return out;
}

/**
 * Initializes feedback state from data for draft phase
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
 * Helper: next category tab that still has unapproved items
 */
export function findNextUnseenFeedback(currentKey, itemApprovals, overrides, feedbackData, feedbackKeys) {
  return findNextUnseenCategory(currentKey, feedbackKeys, feedbackData, overrides, itemApprovals);
}

/**
 * Computes readyForApproval for draft phase
 */
export function computeReadyForApproval({
  isLoading,
  approved,
  thisPhaseDirty,
  feedbackKeys,
  feedbackItemApprovals,
  feedbackOverrides,
  feedback,
  cardPhaseEdits,
  cardPhaseData,
}) {
  void cardPhaseEdits;
  void cardPhaseData;
  if (isLoading) return false;
  if (approved && !thisPhaseDirty) return false;

  if (feedbackKeys.length > 0) {
    const allFeedbackReviewed = feedbackKeys.every((k) => {
      const items = mergeCategoryItems(feedback, feedbackOverrides, k);
      return categoryAllItemsApproved(items, feedbackItemApprovals);
    });
    if (!allFeedbackReviewed) return false;
  }

  return true;
}

/**
 * Handles retry result for draft phase
 */
export function handleRetryResult(data, callbacks) {
  // Logic handled in App.jsx approvePhase
}

/**
 * Renders the content for draft phase
 */
export function renderContent({
  EditableField,
  cardPhaseEdits,
  cardPhaseData,
  handleEditChange,
  isLoading,
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
  // Must not use hooks here: renderContent is called from PhaseCard only when
  // !isLoadingWithoutData, so hooks would run after the loading render (invalid hook count).
  const duplicateLinkFlat = [];
  for (const k of feedbackKeys) {
    for (const it of mergeCategoryItems(feedback, feedbackOverrides, k)) {
      if (it.duplicate_group_id || it.input_cluster_key) {
        duplicateLinkFlat.push({
          id: it.id,
          categoryKey: k,
          duplicate_group_id: it.duplicate_group_id,
          input_cluster_key: it.input_cluster_key,
        });
      }
    }
  }

  return (
    <>
      <div style={{ fontSize: 13, color: "#374151" }}>
        {approved
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
      <KnownWeaknessesPanel items={cardPhaseData.known_weaknesses} />
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
              disabled={isLoading}
              translation={translation}
              duplicateLinkFlat={duplicateLinkFlat}
              inputClusterText={inputClusterText || {}}
              onInputClusterBroadcast={broadcastInputCluster}
              vendor={vendor}
              knownWeaknesses={cardPhaseData.known_weaknesses}
            />
          )}
        </div>
      )}
    </>
  );
}
