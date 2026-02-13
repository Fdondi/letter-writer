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

  // Build a map of doc id -> LLM score (from topDocs for LLM picks; all docs may have doc.score from backend)
  const llmScoreMap = useMemo(() => {
    const map = {};
    (topDocs || []).forEach((d) => {
      const id = d.id || d.company_name;
      if (id) map[id] = d.score;
    });
    return map;
  }, [topDocs]);

  // Build a set of LLM-selected doc IDs (top 3)
  const llmSelectedIds = useMemo(() => {
    return new Set(Object.keys(llmScoreMap));
  }, [llmScoreMap]);

  // Score for display: doc.score from backend (all scored) or llmScoreMap fallback
  const getScore = (d) => {
    const id = d.id || d.company_name;
    return d.score ?? (id ? llmScoreMap[id] : undefined);
  };

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
  const score = getScore(doc);
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
      {/* Header: title + navigation + selection status */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "6px 10px",
        borderBottom: "1px solid var(--border-color)",
        backgroundColor: isUserSelected ? "var(--accent-bg, rgba(59,130,246,0.08))" : "transparent",
        flexShrink: 0,
        flexWrap: "wrap",
        gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
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

        {/* Title: company + role + LLM badge */}
        <div style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: "var(--text-color)" }}>{companyName}</span>
          {role && <span style={{ fontSize: 12, color: "var(--secondary-text-color)" }}>— {role}</span>}
          {score != null && (
            <span style={{
              fontSize: 11,
              padding: "1px 6px",
              borderRadius: 10,
              backgroundColor: isLlmSelected ? "rgba(245,158,11,0.2)" : "var(--bg-color)",
              color: isLlmSelected ? "#b45309" : "var(--secondary-text-color)",
              border: isLlmSelected ? "1px solid #f59e0b" : "1px solid var(--border-color)",
              fontWeight: 600,
              whiteSpace: "nowrap",
            }}>
              {isLlmSelected ? "LLM pick" : "score"}: {score}/10
            </span>
          )}
        </div>

        {/* Dot indicators showing all docs and their status */}
        <div style={{ display: "flex", gap: 3, alignItems: "center", flexWrap: "wrap", flexShrink: 0 }}>
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
                  backgroundColor:
                    isLlm && isSelected ? "#f59e0b" // LLM picked, still picked: orange
                    : isLlm && !isSelected ? "#1f2937" // LLM picked, unpicked: black
                    : !isLlm && isSelected ? "#3b82f6" // LLM not picked, I picked: blue
                    : "var(--border-color)", // LLM not picked, still not picked: grey
                  border: isCurrent ? "2px solid var(--text-color)" : "1px solid transparent",
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
                title={`${d.company_name_original || d.company_name || "?"} ${getScore(d) != null ? `(score: ${getScore(d)}/10)` : ""} ${isSelected ? "(selected)" : ""}`}
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
        <span style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: "#f59e0b", display: "inline-block" }} />
            LLM pick, selected
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: "#1f2937", display: "inline-block" }} />
            LLM pick, unpicked
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: "#3b82f6", display: "inline-block" }} />
            my pick
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: "var(--border-color)", display: "inline-block" }} />
            neither
          </span>
        </span>
      </div>
    </div>
  );
}
