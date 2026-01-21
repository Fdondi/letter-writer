import React, { useState, useEffect } from "react";
import JobDescriptionColumn from "./JobDescriptionColumn";
import { useLanguages } from "../contexts/LanguageContext";
import LanguageSelector from "./LanguageSelector";
import { translateText } from "../utils/translate";

export default function FinalReview({
  initialText,
  jobText,
  requirements,
  onSaveAndCopy,
  onBack,
  saving,
}) {
  const [text, setText] = useState(initialText || "");
  const [buttonState, setButtonState] = useState("save_copy"); // "save_copy" | "copy"
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
    setButtonState("save_copy");
    
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

  const handleButtonClick = async () => {
    if (buttonState === "save_copy") {
      await onSaveAndCopy(text);
      setButtonState("copy");
    } else {
      // Just copy
      try {
        await navigator.clipboard.writeText(text);
        // Show temporary success feedback if needed, or just rely on button text
      } catch (err) {
        console.error("Failed to copy text:", err);
      }
    }
  };

  // Helper to copy text specifically when in "save_copy" mode (called by handleButtonClick via onSaveAndCopy wrapper in App if needed, 
  // but simpler to let this component handle the clipboard part for both states if onSaveAndCopy just saves)
  // Actually, user said: "Save & Copy" button.
  // So when clicking "Save & Copy", it should Save AND Copy.
  // When clicking "Copy", it should just Copy.
  
  // Let's refine handleButtonClick:
  const handleMainButton = async () => {
    try {
      if (buttonState === "save_copy") {
        // Save first
        await onSaveAndCopy(text);
      }
      // Always copy
      await navigator.clipboard.writeText(text);
      
      setButtonState("copy");
    } catch (err) {
      console.error("Error in Save/Copy:", err);
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
      {/* Sidebar: Job Description */}
      <JobDescriptionColumn
        jobText={jobText}
        requirements={requirements}
        width="350px"
        languages={enabledLanguages}
      />

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
              disabled={saving}
              style={{
                padding: "8px 16px",
                backgroundColor: buttonState === "copy" ? "#10b981" : "#3b82f6", // Green for Copy, Blue for Save & Copy
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: saving ? "not-allowed" : "pointer",
                fontWeight: 600,
                minWidth: "120px",
              }}
            >
              {saving
                ? "Saving..."
                : buttonState === "save_copy"
                ? "Save & Copy"
                : "Copy"}
            </button>
          </div>
        </div>

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
    </div>
  );
}
