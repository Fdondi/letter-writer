import React from "react";
import VendorCard from "./VendorCard";

/** VendorCardWrapper — reads data from the shelf (pre-fetched by previous phase); no fetch logic. */
export default function VendorCardWrapper({
  phaseName,
  vendor,
  phaseObj,
  phaseModule,
  sessionId,
  documentId,
  draftFeedbackRegistryRef,
  onEditChange,
  onApprove,
  onSaveFeedbackOverride,
  onPhaseComplete,
  triggerUpdate,
  onExpand,
  isExpanded,
  onCloseExpand,
  useOverlayWidth,
  onAfterApproveInExpanded,
  inputClusterText,
  broadcastInputCluster,
  onRetryPhaseFetch,
  onClearPhaseFetchError,
}) {
  const previousPhaseApproved = phaseObj.previous ? phaseObj.previous.approvedVendors.has(vendor) : true;

  const currentPhaseData = phaseObj.cardData?.[vendor] || null;
  const shelfError = phaseObj.cardErrors?.[vendor] ?? null;

  const [error, setError] = React.useState(null);

  const combinedError = error || shelfError;
  const status = combinedError
    ? "error"
    : currentPhaseData
      ? "success"
      : (previousPhaseApproved ? "loading" : "idle");

  return (
    <VendorCard
      key={`${phaseName}-${vendor}`}
      vendor={vendor}
      phases={[]}
      phaseObj={phaseObj}
      previousPhaseApproved={previousPhaseApproved}
      allPhasesDone={false}
      data={currentPhaseData}
      status={status}
      error={combinedError}
      onEditChange={onEditChange}
      onApprove={onApprove}
      sessionId={sessionId}
      documentId={documentId}
      draftFeedbackRegistryRef={draftFeedbackRegistryRef}
      onStatusChange={useOverlayWidth ? undefined : (s) => phaseObj.registerStatus?.(vendor, s)}
      onSaveFeedbackOverride={(key, val) => {
        if (typeof onSaveFeedbackOverride === 'function') {
          onSaveFeedbackOverride(key, val);
        } else if (onEditChange) {
          onEditChange(vendor, "draft", "feedback_overrides", { [key]: val });
        }
      }}
      onPhaseComplete={(v, phase, completionData) => {
        if (phaseObj.approvedVendors) {
          phaseObj.approvedVendors.add(v);
        }

        let current = phaseObj.next;
        while (current) {
          if (current !== phaseObj.next && current.cardData) delete current.cardData[v];
          if (current !== phaseObj.next && current.cardErrors) delete current.cardErrors[v];
          if (current.approvedVendors) current.approvedVendors.delete(v);
          current = current.next;
        }

        if (triggerUpdate) triggerUpdate();
        if (onPhaseComplete) onPhaseComplete(v, phase, completionData);
      }}
      setStatus={() => {}}
      setData={() => {}}
      setError={setError}
      onRetryPhaseFetch={onRetryPhaseFetch}
      onClearPhaseFetchError={onClearPhaseFetchError}
      onExpand={onExpand}
      isExpanded={isExpanded}
      onCloseExpand={onCloseExpand}
      useOverlayWidth={useOverlayWidth}
      onAfterApproveInExpanded={onAfterApproveInExpanded}
      inputClusterText={inputClusterText}
      broadcastInputCluster={broadcastInputCluster}
    />
  );
}
