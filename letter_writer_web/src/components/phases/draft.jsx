import React from "react";
import { DraftFeedbackView } from "./DraftFeedbackView";
import {
  mergeCategoryItems,
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
export function renderContent(props) {
  // Must not use hooks here: renderContent is called from PhaseCard only when
  // !isLoadingWithoutData, so hooks would run after the loading render (invalid hook count).
  return <DraftFeedbackView {...props} />;
}
