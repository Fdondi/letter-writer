import React from "react";
import Paragraph from "../Paragraph";
import FeedbackForm from "./FeedbackForm";

export default function ExpandedVendorColumn({
  vendor,
  displayParagraphs,
  vendorColors,
  vendorCosts,
  vendorRefineCosts,
  failedVendors,
  onRetry,
  vendorFeedback,
  setVendorFeedback,
  languageOptions,
  requirements,
  selectedKeyTerm,
  onClose,
  showDraftSwap,
  swapDraftActive,
  onToggleDraftSource,
  refineSamples,
  refineSampleTooltip,
  refineRefsText,
}) {
  return (
    <div style={{ width: "100%", minWidth: 0, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          textTransform: "capitalize",
          margin: 0,
          background: vendorColors?.[vendor] || "var(--header-bg)",
          padding: "8px 12px",
          flexShrink: 0,
          color: "var(--text-color)",
        }}
      >
        <span style={{ fontWeight: 600 }} title={refineSampleTooltip(vendor) || ""}>
          {vendor}
          {swapDraftActive && (
            <span style={{ fontWeight: 500, fontSize: 11, marginLeft: 8, opacity: 0.95 }}>(initial draft)</span>
          )}
        </span>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, flexDirection: "column" }}>
          {showDraftSwap && (
            <button
              type="button"
              onClick={() => onToggleDraftSource?.(vendor)}
              title={
                swapDraftActive
                  ? "Show refined letter for this column"
                  : "Show initial draft for this column instead of refined letter"
              }
              style={{
                padding: "2px 8px",
                fontSize: "12px",
                background: "var(--panel-bg)",
                color: "var(--text-color)",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              {swapDraftActive ? "Show refined" : "Show draft"}
            </button>
          )}
          {vendorCosts?.[vendor] !== undefined && vendorCosts[vendor] > 0 && (
            <div style={{ fontSize: "11px", color: "rgba(255, 255, 255, 0.9)", textAlign: "right" }}>
              {vendorRefineCosts?.[vendor] !== undefined && vendorRefineCosts[vendor] > 0 && (
                <div>${vendorRefineCosts[vendor].toFixed(4)}</div>
              )}
            </div>
          )}
          {refineSamples?.[vendor]?.length > 0 && (
            <div style={{ fontSize: 10, fontWeight: 400, opacity: 0.9, textTransform: "none", textAlign: "right", maxWidth: "100%" }}>
              refs: {refineRefsText(vendor)}
            </div>
          )}
          {failedVendors?.[vendor] && (
            <span style={{ fontSize: "12px", color: "var(--error-text)" }}>Failed</span>
          )}
          <button
            type="button"
            onClick={onClose}
            title="Close expanded view"
            style={{
              padding: "2px 8px",
              fontSize: "12px",
              background: "var(--panel-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            × Close
          </button>
        </div>
      </div>
      <div style={{ padding: "8px", flex: 1, overflowY: "auto" }}>
        {failedVendors?.[vendor] ? (
          <div
            style={{
              padding: "16px",
              color: "var(--error-text)",
              fontSize: "12px",
              background: "var(--error-bg)",
              border: "1px solid var(--error-border)",
              borderRadius: 4,
            }}
          >
            <div style={{ marginBottom: "8px" }}>{failedVendors[vendor]}</div>
            <button
              onClick={() => onRetry(vendor)}
              style={{
                padding: "4px 8px",
                fontSize: "12px",
                background: "var(--error-text)",
                color: "white",
                border: "none",
                borderRadius: 2,
                cursor: "pointer",
              }}
            >
              Retry
            </button>
          </div>
        ) : (
          (displayParagraphs || []).map((p, i) => (
            <Paragraph
              key={p.id}
              paragraph={p}
              index={i}
              moveParagraph={() => {}}
              color={vendorColors?.[vendor]}
              editable={false}
              languages={languageOptions}
              keyTerms={requirements}
              selectedKeyTerm={selectedKeyTerm}
            />
          ))
        )}
      </div>
      <FeedbackForm
        rating={vendorFeedback[vendor]?.rating}
        comment={vendorFeedback[vendor]?.comment}
        onChange={(newFeedback) => {
          setVendorFeedback((prev) => ({
            ...prev,
            [vendor]: { ...prev[vendor], ...newFeedback },
          }));
        }}
      />
    </div>
  );
}
