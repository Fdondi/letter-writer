import React from "react";
import Paragraph from "../Paragraph";
import FeedbackForm from "./FeedbackForm";

export default function VendorColumnPane({
  vendor,
  columnWidth,
  minColumnWidth,
  vendorColors,
  vendorCosts,
  vendorRefineCosts,
  failedVendors,
  onRetry,
  vendorFeedback,
  setVendorFeedback,
  displayParagraphs,
  swapDraftActive,
  hasDraftParagraphs,
  onToggleDraftSource,
  refineSamples,
  refineSampleTooltip,
  refineRefsText,
  languageOptions,
  requirements,
  selectedKeyTerm,
  onExpand,
}) {
  return (
    <div
      style={{
        width: columnWidth,
        minWidth: `${minColumnWidth}px`,
        display: "flex",
        flexDirection: "column",
        position: "relative",
        background: "var(--card-bg)",
        border: "1px solid var(--border-color)",
        borderRadius: "4px",
        height: "100%",
      }}
    >
      <div>
        <h4
          style={{
            textTransform: "capitalize",
            margin: 0,
            background: vendorColors?.[vendor] || "var(--header-bg)",
            padding: "8px 12px",
            borderRadius: "4px 4px 0 0",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            color: "var(--text-color)",
            flexShrink: 0,
          }}
        >
          <span title={refineSampleTooltip(vendor) || ""}>
            {vendor}
            {swapDraftActive && hasDraftParagraphs && (
              <span style={{ fontWeight: 500, fontSize: 11, marginLeft: 8, opacity: 0.95 }}>(initial draft)</span>
            )}
          </span>
          <button
            type="button"
            onClick={onExpand}
            title="Expand to 80% width"
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
            Expand
          </button>
        </h4>
        {hasDraftParagraphs && (
          <div
            style={{
              padding: "4px 12px",
              borderBottom: "1px solid var(--border-color)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 8,
              background: "var(--header-bg)",
            }}
          >
            <button
              type="button"
              onClick={onToggleDraftSource}
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
            <div style={{ fontSize: "11px", color: "var(--secondary-text-color)", textAlign: "right", marginLeft: "auto" }}>
              {vendorCosts !== undefined && vendorCosts > 0 && vendorRefineCosts !== undefined && vendorRefineCosts > 0 && (
                <>${vendorRefineCosts.toFixed(4)}</>
              )}
              {refineSamples?.length > 0 && <> · refs: {refineRefsText(vendor)}</>}
            </div>
          </div>
        )}
        {failedVendors && (
          <div
            style={{
              padding: "4px 12px",
              background: "var(--error-bg)",
              borderBottom: "1px solid var(--border-color)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span style={{ fontSize: "12px", color: "var(--error-text)" }}>Failed</span>
          </div>
        )}
      </div>

      <div style={{ padding: "8px", flex: 1, overflowY: "auto" }}>
        {failedVendors ? (
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
            <div style={{ marginBottom: "8px" }}>{failedVendors}</div>
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
