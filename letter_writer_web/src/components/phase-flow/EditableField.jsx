import React, { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import LanguageSelector from "../LanguageSelector";
import { planMarkdownComponents } from "./planMarkdownComponents";

export default function EditableField({
  label,
  value,
  minHeight = 120,
  placeholder,
  onSave,
  disabled = false,
  fieldId,
  translation,
  renderAsMarkdown = false,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");

  useEffect(() => {
    if (!editing) {
      setDraft(value || "");
    }
  }, [value, editing]);

  useEffect(() => {
    if (translation && fieldId) {
      translation.resetFieldTranslation(fieldId, value || "");
    }
  }, [value, fieldId, translation]);

  const displayedText = translation && fieldId
    ? translation.getTranslatedText(fieldId, value || "")
    : (value || placeholder || "");

  const fieldViewLanguage = translation && fieldId
    ? translation.getFieldViewLanguage(fieldId)
    : "source";

  const handleFieldLanguageChange = async (code) => {
    if (!translation || !fieldId) return;

    translation.setFieldViewLanguage(fieldId, code);

    if (code === "source") {
      return;
    }

    const sourceText = value || "";
    if (sourceText) {
      await translation.translateField(fieldId, sourceText, code);
    }
  };

  return (
    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <label style={{ fontWeight: 600, fontSize: 13, flex: 1 }}>{label}</label>
        {!editing && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={disabled}
            style={{
              fontSize: 12,
              padding: "4px 8px",
              opacity: disabled ? 0.6 : 1,
              cursor: disabled ? "not-allowed" : "pointer"
            }}
          >
            ✎ Edit
          </button>
        )}
      </div>
      {editing ? (
        <>
          <textarea
            style={{ width: "100%", minHeight, padding: 8 }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={placeholder}
            disabled={disabled}
            wrap="soft"
            spellCheck={true}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => {
                onSave(draft);
                setEditing(false);
              }}
              disabled={disabled}
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(value || "");
                setEditing(false);
              }}
              disabled={disabled}
            >
              Discard
            </button>
          </div>
        </>
      ) : (
        <div style={{ position: "relative" }}>
          {translation && fieldId && (
            <div style={{
              position: "absolute",
              right: -1,
              top: -10,
              zIndex: 10,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderLeft: "none",
              borderTopRightRadius: 4,
              borderBottomRightRadius: 4,
              padding: "2px 2px 2px 4px",
            }}>
              <LanguageSelector
                languages={translation.languages}
                viewLanguage={fieldViewLanguage}
                onLanguageChange={handleFieldLanguageChange}
                hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
                disabled={disabled}
                isTranslating={translation.isTranslating[fieldId] || false}
                size="tiny"
              />
            </div>
          )}
          <div
            style={{
              width: "100%",
              minHeight,
              padding: 8,
              border: "1px solid #e5e7eb",
              borderRadius: 4,
              background: "#f9fafb",
              whiteSpace: renderAsMarkdown ? "normal" : "pre-wrap",
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            {renderAsMarkdown ? (
              <ReactMarkdown components={planMarkdownComponents}>{displayedText}</ReactMarkdown>
            ) : (
              displayedText
            )}
          </div>
        </div>
      )}
    </div>
  );
}
