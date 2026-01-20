import React, { useState, useEffect } from "react";
import JobDescriptionColumn from "./JobDescriptionColumn";
import { useLanguages } from "../contexts/LanguageContext";

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

  useEffect(() => {
    setText(initialText || "");
  }, [initialText]);

  const handleTextChange = (e) => {
    setText(e.target.value);
    setButtonState("save_copy");
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
          <h2 style={{ margin: 0, fontSize: "18px" }}>Final Review</h2>
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

        <textarea
          value={text}
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
            backgroundColor: "var(--card-bg)",
            color: "var(--text-color)",
            fontFamily: "inherit",
          }}
          spellCheck={true}
        />
      </div>
    </div>
  );
}
