import React, { useState, useEffect } from "react";
import JobDescriptionColumn from "./JobDescriptionColumn";
import { useLanguages } from "../contexts/LanguageContext";
import LanguageSelector from "./LanguageSelector";
import { translateText } from "../utils/translate";
import { useLetterSave } from "../hooks/useLetterSave";

export default function FinalReview({
  initialText,
  jobText,
  requirements,
  competences = {},
  competenceScaleConfig,
  competenceOverrides,
  onSave,
  onBack,
  saving,
}) {
  const [text, setText] = useState(initialText || "");
  const { enabledLanguages } = useLanguages();
  
  // Translation state for the letter
  const [letterViewLanguage, setLetterViewLanguage] = useState("source");
  const [letterTranslations, setLetterTranslations] = useState({});
  const [letterTranslating, setLetterTranslating] = useState(false);
  const [letterTranslationError, setLetterTranslationError] = useState(null);
  const [lastLetterSource, setLastLetterSource] = useState(initialText);

  useEffect(() => {
    setText(initialText || "");
  }, [initialText]);
  
  // Reset translations when source text changes
  useEffect(() => {
    if (text !== lastLetterSource) {
      setLetterTranslations({});
      setLetterViewLanguage("source");
      setLastLetterSource(text);
    }
  }, [text, lastLetterSource]);

  const handleTextChange = (e) => {
    const newText = e.target.value;
    setText(newText);
    
    // If we were viewing a translation, switch back to source
    if (letterViewLanguage !== "source") {
      setLetterViewLanguage("source");
      setLetterTranslations({});
      setLastLetterSource(newText);
    }
  };
  
  // Translate letter
  const translateLetter = async (targetLanguage) => {
    if (!text || targetLanguage === "source") {
      setLetterViewLanguage(targetLanguage);
      return;
    }
    
    if (letterTranslations[targetLanguage] && lastLetterSource === text) {
      setLetterViewLanguage(targetLanguage);
      return;
    }
    
    setLetterTranslating(true);
    setLetterTranslationError(null);
    
    try {
      const translated = await translateText(text, targetLanguage, null);
      setLetterTranslations((prev) => ({ ...prev, [targetLanguage]: translated }));
      setLetterViewLanguage(targetLanguage);
      setLastLetterSource(text);
    } catch (err) {
      setLetterTranslationError(err.message || "Translation failed");
    } finally {
      setLetterTranslating(false);
    }
  };
  
  const getLetterDisplayText = () => {
    if (letterViewLanguage !== "source" && letterTranslations[letterViewLanguage]) {
      return letterTranslations[letterViewLanguage];
    }
    return text;
  };

  const displayText = getLetterDisplayText();
  const { isDirty, handleCopy, handleSave, copyFeedback, saveError } = useLetterSave({
    getFullText: () => displayText,
    onSave,
    saving,
    contentRevision: displayText,
  });

  return (
    <div
      style={{
        display: "flex",
        height: "calc(100vh - 80px)",
        gap: 20,
        marginTop: 20,
      }}
    >
      <JobDescriptionColumn
        jobText={jobText}
        requirements={requirements}
        competences={competences}
        scaleConfig={competenceScaleConfig}
        overrides={competenceOverrides}
        width="350px"
        languages={enabledLanguages}
      />
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h2 style={{ margin: 0, fontSize: "18px" }}>Final Review</h2>
            {enabledLanguages.length > 0 && (
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {letterTranslating && <span style={{ fontSize: "10px", color: "var(--secondary-text-color)" }}>Translating…</span>}
                <LanguageSelector
                  languages={enabledLanguages}
                  viewLanguage={letterViewLanguage}
                  onLanguageChange={translateLetter}
                  hasTranslation={(code) => Boolean(letterTranslations[code])}
                  isTranslating={letterTranslating}
                  size="extra-small"
                />
              </div>
            )}
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button
              type="button"
              onClick={onBack}
              style={{
                padding: "8px 16px",
                backgroundColor: "var(--button-bg)",
                color: "var(--button-text)",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                cursor: "pointer",
              }}
            >
              ← Back to Assembly
            </button>
            <button
              type="button"
              onClick={handleCopy}
              disabled={!displayText.trim() || copyFeedback === "success"}
              style={{
                padding: "8px 16px",
                backgroundColor:
                  copyFeedback === "success" ? "#10b981" : "var(--panel-bg)",
                color: copyFeedback === "success" ? "white" : "var(--text-color)",
                border: "1px solid var(--border-color)",
                borderRadius: "4px",
                cursor: !displayText.trim() || copyFeedback === "success" ? "not-allowed" : "pointer",
                fontWeight: 600,
                minWidth: "80px",
              }}
            >
              {copyFeedback === "success" ? "✓" : "Copy"}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !isDirty || !onSave || !displayText.trim()}
              style={{
                padding: "8px 16px",
                backgroundColor:
                  saving || !isDirty ? "var(--border-color)" : "#3b82f6",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: saving || !isDirty || !onSave ? "not-allowed" : "pointer",
                fontWeight: 600,
                minWidth: "80px",
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>

        {saveError && (
          <div style={{ 
            padding: "8px 12px", 
            background: "var(--error-bg)", 
            color: "#ef4444", 
            fontSize: "12px",
            borderRadius: "4px",
            border: "1px solid var(--error-border)",
            fontWeight: 500
          }}>
            {saveError}
          </div>
        )}

        {letterTranslationError && (
          <div style={{ 
            padding: "6px 12px", 
            background: "var(--error-bg)", 
            color: "#ef4444", 
            fontSize: "11px",
            borderRadius: "4px",
            border: "1px solid var(--error-border)"
          }}>
            {letterTranslationError}
          </div>
        )}
        
        {letterViewLanguage !== "source" && (
          <div style={{ 
            padding: "6px 12px", 
            background: "#dbeafe", 
            color: "#1e40af", 
            fontSize: "11px",
            borderRadius: "4px",
            border: "1px solid #93c5fd"
          }}>
            Viewing translation. Any edits will become the new source text.
          </div>
        )}

        <textarea
          value={displayText}
          onChange={handleTextChange}
          style={{
            flex: 1,
            width: "100%",
            padding: "20px",
            fontSize: "14px",
            lineHeight: "1.6",
            border: "1px solid var(--border-color)",
            borderRadius: "4px",
            resize: "none",
            backgroundColor: letterViewLanguage !== "source" ? "var(--panel-bg)" : "var(--card-bg)",
            color: "var(--text-color)",
            fontFamily: "inherit",
            cursor: "text",
          }}
          spellCheck={true}
        />
      </div>

      <JobDescriptionColumn
        jobText={jobText}
        requirements={requirements}
        competences={competences}
        scaleConfig={competenceScaleConfig}
        overrides={competenceOverrides}
        width="350px"
        languages={enabledLanguages}
      />
    </div>
  );
}
