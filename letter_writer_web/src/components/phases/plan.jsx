import React from "react";

/**
 * Plan phase — strategic outline before the draft letter.
 * Approving triggers the draft API (parent) with the edited `letter_plan`.
 */

export function getApiConfig(vendor, sessionId) {
  return {
    url: `/api/phases/plan/${vendor}/`,
    body: { session_id: sessionId },
  };
}

export function getPhaseTitle() {
  return "Plan";
}

export function initializeEditsFromData(data) {
  if (!data) return {};
  const letter_plan = data.letter_plan;
  if (letter_plan && typeof letter_plan === "string" && letter_plan.trim()) {
    return { letter_plan };
  }
  return {};
}

export function initializeFeedbackFromData() {
  return null;
}

export function findNextUnseenFeedback() {
  return null;
}

export function computeReadyForApproval({
  isLoading,
  approved,
  thisPhaseDirty,
  cardPhaseEdits,
  cardPhaseData,
}) {
  if (isLoading) return false;
  if (approved && !thisPhaseDirty) return false;
  const text = (cardPhaseEdits?.letter_plan ?? cardPhaseData?.letter_plan ?? "").trim();
  return text.length > 0;
}

export function handleRetryResult(data, callbacks) {
  void data;
  void callbacks;
}

export function renderContent({
  EditableField,
  cardPhaseEdits,
  cardPhaseData,
  handleEditChange,
  isLoading,
  approved,
  vendor,
  translation,
}) {
  const planText = cardPhaseEdits.letter_plan ?? cardPhaseData.letter_plan ?? "";
  return (
    <>
      <div style={{ fontSize: 13, color: "#374151" }}>
        {approved
          ? "Plan is approved. Edit and use “Save and restart from here” to regenerate the plan, or proceed in Draft."
          : "Review the strategic plan, edit if needed, then approve to generate the draft letter."}
      </div>
      <EditableField
        label="Strategic plan (~10 lines: strengths, weaknesses, structure)"
        value={planText}
        minHeight={260}
        placeholder="Letter plan"
        onSave={(val) => handleEditChange("letter_plan", val)}
        disabled={isLoading}
        fieldId={`letter_plan_${vendor}`}
        translation={translation}
        renderAsMarkdown
      />
    </>
  );
}
