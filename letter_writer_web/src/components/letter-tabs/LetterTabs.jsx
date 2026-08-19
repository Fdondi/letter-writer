import React, { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { HoverProvider } from "../../contexts/HoverContext";
import { useLanguages } from "../../contexts/LanguageContext";
import LetterAssemblyPane from "./LetterAssemblyPane";
import JobColumnPane from "./JobColumnPane";
import VendorColumnPane from "./VendorColumnPane";
import ExpandedVendorColumn from "./ExpandedVendorColumn";
import { countCompetenceOccurrences } from "./countCompetenceOccurrences";

export default function LetterTabs({
  vendorsList,
  vendorParagraphs,
  vendorCosts,
  vendorRefineCosts = {},
  finalParagraphs,
  setFinalParagraphs,
  originalText,
  companyReport = null,
  requirements = [],
  competences = {},
  competenceScaleConfig,
  competenceOverrides,
  failedVendors,
  onRetry,
  vendorColors,
  onAddParagraph,
  onSave,
  savingFinal = false,
  vendorFeedback = {},
  setVendorFeedback = () => {},
  refineSamples = {},
  vendorDraftParagraphs,
}) {
  const [collapsed, setCollapsed] = useState([]);
  const [swapDraftForFinal, setSwapDraftForFinal] = useState({});
  const [selectedKeyTerm, setSelectedKeyTerm] = useState(null);
  const [originalLetter, setOriginalLetter] = useState(originalText || "");
  const [expandedColumn, setExpandedColumn] = useState(null);
  const [finalAssemblyTextNormalized, setFinalAssemblyTextNormalized] = useState("");
  const expandedDialogRef = useRef(null);

  const handleTermClick = (term) => setSelectedKeyTerm((prev) => (prev === term ? null : term));
  const toggleExpand = (id) => setExpandedColumn((prev) => (prev === id ? null : id));
  const closeExpand = () => setExpandedColumn(null);

  const handleAssemblyTextChange = useCallback(({ normalized }) => {
    setFinalAssemblyTextNormalized(normalized);
  }, []);

  const competenceCounts = React.useMemo(
    () =>
      countCompetenceOccurrences(
        vendorParagraphs,
        requirements,
        vendorDraftParagraphs,
        swapDraftForFinal
      ),
    [vendorParagraphs, requirements, vendorDraftParagraphs, swapDraftForFinal]
  );

  useEffect(() => {
    if (originalText !== originalLetter) {
      setOriginalLetter(originalText || "");
    }
  }, [originalText, originalLetter]);

  const { enabledLanguages: languageOptions } = useLanguages();

  const toggleCollapse = (vendor) => {
    setCollapsed((prev) => (prev.includes(vendor) ? prev.filter((v) => v !== vendor) : [...prev, vendor]));
  };

  const refineSampleTooltip = (vendor) => {
    const samples = refineSamples?.[vendor];
    if (!samples || samples.length === 0) return null;
    const counts = {};
    samples.forEach((s) => {
      counts[s] = (counts[s] || 0) + 1;
    });
    const parts = Object.entries(counts)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([v, n]) => (n > 1 ? `${v} ×${n}` : v));
    return `Reference drafts used: ${parts.join(", ")}`;
  };

  const refineRefsText = (vendor) => {
    const samples = refineSamples?.[vendor];
    if (!samples || samples.length === 0) return "";
    const counts = {};
    samples.forEach((s) => {
      counts[s] = (counts[s] || 0) + 1;
    });
    return Object.entries(counts)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([sv, n]) => (n > 1 ? `${sv} ×${n}` : sv))
      .join(", ");
  };

  const paragraphsForVendorColumn = (vendor) => {
    if (
      swapDraftForFinal[vendor] &&
      vendorDraftParagraphs &&
      Array.isArray(vendorDraftParagraphs[vendor]) &&
      vendorDraftParagraphs[vendor].length > 0
    ) {
      return vendorDraftParagraphs[vendor];
    }
    return vendorParagraphs[vendor] || [];
  };

  const toggleVendorDraftSource = (vendorKey) => {
    setSwapDraftForFinal((prev) => ({ ...prev, [vendorKey]: !prev[vendorKey] }));
  };

  const vendorKeys = Object.keys(vendorParagraphs);
  const visibleVendors = vendorKeys.filter((v) => !collapsed.includes(v));
  const collapsedVendors = vendorKeys.filter((v) => collapsed.includes(v));
  const visibleInRowVendors = expandedColumn?.startsWith("vendor:")
    ? visibleVendors.filter((v) => `vendor:${v}` !== expandedColumn)
    : visibleVendors;
  const totalVisible =
    visibleInRowVendors.length + (expandedColumn === "final" ? 0 : 1) + (expandedColumn === "job-description" ? 0 : 1);
  const columnWidth = totalVisible > 0 ? `${100 / totalVisible}%` : "100%";

  const minColumnWidth = parseInt(localStorage.getItem("minColumnWidth") || "200", 10);
  const vendorColumnWidthPx = `${minColumnWidth}px`;

  const expandedVendor = expandedColumn?.startsWith("vendor:") ? expandedColumn.replace(/^vendor:/, "") : null;

  useEffect(() => {
    if (!expandedColumn) return;
    const frame = requestAnimationFrame(() => {
      expandedDialogRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [expandedColumn]);

  const assemblyPaneProps = {
    finalParagraphs,
    setFinalParagraphs,
    vendorColors,
    requirements,
    selectedKeyTerm,
    languageOptions,
    onSave,
    savingFinal,
    vendorColumnWidthPx,
    onAssemblyTextChange: handleAssemblyTextChange,
  };

  const jobColumnProps = {
    jobText: originalLetter,
    companyReport,
    requirements,
    competences,
    scaleConfig: competenceScaleConfig,
    overrides: competenceOverrides,
    languages: languageOptions,
    selectedKeyTerm,
    onTermClick: handleTermClick,
    competenceCounts,
    finalAssemblyText: finalAssemblyTextNormalized,
  };

  return (
    <HoverProvider>
      <div
        style={{
          height: "calc(100vh - 20px)",
          marginTop: 20,
          display: "flex",
          flexDirection: "column",
          color: "var(--text-color)",
        }}
      >
        {expandedColumn &&
          createPortal(
            <div
              role="presentation"
              onClick={closeExpand}
              style={{
                position: "fixed",
                inset: 0,
                zIndex: 1000,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: 24,
                boxSizing: "border-box",
                background: "rgba(0,0,0,0.2)",
                backdropFilter: "blur(8px)",
                WebkitBackdropFilter: "blur(8px)",
              }}
            >
              <div
                ref={expandedDialogRef}
                role="dialog"
                aria-label={`Expanded view: ${expandedVendor || expandedColumn}`}
                tabIndex={-1}
                onClick={(e) => e.stopPropagation()}
                style={{
                  width: "80%",
                  maxWidth: 1200,
                  height: "85vh",
                  maxHeight: "85vh",
                  overflow: "hidden",
                  display: "flex",
                  flexDirection: "column",
                  background: "var(--card-bg)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 8,
                  boxShadow: "0 12px 40px rgba(0,0,0,0.15)",
                  outline: "none",
                }}
              >
                {expandedColumn === "final" && (
                  <LetterAssemblyPane {...assemblyPaneProps} isExpanded onClose={closeExpand} useOverlayWidth />
                )}
                {expandedColumn === "job-description" && (
                  <JobColumnPane {...jobColumnProps} width="100%" minWidth="0" isExpanded onClose={closeExpand} />
                )}
                {expandedVendor && (
                  <ExpandedVendorColumn
                    vendor={expandedVendor}
                    displayParagraphs={paragraphsForVendorColumn(expandedVendor)}
                    vendorColors={vendorColors}
                    vendorCosts={vendorCosts}
                    vendorRefineCosts={vendorRefineCosts}
                    failedVendors={failedVendors}
                    onRetry={onRetry}
                    vendorFeedback={vendorFeedback}
                    setVendorFeedback={setVendorFeedback}
                    languageOptions={languageOptions}
                    requirements={requirements}
                    selectedKeyTerm={selectedKeyTerm}
                    onClose={closeExpand}
                    showDraftSwap={Boolean(vendorDraftParagraphs?.[expandedVendor]?.length)}
                    swapDraftActive={Boolean(swapDraftForFinal[expandedVendor])}
                    onToggleDraftSource={toggleVendorDraftSource}
                    refineSamples={refineSamples}
                    refineSampleTooltip={refineSampleTooltip}
                    refineRefsText={refineRefsText}
                  />
                )}
              </div>
            </div>,
            document.body
          )}

        {collapsedVendors.length > 0 && (
          <select
            onChange={(e) => {
              if (e.target.value) toggleCollapse(e.target.value);
              e.target.value = "";
            }}
            style={{
              marginBottom: 10,
              maxHeight: "100px",
              overflowY: "auto",
              background: "var(--input-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
            }}
          >
            <option value="">Restore collapsed...</option>
            {collapsedVendors.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        )}

        <div
          style={{
            display: "flex",
            gap: 10,
            flex: 1,
            minHeight: 0,
            overflowX: "auto",
            paddingBottom: 10,
          }}
        >
          {visibleInRowVendors.map((v) => (
            <VendorColumnPane
              key={v}
              vendor={v}
              columnWidth={columnWidth}
              minColumnWidth={minColumnWidth}
              vendorColors={vendorColors}
              vendorCosts={vendorCosts?.[v]}
              vendorRefineCosts={vendorRefineCosts[v]}
              failedVendors={failedVendors[v]}
              onRetry={onRetry}
              vendorFeedback={vendorFeedback}
              setVendorFeedback={setVendorFeedback}
              displayParagraphs={paragraphsForVendorColumn(v)}
              swapDraftActive={Boolean(swapDraftForFinal[v])}
              hasDraftParagraphs={Boolean(vendorDraftParagraphs?.[v]?.length)}
              onToggleDraftSource={() => toggleVendorDraftSource(v)}
              refineSamples={refineSamples[v]}
              refineSampleTooltip={refineSampleTooltip}
              refineRefsText={refineRefsText}
              languageOptions={languageOptions}
              requirements={requirements}
              selectedKeyTerm={selectedKeyTerm}
              onExpand={() => toggleExpand(`vendor:${v}`)}
            />
          ))}

          {expandedColumn !== "final" && (
            <LetterAssemblyPane
              {...assemblyPaneProps}
              onHeaderClick={() => toggleExpand("final")}
              useOverlayWidth={false}
            />
          )}

          {expandedColumn !== "job-description" && (
            <JobColumnPane
              {...jobColumnProps}
              width={columnWidth}
              minWidth={`${minColumnWidth}px`}
              onHeaderClick={() => toggleExpand("job-description")}
              isExpanded={expandedColumn === "job-description"}
              onClose={closeExpand}
            />
          )}
        </div>
      </div>
    </HoverProvider>
  );
}

if (!document.querySelector("#letter-tabs-styles")) {
  const style = document.createElement("style");
  style.id = "letter-tabs-styles";
  style.innerHTML = `
    .spinner {
      width: 24px;
      height: 24px;
      border: 3px solid #e2e8f0;
      border-top-color: #3182ce;
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  `;
  document.head.appendChild(style);
}
