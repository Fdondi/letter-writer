/**
 * Per-topic agentic flow UI: draft, topic columns (threads), status. Server drives feedback;
 * a loading bar fills over the poll interval and when full we fire one poll (no overlapping requests).
 */
import React, { useEffect, useRef, useState } from "react";
import AgenticThread from "./AgenticThread";
import { useTranslation } from "../utils/useTranslation";
import LanguageSelector from "./LanguageSelector";

const FEEDBACK_DESCRIPTIONS = {
  instruction: "Style and tone vs instructions.",
  company_fit: "Company values and culture.",
  precision: "Job requirements and company report.",
  user_fit: "Match to your previous letters.",
  human: "Patterns from your past revisions.",
  accuracy: "CV accuracy check (last word).",
};

const TOPIC_KEYS = ["instruction", "company_fit", "precision", "user_fit", "human", "accuracy"];
const VOTE_COUNTDOWN_SECONDS = 15;

const DRAFT_FIELD_ID = "agentic_draft";

function DraftWithTranslation({ draftText, translation }) {
  useEffect(() => {
    if (translation) translation.resetFieldTranslation(DRAFT_FIELD_ID, draftText);
  }, [draftText, translation]);

  const displayedText = translation
    ? translation.getTranslatedText(DRAFT_FIELD_ID, draftText)
    : draftText;
  const viewLanguage = translation ? translation.getFieldViewLanguage(DRAFT_FIELD_ID) : "source";

  const handleLanguageChange = async (code) => {
    if (!translation) return;
    translation.setFieldViewLanguage(DRAFT_FIELD_ID, code);
    if (code === "source") return;
    if (draftText) await translation.translateField(DRAFT_FIELD_ID, draftText, code);
  };

  return (
    <div style={{ position: "relative", padding: "0 16px 16px" }}>
      {translation && (
        <div
          style={{
            position: "absolute",
            right: 16,
            top: -22,
            zIndex: 10,
            background: "var(--panel-bg)",
            border: "1px solid var(--border-color)",
            borderBottom: "none",
            borderTopLeftRadius: 4,
            borderTopRightRadius: 4,
            padding: "2px 2px 2px 4px",
          }}
        >
          <LanguageSelector
            languages={translation.languages}
            viewLanguage={viewLanguage}
            onLanguageChange={handleLanguageChange}
            hasTranslation={(code) => translation.hasTranslation(DRAFT_FIELD_ID, code)}
            isTranslating={translation.isTranslating[DRAFT_FIELD_ID] || false}
            size="tiny"
          />
        </div>
      )}
      <div
        style={{
          paddingTop: translation ? 32 : 0,
          fontSize: 13,
          color: "var(--text-color)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          maxHeight: 200,
          overflowY: "auto",
        }}
      >
        {displayedText}
      </div>
    </div>
  );
}

export default function AgenticFlow({
  agenticState,
  onFeedbackStart,
  onVote,
  onRefine,
  onSuspend,
  onResume,
  onAddRound,
  feedbackVendors = [],
  vendorColors = {},
  loading = false,
  error = null,
  pollIntervalMs = 1000,
  onPollState,
}) {
  const hasStartedFeedback = useRef(false);
  const [progress, setProgress] = useState(0);
  const [editedThreads, setEditedThreads] = useState(null);
  const [draftCollapsed, setDraftCollapsed] = useState(false);
  const [feedbackCollapsed, setFeedbackCollapsed] = useState(false);
  const [draftTab, setDraftTab] = useState(null); // selected draft vendor tab
  const [voteCountdown, setVoteCountdown] = useState(null);
  const startRef = useRef(Date.now());
  const pollInFlightRef = useRef(false);
  const hasAutoStartedVoteRef = useRef(false);
  const hasAutoStartedRefineRef = useRef(false);
  const status = agenticState?.status;
  const draftLetter = agenticState?.draft_letter;
  const draftLetters = agenticState?.draft_letters ?? (draftLetter != null && agenticState?.draft_vendor ? { [agenticState.draft_vendor]: draftLetter } : {});
  const draftVendorList = Object.keys(draftLetters).filter(Boolean);
  const threadsFromState = agenticState?.threads || {};
  const threads = editedThreads ?? threadsFromState;
  const ongoing = agenticState?.ongoing;
  const round = agenticState?.round ?? 0;
  const cost = agenticState?.cost ?? 0;
  const feedbackSuspended = agenticState?.feedback_suspended === true;
  const topicMeta = agenticState?.topic_meta || {};
  const maxRounds = agenticState?.max_rounds ?? 3;
  const vendorErrors = agenticState?.vendor_errors || {};
  const hasVendorErrors = Object.keys(vendorErrors).length > 0;
  const draftVotes = agenticState?.draft_votes || null;
  const hasVotes = draftVotes != null && Object.keys(draftVotes).length > 0;
  // Active = not done. Button and editing when active count is 0.
  const activeTopicCount = TOPIC_KEYS.filter(
    (topic) => !topicMeta[topic]?.done
  ).length;
  const allTopicsInactive = activeTopicCount === 0;
  const canEditThreads = status === "feedback_done" || (status === "feedback" && allTopicsInactive);
  const canSuspendOrResume = status === "feedback";
  const anyCanResume = canSuspendOrResume && feedbackSuspended;
  const canVoteOnDrafts =
    (status === "feedback_done" || (status === "feedback" && allTopicsInactive)) &&
    !hasVotes &&
    draftVendorList.length > 1 &&
    Boolean(onVote);
  const canAutoRefine =
    (status === "feedback_done" || (status === "feedback" && allTopicsInactive)) &&
    (hasVotes || draftVendorList.length <= 1) &&
    Boolean(onRefine);

  const translation = useTranslation();

  // Start feedback once when a fresh draft is ready (status feedback, round 0) and we have vendors.
  // If a prior run ended, clear the one-shot guard so a new run can auto-start again.
  useEffect(() => {
    if (status !== "feedback" || ongoing === false) {
      hasStartedFeedback.current = false;
    }
  }, [status, ongoing, draftLetter, draftVendorList]);

  // Start feedback once when draft is ready.
  useEffect(() => {
    if (
      status !== "feedback" ||
      ongoing === true ||
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

  useEffect(() => {
    if (status === "done") {
      setDraftCollapsed(true);
      setFeedbackCollapsed(true);
    }
  }, [status]);

  useEffect(() => {
    if (!canVoteOnDrafts) {
      setVoteCountdown(null);
      hasAutoStartedVoteRef.current = false;
      return;
    }
    if (voteCountdown == null && !hasAutoStartedVoteRef.current) {
      setVoteCountdown(VOTE_COUNTDOWN_SECONDS);
    }
  }, [canVoteOnDrafts, voteCountdown]);

  useEffect(() => {
    if (!canVoteOnDrafts || voteCountdown == null || voteCountdown <= 0 || loading) return;
    const timer = setTimeout(() => {
      setVoteCountdown((prev) => (prev != null && prev > 0 ? prev - 1 : null));
    }, 1000);
    return () => clearTimeout(timer);
  }, [canVoteOnDrafts, voteCountdown, loading]);

  useEffect(() => {
    if (!canVoteOnDrafts || voteCountdown !== 0 || loading || hasAutoStartedVoteRef.current) return;
    hasAutoStartedVoteRef.current = true;
    setVoteCountdown(null);
    onVote?.();
  }, [canVoteOnDrafts, voteCountdown, loading, onVote]);

  useEffect(() => {
    if (!canAutoRefine) {
      hasAutoStartedRefineRef.current = false;
      return;
    }
    if (loading || hasAutoStartedRefineRef.current) return;
    hasAutoStartedRefineRef.current = true;
    onRefine?.(editedThreads ?? threadsFromState);
  }, [canAutoRefine, loading, onRefine, editedThreads, threadsFromState]);

  // Default draft tab when draft vendors change
  useEffect(() => {
    if (draftVendorList.length > 0 && !draftTab) setDraftTab(draftVendorList[0]);
    if (draftVendorList.length > 0 && draftTab && !draftVendorList.includes(draftTab)) setDraftTab(draftVendorList[0]);
  }, [draftVendorList, draftTab]);

  const handleRemoveComment = (topic, commentIndex) => {
    setEditedThreads((prev) => {
      const base = prev ?? threadsFromState;
      const list = (base[topic] || []).map((comment, idx) => {
        if (idx !== commentIndex) return comment;
        const votes = comment?.votes || {};
        return {
          ...comment,
          removed: true,
          votes: {
            up: Array.isArray(votes.up) ? [...votes.up] : [],
            down: Array.isArray(votes.down) ? [...votes.down] : [],
            abstain: Array.isArray(votes.abstain) ? [...votes.abstain] : [],
          },
        };
      });
      return { ...base, [topic]: list };
    });
  };

  const handleReinstateComment = (topic, commentIndex) => {
    setEditedThreads((prev) => {
      const base = prev ?? threadsFromState;
      const list = (base[topic] || []).map((comment, idx) => {
        if (idx !== commentIndex) return comment;
        const votes = comment?.votes || {};
        const votesByRoundRaw = comment?.votes_by_round || {};
        const votesByRound = {};
        Object.entries(votesByRoundRaw).forEach(([roundKey, bucket]) => {
          if (!bucket || typeof bucket !== "object") return;
          votesByRound[roundKey] = {
            up: Array.isArray(bucket.up) ? [...bucket.up] : [],
            down: [],
            abstain: Array.isArray(bucket.abstain) ? [...bucket.abstain] : [],
            reasons: bucket.reasons && typeof bucket.reasons === "object" ? { ...bucket.reasons } : {},
          };
        });
        return {
          ...comment,
          removed: false,
          votes: {
            up: Array.isArray(votes.up) ? [...votes.up] : [],
            down: [],
            abstain: Array.isArray(votes.abstain) ? [...votes.abstain] : [],
          },
          votes_by_round: votesByRound,
        };
      });
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

  const handleRemoveAddendum = (topic, commentIndex, addendumIndex) => {
    setEditedThreads((prev) => {
      const base = prev ?? threadsFromState;
      const list = (base[topic] || []).map((c, i) => {
        if (i !== commentIndex) return c;
        const addendums = [...(c.addendums || [])];
        addendums.splice(addendumIndex, 1);
        return { ...c, addendums };
      });
      return { ...base, [topic]: list };
    });
  };

  const handleEditAddendum = (topic, commentIndex, addendumIndex, newText) => {
    setEditedThreads((prev) => {
      const base = prev ?? threadsFromState;
      const list = (base[topic] || []).map((c, i) => {
        if (i !== commentIndex) return c;
        const addendums = (c.addendums || []).map((a, j) =>
          j === addendumIndex ? { ...a, text: newText } : a
        );
        return { ...c, addendums };
      });
      return { ...base, [topic]: list };
    });
  };

  const handleVote = () => {
    hasAutoStartedVoteRef.current = true;
    setVoteCountdown(null);
    onVote?.();
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

      {hasVendorErrors && !error && (
        <div
          style={{
            padding: 12,
            marginBottom: 16,
            backgroundColor: "var(--warning-bg, #fef9c3)",
            color: "var(--warning-text, #854d0e)",
            borderRadius: 8,
            border: "1px solid var(--warning-border, #fde047)",
          }}
        >
          <strong>Some vendors were skipped:</strong>
          <ul style={{ margin: "8px 0 0", paddingLeft: 20 }}>
            {Object.entries(vendorErrors).map(([vendor, msg]) => (
              <li key={vendor}>
                <strong>{vendor}</strong>: {msg}
              </li>
            ))}
          </ul>
          <div style={{ marginTop: 8, fontSize: 13, opacity: 0.9 }}>
            The flow continued with the other vendors. You can change models in Settings and try again for the failed ones.
          </div>
        </div>
      )}

      <div style={{ marginBottom: 16, fontSize: 14, color: "var(--text-color)" }}>
        Status: <strong>{status}</strong>
        {status === "feedback" && ongoing === true && !feedbackSuspended && " · Generating feedback…"}
        {status === "feedback" && feedbackSuspended && " · Suspended"}
        {(status === "feedback_done" || (status === "feedback" && allTopicsInactive && !feedbackSuspended)) && " · Completed"}
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

      {(status === "draft" || status === "feedback" || status === "feedback_done" || status === "done") && draftVendorList.length > 0 && (
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
            Draft letter{draftVendorList.length > 1 ? "s" : ""}
          </button>
              {!draftCollapsed && (
            <>
              {draftVendorList.length > 1 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "8px 16px 0", borderBottom: "1px solid var(--border-color)" }}>
                  {draftVendorList.map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setDraftTab(v)}
                      style={{
                        padding: "6px 12px",
                        fontSize: 12,
                        fontWeight: draftTab === v ? 600 : 400,
                        color: "var(--text-color)",
                        background: draftTab === v ? "var(--header-bg)" : "transparent",
                        border: "1px solid var(--border-color)",
                        borderRadius: 6,
                        cursor: "pointer",
                      }}
                    >
                      {v}
                    </button>
                  ))}
                </div>
              )}
              <DraftWithTranslation
                draftText={(draftVendorList.length > 1 ? draftLetters[draftTab] : draftLetter) ?? ""}
                translation={translation}
              />
            </>
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
                      onClick={() => onSuspend()}
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
                      onClick={() => onResume()}
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
                  {onAddRound && (status === "feedback" || status === "feedback_done") && (
                    <button
                      type="button"
                      onClick={() => onAddRound(true, null)}
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
                      title={`Add one more round for all topics (max ${maxRounds + 1})`}
                    >
                      Add +1 round (all)
                    </button>
                  )}
                </div>
              )}
              <div
                style={{
                  padding: "0 16px 16px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
              >
                {TOPIC_KEYS.map((topic, idx) => (
                  <React.Fragment key={topic}>
                    <AgenticThread
                      topic={topic}
                      thread={threads[topic] || []}
                      topicMeta={topicMeta[topic]}
                      description={FEEDBACK_DESCRIPTIONS[topic]}
                      vendorColors={vendorColors}
                      translation={translation}
                      canEdit={canEditThreads}
                      canSuspend={false}
                      canResume={false}
                      onSuspend={undefined}
                      onResume={undefined}
                      onAddRound={onAddRound ? () => onAddRound(false, topic) : undefined}
                      addRoundLoading={loading}
                      onRemoveComment={handleRemoveComment}
                      onReinstateComment={handleReinstateComment}
                      onEditComment={handleEditComment}
                      onRemoveAddendum={handleRemoveAddendum}
                      onEditAddendum={handleEditAddendum}
                    />
                    {idx < TOPIC_KEYS.length - 1 && (
                      <div
                        aria-hidden
                        style={{
                          alignSelf: "center",
                          color: "var(--secondary-text-color)",
                          fontSize: 16,
                          userSelect: "none",
                        }}
                      >
                        ↓
                      </div>
                    )}
                  </React.Fragment>
                ))}
              </div>
              {(status === "feedback_done" || (status === "feedback" && allTopicsInactive)) && (
                <div style={{ padding: "0 16px 16px" }}>
                  {hasVotes && (
                    <div
                      style={{
                        marginBottom: 12,
                        padding: 12,
                        backgroundColor: "var(--bg-color)",
                        border: "1px solid var(--border-color)",
                        borderRadius: 8,
                      }}
                    >
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "var(--text-color)" }}>
                        Vote results
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        {Object.entries(draftVotes)
                          .sort(([, a], [, b]) => b - a)
                          .map(([vendor, count]) => (
                            <span
                              key={vendor}
                              style={{
                                padding: "4px 10px",
                                borderRadius: 12,
                                fontSize: 12,
                                fontWeight: 600,
                                backgroundColor: vendorColors[vendor]
                                  ? `${vendorColors[vendor]}33`
                                  : "var(--panel-bg)",
                                border: `1px solid ${vendorColors[vendor] || "var(--border-color)"}`,
                                color: "var(--text-color)",
                              }}
                            >
                              {vendor}: {count} vote{count !== 1 ? "s" : ""}
                            </span>
                          ))}
                      </div>
                    </div>
                  )}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                    {!hasVotes && draftVendorList.length > 1 && onVote && (
                      <button
                        type="button"
                        onClick={handleVote}
                        disabled={loading}
                        style={{
                          padding: "8px 16px",
                          backgroundColor: loading ? "var(--header-bg)" : "#6366f1",
                          color: "white",
                          border: "none",
                          borderRadius: 6,
                          cursor: loading ? "not-allowed" : "pointer",
                          fontSize: 14,
                        }}
                      >
                        {loading
                          ? "Voting…"
                          : voteCountdown != null
                            ? `Vote on drafts (${voteCountdown}s)`
                            : "Vote on drafts"}
                      </button>
                    )}
                    {(hasVotes || draftVendorList.length <= 1) && (
                      <div style={{ fontSize: 13, color: "var(--secondary-text-color)" }}>
                        {loading ? "Refining…" : "Preparing final draft…"}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
