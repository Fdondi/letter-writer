/**
 * Per-topic agentic flow UI: draft, topic columns (threads), status. Server drives feedback;
 * a loading bar fills over the poll interval and when full we fire one poll (no overlapping requests).
 */
import React, { useEffect, useRef, useState } from "react";
import AgenticThread from "./AgenticThread";

const FEEDBACK_DESCRIPTIONS = {
  instruction: "Style and tone vs instructions.",
  accuracy: "Factual accuracy vs CV.",
  precision: "Job requirements and company report.",
  company_fit: "Company values and culture.",
  user_fit: "Match to your previous letters.",
  human: "Patterns from your past revisions.",
};

const TOPIC_KEYS = ["instruction", "accuracy", "precision", "company_fit", "user_fit", "human"];

export default function AgenticFlow({
  agenticState,
  onFeedbackStart,
  onRefine,
  onSuspend,
  onResume,
  onSaveFinalLetter,
  feedbackVendors = [],
  loading = false,
  error = null,
  saving = false,
  saveError = null,
  pollIntervalMs = 1000,
  onPollState,
}) {
  const hasStartedFeedback = useRef(false);
  const [progress, setProgress] = useState(0);
  const [editedThreads, setEditedThreads] = useState(null);
  const [editedFinalLetter, setEditedFinalLetter] = useState(null);
  const [saveButtonState, setSaveButtonState] = useState("save_copy"); // "save_copy" | "copy"
  const [draftCollapsed, setDraftCollapsed] = useState(false);
  const [feedbackCollapsed, setFeedbackCollapsed] = useState(false);
  const startRef = useRef(Date.now());
  const pollInFlightRef = useRef(false);
  const status = agenticState?.status;
  const draftLetter = agenticState?.draft_letter;
  const finalLetter = agenticState?.final_letter;
  const threadsFromState = agenticState?.threads || {};
  const threads = editedThreads ?? threadsFromState;
  const ongoing = agenticState?.ongoing;
  const round = agenticState?.round ?? 0;
  const cost = agenticState?.cost ?? 0;
  const feedbackSuspended = agenticState?.feedback_suspended === true;
  const topicMeta = agenticState?.topic_meta || {};
  const canEditThreads = status === "feedback_done" || (status === "feedback" && ongoing === false);
  const canSuspendOrResume = status === "feedback";
  const anyCanResume = canSuspendOrResume && Object.values(topicMeta).some((m) => m?.suspended && !m?.done);
  const displayFinalLetter = editedFinalLetter ?? finalLetter ?? "";

  // Start feedback once when draft is ready (status feedback, round 0) and we have vendors
  useEffect(() => {
    if (
      status !== "feedback" ||
      (round !== 0 && round !== undefined) ||
      !feedbackVendors?.length ||
      hasStartedFeedback.current ||
      loading
    ) {
      return;
    }
    hasStartedFeedback.current = true;
    onFeedbackStart?.();
  }, [status, round, feedbackVendors?.length, loading, onFeedbackStart]);

  // Loading bar fills over pollIntervalMs; when full we fire one poll (serial, no overlap)
  useEffect(() => {
    if (status !== "feedback" || ongoing === false || !onPollState) return;
    const tickMs = 80;
    const id = setInterval(() => {
      if (pollInFlightRef.current) return;
      const elapsed = Date.now() - startRef.current;
      const p = Math.min(1, elapsed / pollIntervalMs);
      setProgress(p);
      if (p >= 1) {
        pollInFlightRef.current = true;
        Promise.resolve(onPollState()).then(() => {
          pollInFlightRef.current = false;
          startRef.current = Date.now();
          setProgress(0);
        });
      }
    }, tickMs);
    return () => clearInterval(id);
  }, [status, ongoing, onPollState, pollIntervalMs]);

  useEffect(() => {
    if (ongoing === false) setProgress(0);
  }, [ongoing]);

  // When feedback is complete, init editable copy once so user can edit/remove comments before Refine
  useEffect(() => {
    if (!canEditThreads || !threadsFromState || Object.keys(threadsFromState).length === 0) {
      if (status === "done") setEditedThreads(null);
      return;
    }
    if (editedThreads == null) setEditedThreads(JSON.parse(JSON.stringify(threadsFromState)));
  }, [canEditThreads, threadsFromState, status]);

  // When we get a final letter from server, init editable text (or reset when leaving done)
  useEffect(() => {
    if (status === "done" && finalLetter != null) {
      setEditedFinalLetter((prev) => (prev == null ? finalLetter : prev));
      setDraftCollapsed(true);
      setFeedbackCollapsed(true);
    } else {
      setEditedFinalLetter(null);
      setSaveButtonState("save_copy");
    }
  }, [status, finalLetter]);

  const handleRemoveComment = (topic, commentIndex) => {
    setEditedThreads((prev) => {
      const base = prev ?? threadsFromState;
      const list = [...(base[topic] || [])];
      list.splice(commentIndex, 1);
      return { ...base, [topic]: list };
    });
  };

  const handleEditComment = (topic, commentIndex, newText) => {
    setEditedThreads((prev) => {
      const base = prev ?? threadsFromState;
      const list = (base[topic] || []).map((c, i) =>
        i === commentIndex ? { ...c, text: newText } : c
      );
      return { ...base, [topic]: list };
    });
  };

  const handleRefine = async () => {
    await onRefine(editedThreads ?? threadsFromState);
  };

  const handleFinalLetterChange = (e) => {
    const next = e.target.value;
    setEditedFinalLetter(next);
    setSaveButtonState("save_copy");
  };

  const handleSaveCopy = async () => {
    const text = editedFinalLetter ?? finalLetter ?? "";
    if (!text.trim()) return;
    if (saveButtonState === "save_copy" && onSaveFinalLetter) {
      try {
        await onSaveFinalLetter(text);
      } catch (err) {
        return; // Parent sets saveError; keep button as "Save & Copy" so user can retry
      }
    }
    try {
      await navigator.clipboard.writeText(text);
      setSaveButtonState("copy");
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  if (!agenticState && !loading) {
    return (
      <div style={{ padding: 20, color: "var(--secondary-text-color)" }}>
        No agentic state. Start the agentic flow to see draft and feedback threads.
      </div>
    );
  }

  if (loading && !agenticState) {
    return (
      <div style={{ padding: 20, color: "var(--text-color)" }}>
        Loading…
      </div>
    );
  }

  return (
    <div style={{ padding: 16 }}>
      {error && (
        <div
          style={{
            padding: 12,
            marginBottom: 16,
            backgroundColor: "#fef2f2",
            color: "#b91c1c",
            borderRadius: 8,
            border: "1px solid #fecaca",
          }}
        >
          {error}
        </div>
      )}

      <div style={{ marginBottom: 16, fontSize: 14, color: "var(--text-color)" }}>
        Status: <strong>{status}</strong>
        {status === "feedback" && ongoing === true && !feedbackSuspended && " · Generating feedback…"}
        {status === "feedback" && feedbackSuspended && " · Suspended"}
        {(status === "feedback_done" || (status === "feedback" && ongoing === false && !feedbackSuspended)) && " · Completed"}
        {cost > 0 && ` · Cost: $${cost.toFixed(4)}`}
      </div>

      {status === "feedback" && (ongoing === true || progress > 0) && (
        <div style={{ marginBottom: 16 }}>
          <div
            style={{
              height: 6,
              backgroundColor: "var(--border-color)",
              borderRadius: 3,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${progress * 100}%`,
                backgroundColor: "var(--header-bg)",
                borderRadius: 3,
                transition: "width 0.1s linear",
              }}
            />
          </div>
        </div>
      )}

      {(status === "feedback" || status === "feedback_done" || status === "done") && draftLetter && (
        <div
          style={{
            marginBottom: 12,
            backgroundColor: "var(--panel-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          <button
            type="button"
            onClick={() => setDraftCollapsed((c) => !c)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "12px 16px",
              fontSize: 13,
              fontWeight: 600,
              color: "var(--text-color)",
              background: "var(--panel-bg)",
              border: "none",
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            <span style={{ fontSize: 10 }}>{draftCollapsed ? "▶" : "▼"}</span>
            Draft letter
          </button>
          {!draftCollapsed && (
            <div
              style={{
                padding: "0 16px 16px",
                fontSize: 13,
                color: "var(--text-color)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                maxHeight: 200,
                overflowY: "auto",
              }}
            >
              {draftLetter}
            </div>
          )}
        </div>
      )}

      {(status === "feedback" || status === "feedback_done" || status === "done") && (
        <div
          style={{
            marginBottom: 20,
            backgroundColor: "var(--panel-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          <button
            type="button"
            onClick={() => setFeedbackCollapsed((c) => !c)}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "12px 16px",
              fontSize: 13,
              fontWeight: 600,
              color: "var(--text-color)",
              background: "var(--panel-bg)",
              border: "none",
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            <span style={{ fontSize: 10 }}>{feedbackCollapsed ? "▶" : "▼"}</span>
            Agent feedback
          </button>
          {!feedbackCollapsed && (
            <>
              {canSuspendOrResume && (ongoing === true || anyCanResume) && (
                <div
                  style={{
                    padding: "0 16px 12px",
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  {ongoing === true && onSuspend && (
                    <button
                      type="button"
                      onClick={() => onSuspend(true, null)}
                      disabled={loading}
                      style={{
                        padding: "6px 12px",
                        fontSize: 13,
                        backgroundColor: "var(--panel-bg)",
                        color: "var(--text-color)",
                        border: "1px solid var(--border-color)",
                        borderRadius: 6,
                        cursor: loading ? "not-allowed" : "pointer",
                      }}
                    >
                      Suspend all
                    </button>
                  )}
                  {anyCanResume && onResume && (
                    <button
                      type="button"
                      onClick={() => onResume(true, null)}
                      disabled={loading}
                      style={{
                        padding: "6px 12px",
                        fontSize: 13,
                        backgroundColor: "#0d9488",
                        color: "white",
                        border: "none",
                        borderRadius: 6,
                        cursor: loading ? "not-allowed" : "pointer",
                      }}
                    >
                      Resume all
                    </button>
                  )}
                </div>
              )}
              <div
                style={{
                  padding: "0 16px 16px",
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                  gap: 16,
                }}
              >
                {TOPIC_KEYS.map((topic) => (
                  <AgenticThread
                    key={topic}
                    topic={topic}
                    thread={threads[topic] || []}
                    topicMeta={topicMeta[topic]}
                    description={FEEDBACK_DESCRIPTIONS[topic]}
                    canEdit={canEditThreads}
                    canSuspend={canSuspendOrResume && ongoing === true}
                    canResume={canSuspendOrResume && topicMeta[topic]?.suspended && !topicMeta[topic]?.done}
                    onSuspend={() => onSuspend?.(false, [topic])}
                    onResume={() => onResume?.(false, [topic])}
                    onRemoveComment={handleRemoveComment}
                    onEditComment={handleEditComment}
                  />
                ))}
              </div>
              {(status === "feedback_done" || (status === "feedback" && ongoing === false)) && (
                <div style={{ padding: "0 16px 16px", display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <button
                    type="button"
                    onClick={handleRefine}
                    disabled={loading}
                    style={{
                      padding: "8px 16px",
                      backgroundColor: loading ? "var(--header-bg)" : "#16a34a",
                      color: "white",
                      border: "none",
                      borderRadius: 6,
                      cursor: loading ? "not-allowed" : "pointer",
                      fontSize: 14,
                    }}
                  >
                    {loading ? "Refining…" : "Use for final draft"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {status === "done" && (finalLetter != null || displayFinalLetter) && (
        <div
          style={{
            marginBottom: 20,
            padding: 16,
            backgroundColor: "var(--panel-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: 8,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-color)" }}>Final letter</div>
            <button
              type="button"
              onClick={handleSaveCopy}
              disabled={saving}
              style={{
                padding: "8px 16px",
                backgroundColor: saveButtonState === "copy" ? "#10b981" : "#3b82f6",
                color: "white",
                border: "none",
                borderRadius: 6,
                cursor: saving ? "not-allowed" : "pointer",
                fontSize: 14,
                fontWeight: 600,
                minWidth: 120,
              }}
            >
              {saving ? "Saving…" : saveButtonState === "save_copy" ? "Save & Copy" : "Copy"}
            </button>
          </div>
          {saveError && (
            <div
              style={{
                marginBottom: 8,
                padding: "8px 12px",
                backgroundColor: "#fef2f2",
                color: "#b91c1c",
                fontSize: 12,
                borderRadius: 6,
                border: "1px solid #fecaca",
              }}
            >
              {saveError}
            </div>
          )}
          <textarea
            value={displayFinalLetter}
            onChange={handleFinalLetterChange}
            style={{
              width: "100%",
              minHeight: 200,
              maxHeight: 400,
              fontSize: 13,
              color: "var(--text-color)",
              backgroundColor: "var(--bg-color)",
              border: "1px solid var(--border-color)",
              borderRadius: 6,
              padding: 12,
              resize: "vertical",
              fontFamily: "inherit",
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          />
        </div>
      )}
    </div>
  );
}
