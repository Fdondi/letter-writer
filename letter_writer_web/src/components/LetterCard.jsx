import React, { useEffect, useMemo, useState } from "react";
import { translateText } from "../utils/translate";
import LanguageSelector from "./LanguageSelector";
import { useLanguages } from "../contexts/LanguageContext";

export default function LetterCard({ title, text, loading = false, error = null, onRetry, onCollapse, editable = false, onChange, width, languages = null }) {
  const [viewLanguage, setViewLanguage] = useState("source"); // "source" or target code
  const [translations, setTranslations] = useState({});
  const [isTranslating, setIsTranslating] = useState(false);
  const [translationError, setTranslationError] = useState(null);
  const [lastSourceSnapshot, setLastSourceSnapshot] = useState(text);

  useEffect(() => {
    // Reset translation cache when source text changes
    if (text !== lastSourceSnapshot) {
      setTranslations({});
      setLastSourceSnapshot(text);
      setViewLanguage("source");
    }
  }, [text, lastSourceSnapshot]);

  const displayedText = useMemo(() => {
    if (viewLanguage !== "source" && translations[viewLanguage]) {
      return translations[viewLanguage];
    }
    return text;
  }, [viewLanguage, translations, text]);

  // Use language context if available, otherwise use provided languages
  let languageContext;
  try {
    languageContext = useLanguages();
  } catch (e) {
    languageContext = null;
  }
  const buttonLanguages = languages || languageContext?.enabledLanguages || [];

  const requestTranslation = async (targetLanguage) => {
    if (isTranslating) return;
    if (translations[targetLanguage] && lastSourceSnapshot === text) {
      setViewLanguage(targetLanguage);
      return;
    }

    setIsTranslating(true);
    setTranslationError(null);
    try {
      const translated = await translateText(text, targetLanguage, null);
      setTranslations((prev) => ({ ...prev, [targetLanguage]: translated }));
      setLastSourceSnapshot(text);
      setViewLanguage(targetLanguage);
    } catch (e) {
      setTranslationError(e.message || "Translation failed");
    } finally {
      setIsTranslating(false);
    }
  };

  return (
    <div
      style={{
        width,
        height: "100%", // Ensure card takes full height of parent
        boxSizing: "border-box", // Include padding/border in height calculation
        border: "1px solid var(--border-color)",
        borderRadius: 4,
        padding: 10,
        position: "relative",
        background: "var(--card-bg)",
        display: "flex",
        flexDirection: "column",
        minHeight: 0, // Allow content to shrink
        perspective: "1000px",
        transition: "transform 0.3s ease",
        transform: viewLanguage !== "source" ? "rotateY(8deg)" : "rotateY(0deg)",
        color: 'var(--text-color)'
      }}
    >
      <div style={{ 
        display: "flex", 
        justifyContent: "space-between", 
        alignItems: "center",
        marginBottom: 5
      }}>
        <strong>{title}</strong>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <LanguageSelector
            languages={buttonLanguages}
            viewLanguage={viewLanguage}
            onLanguageChange={(code) => {
              if (code === "source") {
                setViewLanguage("source");
              } else {
                requestTranslation(code);
              }
            }}
            hasTranslation={(code) => Boolean(translations[code])}
            disabled={loading || !!error}
            isTranslating={isTranslating}
            size="small"
          />
          {onCollapse && (
            <button
              onClick={onCollapse}
              style={{ 
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: "16px",
                padding: "2px 6px",
                color: 'var(--text-color)'
              }}
              title="Hide letter"
            >
              👁️‍🗨️
            </button>
          )}
        </div>
      </div>
      {translationError && (
        <div style={{ color: "var(--error-text)", fontSize: "12px", marginBottom: 6 }}>
          {translationError}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {loading && !text && !error ? (
          <div style={{display:"flex",alignItems:"center",justifyContent:"center",height:"100%"}}>
            <div className="spinner" />
          </div>
        ) : error && !text ? (
          <div style={{padding:8,color:"var(--error-text)",fontSize:12}}>
            {error}
            {onRetry && (
              <button onClick={onRetry} style={{marginTop:5, background: 'var(--button-bg)', color: 'var(--button-text)', border: '1px solid var(--border-color)', padding: '2px 8px', cursor: 'pointer'}}>Retry</button>
            )}
          </div>
        ) : editable ? (
          <textarea
            value={text}
            onChange={(e) => onChange(e.target.value)}
            style={{ 
              width: "100%", 
              height: "100%", 
              resize: "none",
              border: "1px solid var(--border-color)",
              borderRadius: 2,
              padding: 8,
              fontFamily: "monospace",
              fontSize: "12px",
              backgroundColor: 'var(--input-bg)',
              color: 'var(--text-color)'
            }}
          />
        ) : (
          <pre
            style={{
              whiteSpace: "pre-wrap",
              overflowY: "auto",
              height: "100%",
              margin: 0,
              fontFamily: "monospace",
              fontSize: "12px",
              padding: 8,
              background: "var(--pre-bg)",
              border: "1px solid var(--border-color)",
              borderRadius: 2,
              color: 'var(--text-color)'
            }}
          >
            {displayedText}
          </pre>
        )}
      </div>
    </div>
  );
} 