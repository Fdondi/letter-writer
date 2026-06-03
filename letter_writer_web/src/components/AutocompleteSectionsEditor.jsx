/**
 * Sectioned cover-letter editor: title + description (LLM guidance) and body (final copy).
 */

import React, { useCallback, useEffect, useRef } from "react";
import LanguageSelector from "./LanguageSelector";

function sectionFieldId(sectionId, field) {
  return `${sectionId}:${field}`;
}

/** Same pattern as FeedbackItemsPanel / vendor PhaseFlow cards. */
function AutocompleteFieldTranslationBar({ fieldId, sourceText, translation, disabled }) {
  if (!translation || !fieldId) return null;
  const fieldViewLanguage = translation.getFieldViewLanguage(fieldId);
  const handleFieldLanguageChange = async (code) => {
    translation.setFieldViewLanguage(fieldId, code);
    if (code === "source" || !sourceText) return;
    await translation.translateField(fieldId, sourceText, code);
  };
  return (
    <LanguageSelector
      languages={translation.languages}
      viewLanguage={fieldViewLanguage}
      onLanguageChange={handleFieldLanguageChange}
      hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
      disabled={disabled}
      isTranslating={translation.isTranslating[fieldId] || false}
      size="tiny"
    />
  );
}

function useFieldTranslationView(fieldId, sourceText, translation) {
  useEffect(() => {
    if (translation && fieldId) {
      translation.resetFieldTranslation(fieldId, sourceText || "");
    }
  }, [sourceText, fieldId, translation]);

  const fieldViewLanguage =
    translation && fieldId ? translation.getFieldViewLanguage(fieldId) : "source";
  const isTranslationView = fieldViewLanguage !== "source";
  const displayedText =
    translation && fieldId
      ? translation.getTranslatedText(fieldId, sourceText || "")
      : sourceText;
  const translationError = translation?.translationErrors?.[fieldId];

  return { fieldViewLanguage, isTranslationView, displayedText, translationError };
}

function handleTranslationEdit(translation, fieldId, fieldViewLanguage, text) {
  if (translation && fieldId && fieldViewLanguage !== "source") {
    translation.setFieldTranslation(fieldId, fieldViewLanguage, text);
  }
}

function TranslatableTextarea({
  fieldId,
  value,
  translation,
  onChange,
  disabled = false,
  readOnly = false,
  style,
  ...rest
}) {
  const { fieldViewLanguage, isTranslationView, displayedText, translationError } =
    useFieldTranslationView(fieldId, value, translation);

  return (
    <>
      {translationError ? (
        <div style={{ fontSize: 11, color: "#b91c1c", marginBottom: 4 }}>{translationError}</div>
      ) : null}
      <textarea
        value={isTranslationView ? displayedText : value}
        onChange={(e) => {
          if (isTranslationView) {
            handleTranslationEdit(translation, fieldId, fieldViewLanguage, e.target.value);
          } else {
            onChange(e);
          }
        }}
        readOnly={readOnly}
        disabled={disabled}
        style={style}
        {...rest}
      />
    </>
  );
}

function SectionBodyEditor({
  sectionId,
  body,
  cursor,
  suggestion,
  isActive,
  onBodyChange,
  onSelect,
  onFocus,
  onKeyDown,
  onKeyUp,
  textareaRef,
  translation,
}) {
  const fieldId = sectionFieldId(sectionId, "body");
  const { fieldViewLanguage, isTranslationView, displayedText } = useFieldTranslationView(
    fieldId,
    body,
    translation
  );
  const editValue = isTranslationView ? displayedText : body;
  const displayBefore = editValue.slice(0, cursor);
  const displayAfter = editValue.slice(cursor);
  const ghostSuffix = isActive && !isTranslationView && suggestion ? suggestion : "";

  return (
    <div style={{ position: "relative", minHeight: 120 }}>
      <pre
        aria-hidden
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          margin: 0,
          padding: 12,
          fontFamily: "inherit",
          fontSize: 15,
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          pointerEvents: "none",
          overflow: "hidden",
          color: "transparent",
          border: "1px solid transparent",
          boxSizing: "border-box",
        }}
      >
        {displayBefore}
        <span style={{ color: "var(--secondary-text-color)", opacity: 0.55 }}>{ghostSuffix}</span>
        {displayAfter}
      </pre>
      <textarea
        ref={(el) => textareaRef?.(el)}
        data-section-id={sectionId}
        value={editValue}
        onChange={(e) => {
          if (isTranslationView) {
            handleTranslationEdit(translation, fieldId, fieldViewLanguage, e.target.value);
          } else {
            onBodyChange(e.target.value, e.target.selectionStart);
          }
        }}
        onSelect={onSelect}
        onClick={onSelect}
        onFocus={onFocus}
        onKeyDown={isTranslationView ? undefined : onKeyDown}
        onKeyUp={isTranslationView ? undefined : onKeyUp}
        spellCheck
        style={{
          position: "relative",
          width: "100%",
          minHeight: 120,
          padding: 12,
          fontFamily: "inherit",
          fontSize: 15,
          lineHeight: 1.5,
          border: "1px solid var(--border-color)",
          borderRadius: 6,
          background: "transparent",
          color: "var(--text-color)",
          resize: "vertical",
          boxSizing: "border-box",
        }}
        placeholder={
          ghostSuffix ? "" : "Paragraph text (saved in final letter)…"
        }
      />
    </div>
  );
}

export default function AutocompleteSectionsEditor({
  sections,
  activeSectionIndex,
  cursorInSection,
  suggestion,
  planningSectionIndices = null,
  onSaveSectionGoal,
  onSectionsChange,
  onInvalidateCompletionCache,
  onActiveChange,
  onKeyDown,
  onKeyUp,
  registerTextareaRef,
  translation = null,
}) {
  const localRefs = useRef({});

  const setSectionField = useCallback(
    (index, field, value) => {
      onSectionsChange(
        sections.map((s, i) => (i === index ? { ...s, [field]: value } : s))
      );
    },
    [sections, onSectionsChange]
  );

  const addSection = useCallback(() => {
    const next = [
      ...sections,
      {
        id:
          typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : `section-${Date.now()}`,
        title: "New section",
        description: "",
        body: "",
        plan: "",
        proposal: "",
        proposalSourceBody: "",
      },
    ];
    onSectionsChange(next);
    onActiveChange(next.length - 1, 0);
  }, [sections, onSectionsChange, onActiveChange]);

  const removeSection = useCallback(
    (index) => {
      if (sections.length <= 1) return;
      const next = sections.filter((_, i) => i !== index);
      const newActive = Math.min(activeSectionIndex, next.length - 1);
      onSectionsChange(next);
      onActiveChange(newActive, 0);
    },
    [sections, activeSectionIndex, onSectionsChange, onActiveChange]
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, overflow: "auto", flex: 1 }}>
      {sections.map((section, index) => (
        <div
          key={section.id}
          style={{
            padding: 12,
            border: `1px solid ${
              index === activeSectionIndex ? "var(--accent-color, #3b82f6)" : "var(--border-color)"
            }`,
            borderRadius: 8,
            background: "var(--bg-color)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: 8,
              marginBottom: 8,
            }}
          >
            <input
              type="text"
              value={section.title}
              onChange={(e) => setSectionField(index, "title", e.target.value)}
              onFocus={() => onActiveChange(index, cursorInSection)}
              placeholder="Section title"
              style={{
                flex: 1,
                fontWeight: 600,
                fontSize: 15,
                padding: "6px 8px",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--panel-bg)",
                color: "var(--text-color)",
              }}
            />
            {sections.length > 1 && (
              <button
                type="button"
                onClick={() => removeSection(index)}
                title="Remove section"
                style={{
                  padding: "4px 10px",
                  fontSize: 12,
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                  background: "var(--button-bg)",
                  color: "var(--button-text)",
                  cursor: "pointer",
                }}
              >
                Remove
              </button>
            )}
          </div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4,
              gap: 8,
            }}
          >
            <label
              style={{
                fontSize: 12,
                color: "var(--secondary-text-color)",
                margin: 0,
              }}
            >
              Goal for this section (not in final letter)
            </label>
            <AutocompleteFieldTranslationBar
              fieldId={sectionFieldId(section.id, "description")}
              sourceText={section.description}
              translation={translation}
              disabled={planningSectionIndices?.has?.(index) ?? false}
            />
            <button
              type="button"
              onClick={() => onSaveSectionGoal?.(index)}
              disabled={
                (planningSectionIndices?.has?.(index) ?? false) || !onSaveSectionGoal
              }
              style={{
                padding: "2px 10px",
                fontSize: 12,
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--button-bg)",
                color: "var(--button-text)",
                cursor: planningSectionIndices?.has?.(index) ? "wait" : "pointer",
                flexShrink: 0,
              }}
            >
              {planningSectionIndices?.has?.(index) ? "Planning…" : "Save"}
            </button>
          </div>
          <TranslatableTextarea
            fieldId={sectionFieldId(section.id, "description")}
            value={section.description}
            translation={translation}
            onChange={(e) => setSectionField(index, "description", e.target.value)}
            onFocus={() => onActiveChange(index, 0)}
            rows={2}
            style={{
              width: "100%",
              marginBottom: 10,
              padding: 8,
              fontSize: 13,
              lineHeight: 1.4,
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              background: "var(--panel-bg)",
              color: "var(--secondary-text-color)",
              resize: "vertical",
              boxSizing: "border-box",
            }}
            placeholder="What should this section accomplish?"
          />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4,
              gap: 8,
            }}
          >
            <label
              style={{
                fontSize: 12,
                color: "var(--secondary-text-color)",
                margin: 0,
              }}
            >
              Plan (guides autocomplete — editable; not in final letter)
            </label>
            <AutocompleteFieldTranslationBar
              fieldId={sectionFieldId(section.id, "plan")}
              sourceText={section.plan ?? ""}
              translation={translation}
              disabled={planningSectionIndices?.has?.(index) ?? false}
            />
          </div>
          <TranslatableTextarea
            fieldId={sectionFieldId(section.id, "plan")}
            value={section.plan ?? ""}
            translation={translation}
            onChange={(e) => setSectionField(index, "plan", e.target.value)}
            onFocus={() => onActiveChange(index, 0)}
            readOnly={planningSectionIndices?.has?.(index) ?? false}
            rows={4}
            style={{
              width: "100%",
              marginBottom: 10,
              padding: 8,
              fontSize: 13,
              lineHeight: 1.45,
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              background: "var(--panel-bg)",
              color: planningSectionIndices?.has?.(index)
                ? "var(--secondary-text-color)"
                : "var(--text-color)",
              resize: "vertical",
              boxSizing: "border-box",
              cursor: planningSectionIndices?.has?.(index) ? "wait" : "text",
            }}
            placeholder={
              planningSectionIndices?.has?.(index)
                ? "Regenerating plan…"
                : "3–5 bullets — set the goal and Save, refresh plans, or edit here."
            }
          />
          <details
            style={{
              marginBottom: 10,
              fontSize: 13,
              color: "var(--secondary-text-color)",
            }}
          >
            <summary
              style={{
                cursor: "pointer",
                userSelect: "none",
                marginBottom: 4,
                color: "var(--text-color)",
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span>
                Hidden proposal (full draft for this section — guides autocomplete, not copied to final letter unless you paste it)
                {section.proposal?.trim() &&
                section.proposalSourceBody != null &&
                String(section.body || "") !== String(section.proposalSourceBody)
                  ? " · may be outdated after your edits"
                  : ""}
              </span>
              <span
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                role="presentation"
              >
                <AutocompleteFieldTranslationBar
                  fieldId={sectionFieldId(section.id, "proposal")}
                  sourceText={section.proposal ?? ""}
                  translation={translation}
                  disabled={planningSectionIndices?.has?.(index) ?? false}
                />
              </span>
            </summary>
            <TranslatableTextarea
              fieldId={sectionFieldId(section.id, "proposal")}
              value={section.proposal ?? ""}
              translation={translation}
              onChange={(e) => setSectionField(index, "proposal", e.target.value)}
              onFocus={() => onActiveChange(index, 0)}
              readOnly={planningSectionIndices?.has?.(index) ?? false}
              rows={10}
              style={{
                width: "100%",
                marginTop: 6,
                padding: 8,
                fontSize: 13,
                lineHeight: 1.5,
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "var(--panel-bg)",
                color: planningSectionIndices?.has?.(index)
                  ? "var(--secondary-text-color)"
                  : "var(--text-color)",
                resize: "vertical",
                boxSizing: "border-box",
                cursor: planningSectionIndices?.has?.(index) ? "wait" : "text",
                minHeight: 140,
              }}
              placeholder={
                planningSectionIndices?.has?.(index)
                  ? "Generating full section draft…"
                  : "Full cover-letter text for this section (from Plan). Edit or paste into the paragraph below."
              }
            />
          </details>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 4,
              gap: 8,
            }}
          >
            <label
              style={{
                fontSize: 12,
                color: "var(--secondary-text-color)",
                margin: 0,
              }}
            >
              Paragraph (saved in final letter)
            </label>
            <AutocompleteFieldTranslationBar
              fieldId={sectionFieldId(section.id, "body")}
              sourceText={section.body}
              translation={translation}
            />
          </div>
          <SectionBodyEditor
            sectionId={section.id}
            body={section.body}
            cursor={index === activeSectionIndex ? cursorInSection : section.body.length}
            suggestion={suggestion}
            isActive={index === activeSectionIndex}
            onBodyChange={(value, sel) => {
              onInvalidateCompletionCache?.();
              setSectionField(index, "body", value);
              if (index === activeSectionIndex) {
                onActiveChange(index, sel ?? value.length);
              }
            }}
            onSelect={(e) => {
              onActiveChange(index, e.target.selectionStart ?? 0);
            }}
            onFocus={() => onActiveChange(index, cursorInSection)}
            onKeyDown={onKeyDown}
            onKeyUp={onKeyUp}
            textareaRef={(el) => {
              if (el) localRefs.current[section.id] = el;
              registerTextareaRef(index, el);
            }}
            translation={translation}
          />
        </div>
      ))}
      <button
        type="button"
        onClick={addSection}
        style={{
          alignSelf: "flex-start",
          padding: "8px 14px",
          fontSize: 13,
          border: "1px dashed var(--border-color)",
          borderRadius: 6,
          background: "transparent",
          color: "var(--text-color)",
          cursor: "pointer",
        }}
      >
        + Add section
      </button>
    </div>
  );
}
