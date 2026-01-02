import React from "react";

/**
 * Background phase module - handles API configuration and phase-specific logic
 */

/**
 * Returns API configuration for background phase
 */
export function getApiConfig(vendor, sessionId) {
  return {
    url: `/api/phases/background/${vendor}/`,
    body: { session_id: sessionId },
  };
}

/**
 * Returns the title for background phase
 */
export function getPhaseTitle() {
  return "Background";
}

/**
 * Initializes edits from data for background phase
 */
export function initializeEditsFromData(data) {
  if (data?.company_report) {
    return { company_report: data.company_report };
  }
  return {};
}

/**
 * Computes readyForApproval for background phase
 */
export function computeReadyForApproval({
  isLoading,
  approved,
  thisPhaseDirty,
}) {
  if (isLoading) return false;
  if (approved && !thisPhaseDirty) return false;
  return true;
}

/**
 * Renders additional buttons for background phase (e.g., "Rebuild letter from edited background")
 */
export function renderAdditionalButtons({ isDone, cardPhase, collapsed, onRerunFromBackground, vendor }) {
  if (!isDone || collapsed) {
    return null;
  }
  return (
    <button
      onClick={() => {
        onRerunFromBackground(vendor);
      }}
      style={{ opacity: 0.8 }}
    >
      Rebuild letter from edited background
    </button>
  );
}

/**
 * Renders the content for background phase
 */
export function renderContent({ EditableField, cardPhaseEdits, cardPhaseData, handleEditChange, isLoading }) {
  return (
    <>
      <div style={{ fontSize: 13, color: "#374151" }}>
        Review the background search. Edit if needed, then approve to generate the letter.
      </div>
      <EditableField
        label="Company report"
        value={cardPhaseEdits.company_report ?? cardPhaseData.company_report ?? ""}
        minHeight={140}
        placeholder="Company research"
        onSave={(val) => handleEditChange("company_report", val)}
        disabled={isLoading}
      />
    </>
  );
}

/**
 * Handles retry result for background phase
 * Updates phase-specific state based on the API result
 * 
 * @param {any} data - The API response data
 * @param {Object} callbacks - Callbacks for updating state
 * @param {Function} callbacks.setDocumentId - Set document ID if present (function that takes id)
 * @param {Function} callbacks.setPhaseSessions - Update phase sessions
 * @param {Function} callbacks.setUiStage - Set UI stage
 * @param {Function} callbacks.setShowInput - Set show input flag
 * @param {string} callbacks.vendor - Vendor name
 * @param {string} callbacks.sessionId - Session ID
 */
export function handleRetryResult(data, callbacks) {
  const { setDocumentId, setPhaseSessions, setUiStage, setShowInput, vendor, sessionId } = callbacks;
  
  if (data.document?.id) {
    setDocumentId(data.document.id);
  }
  
  setPhaseSessions((prev) => ({ ...prev, [vendor]: sessionId }));
  setUiStage("phases");
  setShowInput(false);
}
