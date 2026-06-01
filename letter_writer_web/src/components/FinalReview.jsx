import React, { useState, useEffect, useRef } from "react";
import JobDescriptionColumn from "./JobDescriptionColumn";
import { useLanguages } from "../contexts/LanguageContext";
import LanguageSelector from "./LanguageSelector";
import { translateText } from "../utils/translate";

export default function FinalReview({
  initialText,
  jobText,
  requirements,
  competences = {},
  competenceScaleConfig,
  competenceOverrides,
  onSaveAndCopy,
  onBack,
  saving,
}) {
  const [text, setText] = useState(initialText || "");
  const [buttonState, setButtonState] = useState("save_copy"); // "save_copy" | "copy"
  const [copyFeedback, setCopyFeedback] = useState(null); // null | "success"
  const copyFeedbackTimerRef = useRef(null);
  const [saveError, setSaveError] = useState(null);
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

  useEffect(() => {
    return () => {
      if (copyFeedbackTimerRef.current) clearTimeout(copyFeedbackTimerRef.current);
    };
  }, []);
  
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
    setButtonState("save_copy");
    setSaveError(null); // Clear any previous save error
    
    // If we were viewing a translation, switch back to source
    // The new text becomes the source, and we clear translations
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
  
  // Get display text for letter
  const getLetterDisplayText = () => {
    if (letterViewLanguage !== "source" && letterTranslations[letterViewLanguage]) {
      return letterTranslations[letterViewLanguage];
    }
    return text;
  };

  const handleMainButton = async () => {
    setSaveError(null);
    const displayText = getLetterDisplayText();
    const shouldSave = buttonState === "save_copy";
    try {
      await navigator.clipboard.writeText(displayText);
      setCopyFeedback("success");
      await new Promise((resolve) => {
        copyFeedbackTimerRef.current = setTimeout(resolve, 1000);
      });
      setCopyFeedback(null);
      if (shouldSave) {
        await onSaveAndCopy(displayText);
        setButtonState("copy");
      }
    } catch (err) {
      if (copyFeedbackTimerRef.current) clearTimeout(copyFeedbackTimerRef.current);
      setCopyFeedback(null);
      console.error("Error in Copy/Save:", err);
      setSaveError(err.message || "Failed to copy or save letter");
    }
  };

  return (
    <div
      style={{
        display: "flex",
        height: "calc(100vh - 80px)", // Adjust based on header/padding
        gap: 20,
        marginTop: 20,
      }}
    >
      {/* Main Content: Final Letter */}
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
              onClick={handleMainButton}
              disabled={saving || copyFeedback === "success"}
              style={{
                padding: "8px 16px",
                backgroundColor:
                  saving
                    ? "var(--border-color)"
                    : copyFeedback === "success" || buttonState === "copy"
                      ? "#10b981"
                      : "#3b82f6",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: saving || copyFeedback === "success" ? "not-allowed" : "pointer",
                fontWeight: 600,
                minWidth: "120px",
              }}
            >
              {copyFeedback === "success"
                ? "✓"
                : saving
                  ? "Saving..."
                  : buttonState === "save_copy"
                    ? "Copy & Save"
                    : "Copy"}
            </button>
          </div>
        </div>

        {/* Save Error */}
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

        {/* Translation Error */}
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
        
        {/* Translation Edit Notice */}
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
          value={getLetterDisplayText()}
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
