/**
 * Shared Save & Copy control for vendor and autocomplete final-letter flows.
 * Copy to clipboard first, brief ✓ feedback, then persist (when in save_copy state). Letter text is not cleared.
 */

import React, { useCallback, useEffect, useState } from "react";

const BUTTON_BASE_STYLE = {
  padding: "4px 8px",
  fontSize: "12px",
  color: "white",
  border: "none",
  borderRadius: 4,
  transition: "background 0.2s ease",
};

/** Time to show ✓ Copied before starting the save request. */
const COPIED_FEEDBACK_MS = 500;

/**
 * @param {object} options
 * @param {string} options.letterText - Current letter body (trimmed for copy/save).
 * @param {(copyText: string) => Promise<void>} [options.onSave] - Persist; receives text copied to clipboard.
 * @param {boolean} [options.saving] - Parent save in flight (after copy feedback).
 * @param {unknown} [options.resetKey] - When this changes, button returns to "Save & Copy".
 * @param {boolean} [options.requireSave] - When true, disable the button if onSave is missing.
 */
export function useSaveAndCopy({
  letterText,
  onSave,
  saving = false,
  resetKey,
  requireSave = false,
}) {
  const [savedState, setSavedState] = useState("save_copy");
  const [saveError, setSaveError] = useState(null);
  /** @type {"idle" | "copied" | "saving"} */
  const [uiPhase, setUiPhase] = useState("idle");
  const trimmed = (letterText || "").trim();
  const busy = uiPhase !== "idle" || saving;
  const disabled = !trimmed || busy || (requireSave && !onSave);

  useEffect(() => {
    setSavedState("save_copy");
    setSaveError(null);
    setUiPhase("idle");
  }, [resetKey]);

  const handleClick = useCallback(async () => {
    if (!trimmed || busy) return;
    setSaveError(null);
    try {
      await navigator.clipboard.writeText(trimmed);
      setUiPhase("copied");
      await new Promise((resolve) => setTimeout(resolve, COPIED_FEEDBACK_MS));
      if (savedState === "save_copy" && onSave) {
        setUiPhase("saving");
        await onSave(trimmed);
        setSavedState("copy");
      }
      setUiPhase("idle");
    } catch (e) {
      setUiPhase("idle");
      setSaveError(e.message || "Failed to save letter");
    }
  }, [trimmed, busy, savedState, onSave]);

  const showCopied = uiPhase === "copied";
  const showSaving = uiPhase === "saving" || saving;
  const showCopyState = savedState === "copy" && !showCopied && !showSaving;

  let label = "Save & Copy";
  if (showCopied) label = "✓ Copied";
  else if (showSaving) label = "Saving...";
  else if (showCopyState) label = "Copy";

  return {
    savedState,
    saveError,
    handleClick,
    disabled,
    saving: showSaving,
    label,
    buttonSavedState: showCopied || showCopyState ? "copy" : "save_copy",
  };
}

export function SaveCopyErrorBanner({ message, style = {} }) {
  if (!message) return null;
  return (
    <div
      style={{
        padding: "4px 12px",
        fontSize: "12px",
        background: "var(--error-bg)",
        color: "var(--error-text)",
        borderBottom: "1px solid var(--border-color)",
        ...style,
      }}
    >
      {message}
    </div>
  );
}

export default function SaveAndCopyButton({
  onClick,
  disabled,
  savedState,
  label,
  id = "save-copy-btn",
  style = {},
}) {
  const background = disabled
    ? "var(--border-color)"
    : savedState === "copy"
      ? "#10b981"
      : "#3b82f6";

  return (
    <button
      type="button"
      id={id}
      onClick={onClick}
      disabled={disabled}
      style={{
        ...BUTTON_BASE_STYLE,
        background,
        cursor: disabled ? "not-allowed" : "pointer",
        ...style,
      }}
    >
      {label ?? (savedState === "copy" ? "Copy" : "Save & Copy")}
    </button>
  );
}
