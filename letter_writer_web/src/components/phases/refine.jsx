import React from "react";
import { DraftFeedbackView } from "./DraftFeedbackView";
import {
  mergeCategoryItems,
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

export function renderContent(props) {
  // Must not use hooks here: renderContent is called from PhaseCard only when
  // !isLoadingWithoutData, so hooks would run after the loading render (invalid hook count).
  const { previousPhaseApproved, cardPhase, isLoading } = props;
  return (
    <>
      {!previousPhaseApproved && (
        <div style={{ fontSize: 13, color: "#374151" }}>
          Background approval required before {cardPhase} phase.
        </div>
      )}
      <DraftFeedbackView {...props} isLoading={isLoading || !previousPhaseApproved} />
    </>
  );
}
