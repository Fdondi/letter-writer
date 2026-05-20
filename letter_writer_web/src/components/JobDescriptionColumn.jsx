import React, { useState, useEffect } from "react";
import LanguageSelector from "./LanguageSelector";
import { translateText } from "../utils/translate";
import CompetencesList from "./CompetencesList";
import { getEffectiveRating, getEffectiveImportance } from "../utils/competenceScales";

// Reference sidebar: tabs (job, key competences, company report, POC) + extracted goal
const JobDescriptionColumn = ({
  jobText,
  companyReport = null,
  pocReport = null,
  requirements = [],
  competences = {},
  scaleConfig,
  overrides,
  width,
  minWidth,
  languages = [],
  selectedKeyTerm,
  onTermClick,
  competenceCounts = {},
  finalAssemblyText = "",
  hireProblem = "",
  onHireProblemChange,
  onCollapsePanel,
}) => {
  const [referenceTab, setReferenceTab] = useState("job"); // "job" | "competences" | "report" | "poc"

  const [jobViewLanguage, setJobViewLanguage] = useState("source");
  const [jobTranslations, setJobTranslations] = useState({});
  const [jobTranslating, setJobTranslating] = useState(false);
  const [jobTranslationError, setJobTranslationError] = useState(null);
  const [lastJobSource, setLastJobSource] = useState(jobText);

  const [reqViewLanguage, setReqViewLanguage] = useState("source");
  const [reqTranslations, setReqTranslations] = useState({});
  const [reqTranslating, setReqTranslating] = useState(false);
  const [reqTranslationError, setReqTranslationError] = useState(null);
  const [lastReqSource, setLastReqSource] = useState(requirements);

  const requirementsList = Array.isArray(requirements) ? requirements : requirements ? [requirements] : [];

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
      const translatedReqs = await Promise.all(
        requirementsList.map((req) => translateText(req, targetLanguage, null))
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

  const getJobDisplayText = () => {
    if (jobViewLanguage !== "source" && jobTranslations[jobViewLanguage]) {
      return jobTranslations[jobViewLanguage];
    }
    return jobText;
  };

  const reportPlain =
    companyReport == null
      ? ""
      : typeof companyReport === "string"
        ? companyReport
        : null;
  const reportFormatError =
    companyReport != null && typeof companyReport !== "string" ? typeof companyReport : null;
  const hasReport = Boolean((reportPlain || "").trim());

  const hasPoc = pocReport != null;
  const pocPlain =
    pocReport == null ? "" : typeof pocReport === "string" ? pocReport : null;
  const pocFormatError =
    pocReport != null && typeof pocReport !== "string" ? typeof pocReport : null;

  useEffect(() => {
    if (referenceTab === "poc" && !hasPoc) {
      setReferenceTab("job");
    }
  }, [referenceTab, hasPoc]);

  const tabBtn = (id, label) => (
    <button
      type="button"
      role="tab"
      aria-selected={referenceTab === id}
      onClick={() => setReferenceTab(id)}
      style={{
        padding: "4px 10px",
        fontSize: "12px",
        fontWeight: referenceTab === id ? 600 : 500,
        background: referenceTab === id ? "var(--panel-bg)" : "transparent",
        color: "var(--text-color)",
        border: "1px solid var(--border-color)",
        borderRadius: 4,
        cursor: "pointer",
        borderBottomLeftRadius: referenceTab === id ? 0 : 4,
        borderBottomRightRadius: referenceTab === id ? 0 : 4,
        borderBottom: referenceTab === id ? "1px solid var(--panel-bg)" : undefined,
        marginBottom: referenceTab === id ? -1 : 0,
        zIndex: referenceTab === id ? 1 : 0,
      }}
    >
      {label}
    </button>
  );

  const comp = typeof competences === "object" && competences !== null ? competences : {};
  const hasRatings = Object.keys(comp).length > 0;
  const reqDisplayTexts =
    reqViewLanguage !== "source" && reqTranslations[reqViewLanguage]
      ? reqTranslations[reqViewLanguage]
      : null;

  const showJobLang = referenceTab === "job" && languages.length > 0;
  const showReqLang =
    referenceTab === "competences" && languages.length > 0 && requirementsList.length > 0;
  const showLangOverlay = showJobLang || showReqLang;

  const competencesSummary = (() => {
    if (!hasRatings || !scaleConfig) return null;
    const keys = Object.keys(comp);
    let totalWeighted = 0;
    let totalWeight = 0;
    keys.forEach((key) => {
      const num = getEffectiveRating(key, comp, scaleConfig, overrides);
      const imp = getEffectiveImportance(key, comp, scaleConfig, overrides);
      if (num.presence != null && imp != null) {
        totalWeighted += num.presence * imp;
        totalWeight += imp;
      }
    });
    if (totalWeight === 0) return null;
    const avgPresence = totalWeighted / totalWeight;
    const avgStars = Math.round(avgPresence);
    return (
      <span style={{ fontWeight: 500, color: "var(--secondary-text-color)", fontSize: 12 }}>
        <span style={{ fontSize: 11 }}>
          {"★".repeat(avgStars)}
          {"☆".repeat(5 - avgStars)}
        </span>{" "}
        ({avgPresence.toFixed(1)})
      </span>
    );
  })();

  const renderReportBody = () =>
    reportFormatError ? (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div
          style={{
            padding: 10,
            fontSize: "12px",
            color: "var(--error-text)",
            background: "var(--error-bg)",
            border: "1px solid var(--error-border)",
            borderRadius: 4,
          }}
        >
          Company report is not plain text (type: {reportFormatError}). Raw value:
        </div>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            margin: 0,
            fontFamily: "monospace",
            fontSize: "12px",
            color: "var(--text-color)",
            background: "var(--pre-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: 2,
            padding: 8,
          }}
        >
          {JSON.stringify(companyReport, null, 2)}
        </pre>
      </div>
    ) : hasReport ? (
      <pre
        style={{
          whiteSpace: "pre-wrap",
          margin: 0,
          fontFamily: "monospace",
          fontSize: "12px",
          color: "var(--text-color)",
          background: "var(--pre-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: 2,
          padding: 8,
        }}
      >
        {reportPlain}
      </pre>
    ) : (
      <div
        style={{
          padding: 16,
          textAlign: "center",
          color: "var(--secondary-text-color)",
          fontSize: "12px",
          background: "var(--panel-bg)",
          border: "1px dashed var(--border-color)",
          borderRadius: 4,
        }}
      >
        No company report loaded. Run Company Research in the intake form and select a result, then return to assembly.
      </div>
    );

  const renderPocBody = () =>
    pocFormatError ? (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div
          style={{
            padding: 10,
            fontSize: "12px",
            color: "var(--error-text)",
            background: "var(--error-bg)",
            border: "1px solid var(--error-border)",
            borderRadius: 4,
          }}
        >
          POC report is not plain text (type: {pocFormatError}). Raw value:
        </div>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            margin: 0,
            fontFamily: "monospace",
            fontSize: "12px",
            color: "var(--text-color)",
            background: "var(--pre-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: 2,
            padding: 8,
          }}
        >
          {JSON.stringify(pocReport, null, 2)}
        </pre>
      </div>
    ) : (pocPlain || "").trim() ? (
      <pre
        style={{
          whiteSpace: "pre-wrap",
          margin: 0,
          fontFamily: "monospace",
          fontSize: "12px",
          color: "var(--text-color)",
          background: "var(--pre-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: 2,
          padding: 8,
        }}
      >
        {pocPlain}
      </pre>
    ) : (
      <div
        style={{
          padding: 16,
          textAlign: "center",
          color: "var(--secondary-text-color)",
          fontSize: "12px",
          background: "var(--panel-bg)",
          border: "1px dashed var(--border-color)",
          borderRadius: 4,
        }}
      >
        No POC report text yet. Run POC Research in the intake form and select a result.
      </div>
    );

  const renderTabMain = () => {
    if (referenceTab === "job") {
      return (
        <pre
          style={{
            whiteSpace: "pre-wrap",
            margin: 0,
            fontFamily: "monospace",
            fontSize: "12px",
            color: "var(--text-color)",
            background: "var(--pre-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: 2,
            padding: 8,
            minHeight: 80,
          }}
        >
          {getJobDisplayText() || "No job description available"}
        </pre>
      );
    }
    if (referenceTab === "competences") {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 60 }}>
          {competencesSummary && (
            <div style={{ fontSize: "12px", color: "var(--text-color)", flexShrink: 0 }}>
              Weighted fit {competencesSummary}
            </div>
          )}
          {reqTranslationError && (
            <div
              style={{
                padding: "4px 8px",
                background: "var(--error-bg)",
                color: "#ef4444",
                fontSize: "10px",
                borderRadius: 4,
              }}
            >
              {reqTranslationError}
            </div>
          )}
          <div
            style={{
              flex: 1,
              minHeight: 0,
              background: "var(--pre-bg)",
              border: "1px solid var(--border-color)",
              borderRadius: 2,
              padding: 8,
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
                selectedKeyTerm={selectedKeyTerm}
                onTermClick={onTermClick}
                competenceCounts={competenceCounts}
                finalAssemblyText={finalAssemblyText}
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
      );
    }
    if (referenceTab === "report") {
      return renderReportBody();
    }
    return renderPocBody();
  };

  return (
    <div
      style={{
        width,
        minWidth: minWidth || "200px",
        height: "100%",
        minHeight: 0,
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
      <div
        style={{
          background: "var(--header-bg)",
          borderBottom: "1px solid var(--border-color)",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            padding: "6px 8px 0 4px",
            display: "flex",
            alignItems: "flex-end",
            gap: 0,
            flexWrap: "wrap",
          }}
          role="tablist"
          aria-label="Job reference"
        >
        {onCollapsePanel && (
          <button
            type="button"
            onClick={onCollapsePanel}
            aria-label="Collapse reference panel"
            title="Collapse job reference panel"
            style={{
              flexShrink: 0,
              alignSelf: "center",
              width: 24,
              height: 24,
              marginRight: 6,
              marginBottom: 2,
              padding: 0,
              fontSize: 14,
              lineHeight: "22px",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              background: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              boxShadow: "0 1px 3px rgba(0,0,0,0.12)",
            }}
          >
            ‹
          </button>
        )}
          {tabBtn("job", "Job offer")}
          {tabBtn("competences", "Key competences")}
          {tabBtn("report", "Company report")}
          {hasPoc ? tabBtn("poc", "POC report") : null}
        </div>
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          padding: 8,
          overflow: "hidden",
        }}
      >
        {referenceTab === "job" && jobTranslationError && (
          <div
            style={{
              padding: "4px 8px",
              background: "var(--error-bg)",
              color: "#ef4444",
              fontSize: "10px",
              borderRadius: 4,
              marginBottom: 6,
              flexShrink: 0,
            }}
          >
            {jobTranslationError}
          </div>
        )}

        <div
          style={{
            position: "relative",
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          {showLangOverlay && (
            <div
              style={{
                position: "absolute",
                top: 0,
                right: 0,
                zIndex: 2,
                display: "flex",
                alignItems: "center",
                gap: 4,
                flexWrap: "wrap",
                justifyContent: "flex-end",
                maxWidth: "72%",
              }}
            >
              {(referenceTab === "job" ? jobTranslating : reqTranslating) && (
                <span style={{ fontSize: "9px", color: "var(--secondary-text-color)" }}>Translating…</span>
              )}
              <LanguageSelector
                languages={languages}
                viewLanguage={referenceTab === "job" ? jobViewLanguage : reqViewLanguage}
                onLanguageChange={referenceTab === "job" ? translateJobDescription : translateRequirements}
                hasTranslation={
                  referenceTab === "job"
                    ? (code) => Boolean(jobTranslations[code])
                    : (code) => Boolean(reqTranslations[code])
                }
                isTranslating={referenceTab === "job" ? jobTranslating : reqTranslating}
                size="tiny"
              />
            </div>
          )}
          <div
            style={{
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              paddingTop: showLangOverlay ? 28 : 4,
            }}
          >
            {renderTabMain()}
          </div>
        </div>
      </div>

      {(hireProblem !== undefined || onHireProblemChange) && (
        <div
          style={{
            flexShrink: 0,
            borderTop: "1px solid var(--border-color)",
            background: "var(--panel-bg)",
            padding: "8px 12px 10px",
            maxHeight: "40%",
            overflowY: "auto",
            minHeight: 0,
          }}
        >
          <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: 4, color: "var(--text-color)" }}>
            Extracted goal
          </label>
          <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginBottom: 6 }}>
            What problem or outcome this hire is meant to address (same extraction pass as key competences).
          </div>
          <textarea
            value={hireProblem ?? ""}
            onChange={onHireProblemChange ? (e) => onHireProblemChange(e.target.value) : undefined}
            readOnly={!onHireProblemChange}
            placeholder="e.g. scale the data platform, lead a regulatory migration…"
            rows={3}
            style={{
              width: "100%",
              boxSizing: "border-box",
              padding: 8,
              fontSize: 13,
              resize: "vertical",
              backgroundColor: "var(--bg-color)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              fontFamily: "inherit",
              opacity: onHireProblemChange ? 1 : 0.95,
              minHeight: 56,
            }}
          />
        </div>
      )}
    </div>
  );
};

export default JobDescriptionColumn;
