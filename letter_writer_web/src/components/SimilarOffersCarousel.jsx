import React, { useState, useMemo } from "react";

/**
 * Carousel showing RAG-found similar previous job offers.
 * Highlights LLM-selected docs, allows user to add/remove from selection.
 *
 * Props:
 * - allSearchResults: Array of all RAG-retrieved docs (up to 7)
 * - topDocs: Array of LLM-selected docs (top 3, with score field)
 * - selectedDocIds: Set of doc IDs currently selected for draft
 * - onSelectionChange: (newSelectedDocIds: Set) => void
 */
export default function SimilarOffersCarousel({
  allSearchResults = [],
  topDocs = [],
  selectedDocIds = new Set(),
  onSelectionChange,
}) {
  const [currentIndex, setCurrentIndex] = useState(0);

  // Build a map of doc id -> LLM score from topDocs
  const llmScoreMap = useMemo(() => {
    const map = {};
    (topDocs || []).forEach((doc) => {
      const id = doc.id || doc.company_name;
      if (id) map[id] = doc.score;
    });
    return map;
  }, [topDocs]);

  // Build a set of LLM-selected doc IDs
  const llmSelectedIds = useMemo(() => {
    return new Set(Object.keys(llmScoreMap));
  }, [llmScoreMap]);

  if (!allSearchResults || allSearchResults.length === 0) {
    return (
      <div style={{
        padding: 12,
        border: "1px solid var(--border-color)",
        borderRadius: 8,
        backgroundColor: "var(--panel-bg)",
        color: "var(--secondary-text-color)",
        fontSize: 13,
        textAlign: "center",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}>
        Similar previous offers will appear here after extraction.
      </div>
    );
  }

  const total = allSearchResults.length;
  const doc = allSearchResults[currentIndex];
  const docId = doc.id || doc.company_name || `doc-${currentIndex}`;
  const isLlmSelected = llmSelectedIds.has(docId);
  const llmScore = llmScoreMap[docId];
  const isUserSelected = selectedDocIds.has(docId);

  const goLeft = () => setCurrentIndex((prev) => (prev - 1 + total) % total);
  const goRight = () => setCurrentIndex((prev) => (prev + 1) % total);

  const toggleSelection = () => {
    if (!onSelectionChange) return;
    const next = new Set(selectedDocIds);
    if (next.has(docId)) {
      next.delete(docId);
    } else {
      next.add(docId);
    }
    onSelectionChange(next);
  };

  const companyName = doc.company_name_original || doc.company_name || "Unknown";
  const role = doc.role || "";
  const jobText = doc.job_text || "";

  return (
    <div style={{
      border: "1px solid var(--border-color)",
      borderRadius: 8,
      backgroundColor: "var(--panel-bg)",
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      height: "100%",
    }}>
      {/* Header: navigation + selection status */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "6px 10px",
        borderBottom: "1px solid var(--border-color)",
        backgroundColor: isUserSelected ? "var(--accent-bg, rgba(59,130,246,0.08))" : "transparent",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button
            onClick={goLeft}
            style={{
              padding: "2px 8px",
              fontSize: 16,
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              lineHeight: 1,
            }}
            title="Previous offer"
          >
            ‹
          </button>
          <span style={{ fontSize: 12, color: "var(--secondary-text-color)", minWidth: 40, textAlign: "center" }}>
            {currentIndex + 1} / {total}
          </span>
          <button
            onClick={goRight}
            style={{
              padding: "2px 8px",
              fontSize: 16,
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              lineHeight: 1,
            }}
            title="Next offer"
          >
            ›
          </button>
        </div>

        {/* Dot indicators showing all docs and their status */}
        <div style={{ display: "flex", gap: 3, alignItems: "center", flexWrap: "wrap" }}>
          {allSearchResults.map((d, idx) => {
            const dId = d.id || d.company_name || `doc-${idx}`;
            const isSelected = selectedDocIds.has(dId);
            const isLlm = llmSelectedIds.has(dId);
            const isCurrent = idx === currentIndex;
            return (
              <div
                key={dId}
                onClick={() => setCurrentIndex(idx)}
                style={{
                  width: isCurrent ? 10 : 7,
                  height: isCurrent ? 10 : 7,
                  borderRadius: "50%",
                  backgroundColor: isSelected ? "#3b82f6" : isLlm ? "#f59e0b" : "var(--border-color)",
                  border: isCurrent ? "2px solid var(--text-color)" : "1px solid transparent",
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
                title={`${d.company_name_original || d.company_name || "?"} ${isLlm ? `(LLM score: ${llmScoreMap[dId]})` : ""} ${isSelected ? "(selected)" : ""}`}
              />
            );
          })}
        </div>

        {/* Selection toggle */}
        <button
          onClick={toggleSelection}
          style={{
            padding: "3px 10px",
            fontSize: 12,
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            backgroundColor: isUserSelected ? "#3b82f6" : "var(--button-bg)",
            color: isUserSelected ? "white" : "var(--button-text)",
            cursor: "pointer",
            fontWeight: 500,
            whiteSpace: "nowrap",
          }}
        >
          {isUserSelected ? "Selected" : "+ Select"}
        </button>
      </div>

      {/* Doc content — fills remaining space */}
      <div style={{ padding: "8px 10px", flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {/* Company + role + badges */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap", flexShrink: 0 }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{companyName}</span>
          {role && <span style={{ fontSize: 12, color: "var(--secondary-text-color)" }}>— {role}</span>}
          {isLlmSelected && (
            <span style={{
              fontSize: 11,
              padding: "1px 6px",
              borderRadius: 10,
              backgroundColor: "#fef3c7",
              color: "#92400e",
              fontWeight: 600,
              whiteSpace: "nowrap",
            }}>
              LLM pick (score: {llmScore}/10)
            </span>
          )}
        </div>

        {/* Job text — scrollable, fills remaining space */}
        {jobText && (
          <div style={{
            fontSize: 11,
            flex: 1,
            overflowY: "auto",
            whiteSpace: "pre-wrap",
            padding: 6,
            backgroundColor: "var(--bg-color)",
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            lineHeight: 1.4,
          }}>
            {jobText}
          </div>
        )}
      </div>

      {/* Footer: selection summary */}
      <div style={{
        borderTop: "1px solid var(--border-color)",
        padding: "4px 10px",
        fontSize: 11,
        color: "var(--secondary-text-color)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexShrink: 0,
      }}>
        <span>
          {selectedDocIds.size} selected for draft
          {llmSelectedIds.size > 0 && ` (${llmSelectedIds.size} LLM picks)`}
        </span>
        <span style={{ display: "flex", gap: 8 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: "#3b82f6", display: "inline-block" }} />
            selected
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: "#f59e0b", display: "inline-block" }} />
            LLM pick
          </span>
        </span>
      </div>
    </div>
  );
}
