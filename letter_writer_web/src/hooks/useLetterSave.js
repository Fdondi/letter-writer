import { useState, useEffect, useRef, useCallback } from "react";

const AUTO_SAVE_MS = 15 * 60 * 1000;

/**
 * Copy/save controls with auto-save after 15 minutes of inactivity when dirty.
 * @param {object} opts
 * @param {() => string} opts.getFullText - Current letter text to copy/save
 * @param {(text: string) => Promise<void>} [opts.onSave]
 * @param {boolean} [opts.saving=false]
 * @param {*} opts.contentRevision - Changes when letter content changes (resets dirty + idle timer)
 */
export function useLetterSave({ getFullText, onSave, saving = false, contentRevision }) {
  const [isDirty, setIsDirty] = useState(true);
  const [copyFeedback, setCopyFeedback] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const copyFeedbackTimerRef = useRef(null);
  const saveInFlightRef = useRef(false);
  const getFullTextRef = useRef(getFullText);
  getFullTextRef.current = getFullText;

  const runSave = useCallback(async () => {
    if (!onSave || saveInFlightRef.current || saving) return false;
    const fullText = getFullTextRef.current();
    if (!fullText?.trim()) {
      setSaveError("No letter text to save");
      return false;
    }
    saveInFlightRef.current = true;
    setSaveError(null);
    try {
      await onSave(fullText);
      setIsDirty(false);
      return true;
    } catch (e) {
      setSaveError(e.message || "Failed to save letter");
      return false;
    } finally {
      saveInFlightRef.current = false;
    }
  }, [onSave, saving]);

  useEffect(() => {
    setIsDirty(true);
    setSaveError(null);
    setCopyFeedback(null);
  }, [contentRevision]);

  useEffect(() => {
    return () => {
      if (copyFeedbackTimerRef.current) clearTimeout(copyFeedbackTimerRef.current);
    };
  }, []);

  const handleCopy = useCallback(async () => {
    const fullText = getFullTextRef.current();
    setSaveError(null);
    try {
      await navigator.clipboard.writeText(fullText);
      setCopyFeedback("success");
      await new Promise((resolve) => {
        copyFeedbackTimerRef.current = setTimeout(resolve, 1000);
      });
      setCopyFeedback(null);
    } catch (e) {
      if (copyFeedbackTimerRef.current) clearTimeout(copyFeedbackTimerRef.current);
      setCopyFeedback(null);
      setSaveError(e.message || "Failed to copy text to clipboard");
    }
  }, []);

  const handleSave = useCallback(async () => {
    if (!isDirty) return;
    await runSave();
  }, [isDirty, runSave]);

  useEffect(() => {
    if (!isDirty || !onSave || saving) return undefined;
    const timer = setTimeout(() => {
      runSave();
    }, AUTO_SAVE_MS);
    return () => clearTimeout(timer);
  }, [isDirty, contentRevision, onSave, saving, runSave]);

  return { isDirty, handleCopy, handleSave, copyFeedback, saveError };
}
