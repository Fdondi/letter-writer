import React, { useState, useEffect } from "react";
import LanguageSelector from "../LanguageSelector";
import InfoTooltip from "./InfoTooltip";
import { FEEDBACK_DESCRIPTIONS } from "./feedbackDescriptions";

export default function EditableFeedback({
  label,
  value,
  placeholder,
  onSave,
  approved,
  onApprove,
  hasContent,
  isModified,
  fieldId,
  translation,
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

  const feedbackDescription = FEEDBACK_DESCRIPTIONS[label] || `Feedback about ${label.replace(/_/g, ' ')}.`;

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid #e5e7eb", borderRadius: 6, background: "#f9fafb" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, fontWeight: 600 }}>
          {label}
          <InfoTooltip text={feedbackDescription}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '12px',
                fontWeight: 'normal',
                color: 'var(--text-color)',
                opacity: 0.6,
                cursor: 'help',
                lineHeight: '1',
                fontStyle: 'italic',
                marginLeft: '4px',
              }}
              title={feedbackDescription}
            >
              (i)
            </span>
          </InfoTooltip>
        </div>
        {!editing && (
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {hasContent && (
              <button
                type="button"
                onClick={() => onSave("NO COMMENT")}
                style={{
                  fontSize: 11,
                  padding: "2px 6px",
                  border: "1px solid #dc2626",
                  background: "#fff",
                  color: "#dc2626",
                  cursor: "pointer",
                  borderRadius: 3,
                }}
              >
                Remove
              </button>
            )}
            <button
              type="button"
              onClick={() => setEditing(true)}
              style={{
                fontSize: 11,
                padding: "2px 6px",
                borderRadius: 3,
              }}
            >
              Edit
            </button>
            {isModified ? (
              <span
                style={{
                  fontSize: 11,
                  padding: "2px 6px",
                  border: "1px solid #fca5a5",
                  background: "#fff1f2",
                  color: "#b91c1c",
                  borderRadius: 3,
                }}
              >
                Edited
              </span>
            ) : (
              <button
                type="button"
                onClick={onApprove}
                style={{
                  fontSize: 11,
                  padding: "2px 6px",
                  border: "1px solid #16a34a",
                  background: approved ? "#dcfce7" : "#fff",
                  color: "#166534",
                  cursor: approved ? "default" : "pointer",
                  borderRadius: 3,
                }}
                disabled={approved}
              >
                {approved ? "Approved" : "Approve"}
              </button>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <>
          <textarea
            style={{ width: "100%", minHeight: 120, padding: 8 }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={placeholder}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
            <button
              type="button"
              onClick={() => {
                onSave(draft);
                setEditing(false);
              }}
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(value || "");
                setEditing(false);
              }}
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
              background: "#fff",
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
                disabled={false}
                isTranslating={translation.isTranslating[fieldId] || false}
                size="tiny"
              />
            </div>
          )}
          <div
            style={{
              width: "100%",
              minHeight: 80,
              padding: 8,
              border: "1px solid #e5e7eb",
              borderRadius: 4,
              background: "#fff",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              overflowWrap: "anywhere",
              fontSize: 13,
            }}
          >
            {displayedText}
          </div>
        </div>
      )}
    </div>
  );
}
