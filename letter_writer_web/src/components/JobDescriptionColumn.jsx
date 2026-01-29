import React, { useState, useRef, useEffect } from "react";
import LanguageSelector from "./LanguageSelector";
import { translateText } from "../utils/translate";
import CompetencesList from "./CompetencesList";
import { getEffectiveRating } from "../utils/competenceScales";

// Job Description Column with resizable/collapsible requirements section
const JobDescriptionColumn = ({ jobText, requirements = [], competences = {}, scaleConfig, overrides, width, minWidth, languages = [], onHeaderClick, isExpanded, onClose }) => {
  const [requirementsHeight, setRequirementsHeight] = useState(25); // Percentage of column height
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const containerRef = useRef(null);
  const resizeStartY = useRef(0);
  const resizeStartHeight = useRef(25);
  
  // Translation state for job description
  const [jobViewLanguage, setJobViewLanguage] = useState("source");
  const [jobTranslations, setJobTranslations] = useState({});
  const [jobTranslating, setJobTranslating] = useState(false);
  const [jobTranslationError, setJobTranslationError] = useState(null);
  const [lastJobSource, setLastJobSource] = useState(jobText);
  
  // Translation state for requirements
  const [reqViewLanguage, setReqViewLanguage] = useState("source");
  const [reqTranslations, setReqTranslations] = useState({});
  const [reqTranslating, setReqTranslating] = useState(false);
  const [reqTranslationError, setReqTranslationError] = useState(null);
  const [lastReqSource, setLastReqSource] = useState(requirements);

  const requirementsList = Array.isArray(requirements) ? requirements : requirements ? [requirements] : [];

  const isResizingRef = useRef(false);
  
  // Reset translations when source text changes
  useEffect(() => {
    if (jobText !== lastJobSource) {
      setJobTranslations({});
      setJobViewLanguage("source");
      setLastJobSource(jobText);
    }
  }, [jobText, lastJobSource]);
  
  useEffect(() => {
    const reqString = JSON.stringify(requirements);
    if (reqString !== JSON.stringify(lastReqSource)) {
      setReqTranslations({});
      setReqViewLanguage("source");
      setLastReqSource(requirements);
    }
  }, [requirements, lastReqSource]);
  
  // Translate job description
  const translateJobDescription = async (targetLanguage) => {
    if (!jobText || targetLanguage === "source") {
      setJobViewLanguage(targetLanguage);
      return;
    }
    
    if (jobTranslations[targetLanguage] && lastJobSource === jobText) {
      setJobViewLanguage(targetLanguage);
      return;
    }
    
    setJobTranslating(true);
    setJobTranslationError(null);
    
    try {
      const translated = await translateText(jobText, targetLanguage, null);
      setJobTranslations((prev) => ({ ...prev, [targetLanguage]: translated }));
      setJobViewLanguage(targetLanguage);
      setLastJobSource(jobText);
    } catch (err) {
      setJobTranslationError(err.message || "Translation failed");
    } finally {
      setJobTranslating(false);
    }
  };
  
  // Translate requirements
  const translateRequirements = async (targetLanguage) => {
    if (requirementsList.length === 0 || targetLanguage === "source") {
      setReqViewLanguage(targetLanguage);
      return;
    }
    
    const reqString = JSON.stringify(requirements);
    if (reqTranslations[targetLanguage] && JSON.stringify(lastReqSource) === reqString) {
      setReqViewLanguage(targetLanguage);
      return;
    }
    
    setReqTranslating(true);
    setReqTranslationError(null);
    
    try {
      // Translate each requirement individually
      const translatedReqs = await Promise.all(
        requirementsList.map(req => translateText(req, targetLanguage, null))
      );
      setReqTranslations((prev) => ({ ...prev, [targetLanguage]: translatedReqs }));
      setReqViewLanguage(targetLanguage);
      setLastReqSource(requirements);
    } catch (err) {
      setReqTranslationError(err.message || "Translation failed");
    } finally {
      setReqTranslating(false);
    }
  };
  
  // Get display text for job description
  const getJobDisplayText = () => {
    if (jobViewLanguage !== "source" && jobTranslations[jobViewLanguage]) {
      return jobTranslations[jobViewLanguage];
    }
    return jobText;
  };
  
  const comp = typeof competences === "object" && competences !== null ? competences : {};
  const hasRatings = Object.keys(comp).length > 0;
  const reqDisplayTexts =
    reqViewLanguage !== "source" && reqTranslations[reqViewLanguage]
      ? reqTranslations[reqViewLanguage]
      : null;

  const handleResizeStart = (e) => {
    setIsResizing(true);
    isResizingRef.current = true;
    resizeStartY.current = e.clientY;
    resizeStartHeight.current = requirementsHeight;
    e.preventDefault();
  };

  useEffect(() => {
    if (!isResizing) return;

    const handleResizeMove = (e) => {
      if (!isResizingRef.current) return;
      
      const container = containerRef.current;
      if (!container) return;
      
      const containerRect = container.getBoundingClientRect();
      const deltaY = resizeStartY.current - e.clientY; // Inverted: dragging up increases height
      const deltaPercent = (deltaY / containerRect.height) * 100;
      const newHeight = Math.max(10, Math.min(80, resizeStartHeight.current + deltaPercent));
      
      setRequirementsHeight(newHeight);
    };

    const handleResizeEnd = () => {
      setIsResizing(false);
      isResizingRef.current = false;
    };

    document.addEventListener('mousemove', handleResizeMove);
    document.addEventListener('mouseup', handleResizeEnd);
    return () => {
      document.removeEventListener('mousemove', handleResizeMove);
      document.removeEventListener('mouseup', handleResizeEnd);
    };
  }, [isResizing]);

  const jobDescriptionHeight = isCollapsed ? 100 : (100 - requirementsHeight);
  const actualRequirementsHeight = isCollapsed ? 0 : requirementsHeight;

  return (
    <div
      ref={containerRef}
      style={{
        width,
        minWidth: minWidth || "200px",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        border: "1px solid var(--border-color)",
        borderRadius: 4,
        background: "var(--card-bg)",
        overflow: "hidden",
        position: "relative",
        boxSizing: "border-box",
      }}
    >
      {/* Job Description Section */}
      <div
        style={{
          height: isCollapsed ? "100%" : `${jobDescriptionHeight}%`,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "8px 12px",
            background: "var(--header-bg)",
            borderBottom: "1px solid var(--border-color)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexShrink: 0,
          }}
        >
          <strong style={{ color: 'var(--text-color)' }}>Job Description</strong>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {languages.length > 0 && (
              <>
                {jobTranslating && <span style={{ fontSize: "9px", color: "var(--secondary-text-color)" }}>Translating…</span>}
                <LanguageSelector
                  languages={languages}
                  viewLanguage={jobViewLanguage}
                  onLanguageChange={translateJobDescription}
                  hasTranslation={(code) => Boolean(jobTranslations[code])}
                  isTranslating={jobTranslating}
                  size="tiny"
                />
              </>
            )}
            {onHeaderClick && !isExpanded && (
              <button
                type="button"
                onClick={onHeaderClick}
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
            )}
            {isExpanded && onClose && (
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
            )}
          </div>
        </div>
        {jobTranslationError && (
          <div style={{ 
            padding: "4px 12px", 
            background: "var(--error-bg)", 
            color: "#ef4444", 
            fontSize: "10px",
            borderBottom: "1px solid var(--border-color)"
          }}>
            {jobTranslationError}
          </div>
        )}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: 8,
            minHeight: 0,
          }}
        >
          <pre
            style={{
              whiteSpace: "pre-wrap",
              margin: 0,
              fontFamily: "monospace",
              fontSize: "12px",
              color: 'var(--text-color)',
              background: "var(--pre-bg)",
              border: "1px solid var(--border-color)",
              borderRadius: 2,
              padding: 8,
            }}
          >
            {getJobDisplayText() || "No job description available"}
          </pre>
        </div>
      </div>

      {/* Resize Handle */}
      {!isCollapsed && (
        <div
          onMouseDown={handleResizeStart}
          style={{
            height: "8px", // Increased handle size for better usability
            background: isResizing ? "#3b82f6" : "var(--header-bg)",
            borderTop: "1px solid var(--border-color)",
            borderBottom: "1px solid var(--border-color)",
            cursor: "row-resize",
            flexShrink: 0,
            position: "relative",
            transition: isResizing ? "none" : "background 0.2s",
            zIndex: 5,
          }}
          title="Drag to resize"
        >
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              width: "40px",
              height: "2px",
              background: isResizing ? "white" : "var(--secondary-text-color)",
              borderRadius: 1,
            }}
          />
        </div>
      )}

      {/* Competences Section */}
      <div
        style={{
          height: isCollapsed ? "30px" : `${actualRequirementsHeight}%`,
          display: "flex",
          flexDirection: "column",
          minHeight: isCollapsed ? "30px" : 0,
          overflow: "hidden",
          transition: isResizing ? "none" : "height 0.2s ease",
          background: "var(--card-bg)",
        }}
      >
        <div
          style={{
            padding: "4px 12px",
            background: "var(--panel-bg)",
            borderTop: isCollapsed ? "1px solid var(--border-color)" : "none",
            borderBottom: isCollapsed ? "none" : "1px solid var(--border-color)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexShrink: 0,
          }}
        >
          <strong style={{ color: 'var(--text-color)', fontSize: "13px" }}>
            Key Competences
            {requirementsList.length > 0 && ` (${requirementsList.length})`}
            {(() => {
              if (!hasRatings || !scaleConfig) return null;
              const keys = Object.keys(comp);
              let totalWeighted = 0;
              let totalWeight = 0;
              keys.forEach(key => {
                const num = getEffectiveRating(key, comp, scaleConfig, overrides);
                if (num.presence != null && num.importance != null) {
                  totalWeighted += num.presence * num.importance;
                  totalWeight += num.importance;
                }
              });
              if (totalWeight === 0) return null;
              const avgPresence = totalWeighted / totalWeight;
              const avgStars = Math.round(avgPresence);
              return (
                <span style={{ fontWeight: 500, color: "var(--secondary-text-color)", marginLeft: 6 }}>
                  <span style={{ fontSize: 11 }}>
                    {"★".repeat(avgStars)}
                    {"☆".repeat(5 - avgStars)}
                  </span>
                  {" "}({avgPresence.toFixed(1)})
                </span>
              );
            })()}
          </strong>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {!isCollapsed && languages.length > 0 && (
              <>
                {reqTranslating && <span style={{ fontSize: "9px", color: "var(--secondary-text-color)" }}>Translating…</span>}
                <LanguageSelector
                  languages={languages}
                  viewLanguage={reqViewLanguage}
                  onLanguageChange={translateRequirements}
                  hasTranslation={(code) => Boolean(reqTranslations[code])}
                  isTranslating={reqTranslating}
                  size="tiny"
                />
              </>
            )}
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: "14px",
                padding: "2px 6px",
                color: 'var(--text-color)',
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
              title={isCollapsed ? "Expand competences" : "Collapse competences"}
            >
              {isCollapsed ? "▲" : "▼"}
            </button>
          </div>
        </div>
        {!isCollapsed && reqTranslationError && (
          <div style={{ 
            padding: "4px 12px", 
            background: "var(--error-bg)", 
            color: "#ef4444", 
            fontSize: "10px",
            borderBottom: "1px solid var(--border-color)"
          }}>
            {reqTranslationError}
          </div>
        )}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: 8,
            minHeight: 0,
            display: isCollapsed ? "none" : "block",
            background: "var(--pre-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: 2,
          }}
        >
          {requirementsList.length > 0 ? (
            <CompetencesList
              requirements={requirementsList}
              competences={comp}
              scaleConfig={scaleConfig}
              overrides={overrides}
              editable={false}
              displayTexts={reqDisplayTexts}
            />
          ) : (
            <div
              style={{
                padding: 12,
                textAlign: "center",
                color: "var(--secondary-text-color)",
                fontStyle: "italic",
                fontSize: "12px",
              }}
            >
              No competences extracted
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default JobDescriptionColumn;
