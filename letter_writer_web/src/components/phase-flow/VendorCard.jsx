import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { phases as phaseModules } from "../phases";
import { fetchWithHeartbeat } from "../../utils/apiHelpers";
import { useTranslation } from "../../utils/useTranslation";
import LanguageSelector from "../LanguageSelector";
import { FEEDBACK_TYPES, firstFeedbackKeyWithItems, mergeCategoryItems } from "../phases/feedbackItemUtils";
import { CardStatus } from "./cardStatus";
import { deepCloneJson } from "./deepCloneJson";
import { computeEditsDifferFromReference } from "./computeEditsDifferFromReference";
import ExpandOutIcon from "./ExpandOutIcon";
import EditableField from "./EditableField";
import EditableFeedback from "./EditableFeedback";
import { cardStyle, cardHeaderStyle, contentContainerStyle, iconButtonStyle } from "./vendorCardStyles";

export default function VendorCard({
  vendor,
  phases,
  phaseObj,
  data = null,
  status = "idle",
  error = null,
  previousPhaseApproved = true,
  allPhasesDone = false,
  onEditChange,
  onSaveFeedbackOverride,
  onApprove,
  sessionId,
  documentId,
  draftFeedbackRegistryRef,
  onStatusChange,
  disabled = false,
  onPhaseComplete,
  setStatus,
  setData,
  setError,
  onRetryPhaseFetch,
  onClearPhaseFetchError,
  onExpand,
  isExpanded,
  onCloseExpand,
  useOverlayWidth,
  onAfterApproveInExpanded,
  inputClusterText,
  broadcastInputCluster,
}) {
  const cardPhase = phaseObj?.phase || null;

  const [approved, setApproved] = React.useState(false);
  const [approvedEditsBaseline, setApprovedEditsBaseline] = React.useState(null);
  const [edits, setEdits] = React.useState({});
  const [phaseCost, setPhaseCost] = React.useState(0);
  const [runningTotal, setRunningTotal] = React.useState(0);

  React.useEffect(() => {
    if (data && status === "success") {
      try {
        const phaseModule = phaseModules[cardPhase];
        if (phaseModule && phaseModule.initializeEditsFromData) {
          const initialEdits = phaseModule.initializeEditsFromData(data);
          if (initialEdits && Object.keys(initialEdits).length > 0) {
            setEdits(initialEdits);
          }
        }

        if (data.cost !== undefined) {
          setRunningTotal(data.cost);
          setPhaseCost(data.cost);
        }
      } catch (e) {
        console.error(`Error initializing edits from data for ${cardPhase}:`, e, data);
        setError(`Failed to parse ${cardPhase} data: ${e.message}`);
      }
    }
  }, [data, status, cardPhase, setError]);

  const cardPhaseData = data || {};
  const isCardPhaseApproved = approved;
  const cardPhaseEdits = edits;
  const isLoading = status === "loading";
  const cardError = error;

  const [selectedFeedbackTab, setSelectedFeedbackTab] = useState(null);
  const [feedbackItemApprovals, setFeedbackItemApprovals] = useState({});
  const [collapsed, setCollapsed] = useState(false);

  const translation = useTranslation();

  const lastSuccessDataRef = useRef(null);
  const registeredStatusRef = useRef(null);

  React.useEffect(() => {
    if (!cardPhase || !onStatusChange) return;

    const hasData = data !== null && Object.keys(data).length > 0;

    let newStatus = null;
    if (approved) {
      newStatus = CardStatus.APPROVED;
    } else if (status === "loading") {
      newStatus = CardStatus.PENDING;
    } else if (status === "error") {
      newStatus = CardStatus.PENDING;
    } else if (status === "success" && hasData) {
      newStatus = CardStatus.READY;
    }

    if (newStatus && newStatus !== registeredStatusRef.current) {
      registeredStatusRef.current = newStatus;
      onStatusChange(newStatus);
    }
  }, [status, data, approved, cardPhase, onStatusChange]);

  const phaseModule = phaseModules[cardPhase];

  React.useEffect(() => {
    if (cardPhase && phaseModule?.initializeFeedbackFromData && data) {
      try {
        const feedbackData = phaseModule.initializeFeedbackFromData(data);
        if (feedbackData && feedbackData.feedbackKeys && feedbackData.feedbackKeys.length > 0) {
          setFeedbackItemApprovals((prev) => {
            const next = { ...prev };
            feedbackData.feedbackKeys.forEach((k) => {
              const items = mergeCategoryItems(feedbackData.feedback, {}, k);
              items.forEach((it) => {
                if (it.type === "PLEASE_FIX" && next[it.id] === undefined) {
                  next[it.id] = false;
                }
              });
            });
            return next;
          });
        }
      } catch (e) {
        console.error(`Error initializing feedback from data for ${cardPhase}:`, e, data);
      }
    }
  }, [cardPhase, data, phaseModule]);

  React.useEffect(() => {
    if (!data || status !== "success") return;
    if (lastSuccessDataRef.current === data) return;
    lastSuccessDataRef.current = data;
    if (!approved) return;
    const pm = phaseModules[cardPhase];
    if (!pm?.initializeEditsFromData) return;
    const initialEdits = pm.initializeEditsFromData(data);
    if (!initialEdits || Object.keys(initialEdits).length === 0) return;
    setApprovedEditsBaseline(deepCloneJson(initialEdits));
  }, [data, status, approved, cardPhase]);

  let feedbackData = null;
  let feedback = {};
  let feedbackKeys = [];
  try {
    if (cardPhase && phaseModule?.initializeFeedbackFromData && data) {
      feedbackData = phaseModule.initializeFeedbackFromData(data);
      feedback = feedbackData?.feedback || {};
      feedbackKeys = feedbackData?.feedbackKeys || [];
    }
  } catch (e) {
    console.error(`Error getting feedback data for ${cardPhase}:`, e, data);
    feedback = {};
    feedbackKeys = [];
  }

  const handleEditChange = (field, value) => {
    setEdits(prev => ({
      ...prev,
      [field]: value,
    }));
    if (onEditChange) {
      onEditChange(vendor, cardPhase, field, value);
    }
  };

  const referenceForDirty =
    approved && approvedEditsBaseline != null ? approvedEditsBaseline : cardPhaseData;
  const thisPhaseDirty = phaseObj
    ? computeEditsDifferFromReference(cardPhaseEdits, referenceForDirty)
    : false;

  const isDone = allPhasesDone;

  const feedbackOverrides = feedbackData ? (edits?.feedback_overrides || {}) : {};
  const preferredFeedbackTab = useMemo(
    () => firstFeedbackKeyWithItems(feedbackKeys, feedback, feedbackOverrides),
    [feedbackKeys, feedback, feedbackOverrides],
  );
  const activeFeedbackKey =
    selectedFeedbackTab ?? preferredFeedbackTab ?? feedbackKeys[0] ?? null;

  React.useEffect(() => {
    if (cardPhase !== "draft" || !draftFeedbackRegistryRef) return undefined;
    const fn = () => ({
      feedback,
      feedback_overrides: edits?.feedback_overrides || {},
      feedbackKeys,
    });
    draftFeedbackRegistryRef.current[vendor] = fn;
    return () => {
      delete draftFeedbackRegistryRef.current[vendor];
    };
  }, [cardPhase, vendor, feedback, feedbackKeys, edits?.feedback_overrides, draftFeedbackRegistryRef]);

  const handleSaveFeedbackOverride = (key, val) => {
    const currentOverrides = edits?.feedback_overrides || {};
    const updatedOverrides = { ...currentOverrides, [key]: val };
    handleEditChange("feedback_overrides", updatedOverrides);
    if (onSaveFeedbackOverride) {
      onSaveFeedbackOverride(key, val);
    }
    if (feedbackKeys.length > 0 && feedbackData) {
      void (async () => {
        try {
          const result = await fetchWithHeartbeat("/api/phase-feedback/snapshot/", {
            method: "POST",
            body: JSON.stringify({
              session_id: sessionId,
              document_id: documentId || null,
              vendor,
              feedback,
              feedback_overrides: updatedOverrides,
            }),
          });
          if (result.isHeartbeat) return;
          if (!result.data || result.data.status !== "ok") {
            console.warn("phase feedback snapshot unexpected:", result);
          }
        } catch (e) {
          console.warn("phase feedback snapshot error", e);
        }
      })();
    }
  };

  useEffect(() => {
    if (!inputClusterText || !Object.keys(inputClusterText).length) return;
    if (cardPhase !== "draft" && cardPhase !== "refine") return;
    if (!data?.feedback || !feedbackKeys?.length) return;
    const baseFeedback = data.feedback;
    setEdits((prev) => {
      const overrides = prev.feedback_overrides || {};
      const nextOverrides = { ...overrides };
      let any = false;
      for (const key of feedbackKeys) {
        const merged = mergeCategoryItems(baseFeedback, nextOverrides, key);
        const newItems = merged.map((item) => {
          const ck = item.input_cluster_key;
          if (!ck || String(item.status || "").toUpperCase() !== "INPUT_NEEDED") return item;
          const v = inputClusterText[ck];
          if (v == null || String(v).trim() === "") return item;
          const current = String(item.user_context || "").trim();
          if (current) return item;
          return { ...item, user_context: v };
        });
        if (JSON.stringify(newItems) !== JSON.stringify(merged)) {
          nextOverrides[key] = newItems;
          any = true;
        }
      }
      if (!any) return prev;
      const next = { ...prev, feedback_overrides: nextOverrides };
      if (onEditChange) onEditChange(vendor, cardPhase, "feedback_overrides", nextOverrides);
      return next;
    });
  }, [inputClusterText, cardPhase, data, feedbackKeys, onEditChange, vendor]);

  React.useEffect(() => {
    if (cardPhase !== "draft" && cardPhase !== "refine") return;
    const base = data?.feedback;
    if (!base || !feedbackKeys?.length) return;
    const overrides = edits?.feedback_overrides || {};
    const byCluster = new Map();
    for (const k of feedbackKeys) {
      for (const it of mergeCategoryItems(base, overrides, k)) {
        if (it.type !== FEEDBACK_TYPES.PLEASE_FIX) continue;
        const ck = it.input_cluster_key;
        if (!ck || String(it.status || "").toUpperCase() !== "INPUT_NEEDED") continue;
        if (!byCluster.has(ck)) byCluster.set(ck, []);
        byCluster.get(ck).push({
          id: it.id,
          filled: String(it.user_context || "").trim().length > 0,
          declined: it.input_declined === true,
        });
      }
    }
    setFeedbackItemApprovals((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const rows of byCluster.values()) {
        const anyReady = rows.some((r) => r.filled || r.declined);
        if (!anyReady) continue;
        for (const r of rows) {
          if (next[r.id] !== true) {
            next[r.id] = true;
            changed = true;
          }
        }
      }
      return changed ? next : prev;
    });
  }, [cardPhase, data, feedbackKeys, edits?.feedback_overrides]);

  useEffect(() => {
    if (isDone && !collapsed) {
      setCollapsed(true);
    }
  }, [isDone, collapsed]);

  const hasPhaseData = cardPhase && data !== null && Object.keys(data).length > 0;
  const isLoadingWithoutData = status === "loading" && !hasPhaseData && !approved;

  const readyForApproval = React.useMemo(() => {
    if (!cardPhase || !phaseModule?.computeReadyForApproval) {
      if (isLoading) return false;
      if (approved && !thisPhaseDirty) return false;
      return true;
    }
    return phaseModule.computeReadyForApproval({
      isLoading,
      approved,
      thisPhaseDirty,
      previousPhaseApproved,
      feedbackKeys,
      feedbackItemApprovals,
      feedbackOverrides,
      feedback,
      cardPhaseEdits,
      cardPhaseData,
    });
  }, [isLoading, approved, thisPhaseDirty, cardPhase, previousPhaseApproved, feedbackKeys, feedbackItemApprovals, feedbackOverrides, feedback, phaseModule, cardPhaseEdits, cardPhaseData]);

  const executePrimaryApprove = useCallback(async () => {
    if (approved && !thisPhaseDirty) return;
    if (!readyForApproval) return;
    if (onClearPhaseFetchError && cardPhase) {
      onClearPhaseFetchError(cardPhase, vendor);
    }
    setError(null);
    if (hasPhaseData && thisPhaseDirty) {
      setStatus("loading");
      setData(null);
      if (onStatusChange) onStatusChange(CardStatus.PENDING);
    }
    try {
      if (onApprove) {
        const snapshotAtApprove = deepCloneJson(cardPhaseEdits);
        setApproved(true);
        setApprovedEditsBaseline(snapshotAtApprove);
        if (onPhaseComplete) {
          onPhaseComplete(vendor, cardPhase, null);
        }
        if (onAfterApproveInExpanded) {
          onAfterApproveInExpanded();
        }
        const nextPhaseData = await onApprove(cardPhase, vendor, cardPhaseEdits);
        if (nextPhaseData === null) {
          console.log(`Phase ${cardPhase} for ${vendor} still processing (heartbeat)`);
          return;
        }
        if (onPhaseComplete && nextPhaseData) {
          onPhaseComplete(vendor, cardPhase, nextPhaseData);
        }
      }
    } catch (e) {
      setError(e.message || String(e));
      setApproved(false);
      setApprovedEditsBaseline(null);
      if (phaseObj?.approvedVendors) {
        phaseObj.approvedVendors.delete(vendor);
      }
    }
  }, [
    approved,
    thisPhaseDirty,
    readyForApproval,
    hasPhaseData,
    onClearPhaseFetchError,
    cardPhase,
    vendor,
    setError,
    setStatus,
    setData,
    onStatusChange,
    onApprove,
    cardPhaseEdits,
    onPhaseComplete,
    onAfterApproveInExpanded,
    phaseObj,
  ]);

  const planApproveRunnerRef = useRef(executePrimaryApprove);
  planApproveRunnerRef.current = executePrimaryApprove;
  useEffect(() => {
    if (cardPhase !== "plan" || !phaseObj?.planApproveRunners) return undefined;
    const wrapped = () => planApproveRunnerRef.current();
    phaseObj.planApproveRunners.set(vendor, wrapped);
    return () => {
      phaseObj.planApproveRunners.delete(vendor);
    };
  }, [cardPhase, vendor, phaseObj, executePrimaryApprove]);

  const hasAnyTranslation = useCallback((code) => {
    if (cardPhase === "draft") {
      const itemFieldHas = feedbackKeys.some((k) => {
        const items = mergeCategoryItems(feedback, feedbackOverrides, k);
        return items.some((it) => translation.hasTranslation(`feedback_${k}_${it.id}`));
      });
      return translation.hasTranslation("draft_letter") || itemFieldHas;
    }
    return false;
  }, [cardPhase, translation, feedbackKeys, feedback, feedbackOverrides]);

  const handleLanguageChange = useCallback(async (code) => {
    translation.setViewLanguage(code);

    if (code === "source") {
      return;
    }

    if (cardPhase === "draft") {
      const translationPromises = [];

      const draftText = cardPhaseEdits.draft_letter ?? cardPhaseData.draft_letter ?? "";
      if (draftText) {
        translationPromises.push(
          translation.translateField("draft_letter", draftText, code)
        );
      }

      for (const key of feedbackKeys) {
        const items = mergeCategoryItems(feedback, feedbackOverrides, key);
        for (const it of items) {
          if (it.observation) {
            const fid = `feedback_${key}_${it.id}`;
            translationPromises.push(translation.translateField(fid, it.observation, code));
          }
        }
      }

      await Promise.all(translationPromises);
    }
  }, [cardPhase, cardPhaseData, cardPhaseEdits, translation, feedbackKeys, feedbackOverrides, feedback]);

  const effectiveCardStyle = useOverlayWidth
    ? {
        ...cardStyle,
        width: "100%",
        minWidth: 0,
        maxWidth: "none",
        flex: "1 1 auto",
        minHeight: 0,
        maxHeight: "none",
        height: "100%",
      }
    : cardStyle;

  const approveButtonLabel = isLoading
    ? "Processing..."
    : approved
      ? thisPhaseDirty
        ? "Save and restart from here"
        : "Approved"
      : readyForApproval
        ? "Approve"
        : cardPhase === "plan" ||
            cardPhase === "draft" ||
            (cardPhase === "refine" && previousPhaseApproved)
          ? "Check feedback"
          : "Approve";

  return (
    <div style={{ ...effectiveCardStyle, opacity: disabled ? 0.6 : 1, pointerEvents: disabled ? "none" : "auto" }}>
      <div style={cardHeaderStyle} data-vendor-column-header>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "nowrap" }}>
          <h4 style={{ margin: 0, flex: "1 1 auto", textTransform: "capitalize", fontSize: 14, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {vendor}
          </h4>
          {onExpand && !isExpanded && (
            <button
              type="button"
              onClick={onExpand}
              title="Expand to 80% width"
              aria-label="Expand column"
              style={iconButtonStyle}
            >
              <ExpandOutIcon />
            </button>
          )}
          {isExpanded && onCloseExpand && (
            <button
              type="button"
              onClick={onCloseExpand}
              title="Close expanded view"
              aria-label="Close expanded view"
              style={{ ...iconButtonStyle, fontSize: 16, lineHeight: 1 }}
            >
              ×
            </button>
          )}
          {isDone && (
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              style={{ fontSize: 11, padding: "2px 6px" }}
            >
              {collapsed ? "Show" : "Hide"}
            </button>
          )}
          {!isLoadingWithoutData && cardPhase && phaseModule && (
            <button
              type="button"
              onClick={() => {
                void executePrimaryApprove();
              }}
              disabled={!readyForApproval || (approved && !thisPhaseDirty)}
              style={{
                fontSize: 12,
                padding: "4px 10px",
                flexShrink: 0,
                opacity: readyForApproval ? 1 : 0.6,
                cursor: readyForApproval ? "pointer" : "not-allowed",
              }}
            >
              {approveButtonLabel}
            </button>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          {(phaseCost > 0 || runningTotal > 0) && (
            <div style={{ fontSize: "11px", color: "var(--secondary-text-color)", whiteSpace: "nowrap" }}>
              ${phaseCost.toFixed(4)} <span style={{ fontSize: "10px", opacity: 0.8 }}>(Total: ${runningTotal.toFixed(4)})</span>
            </div>
          )}
          {cardPhase !== "draft" && (
            <LanguageSelector
              languages={translation.languages}
              viewLanguage={translation.viewLanguage}
              onLanguageChange={handleLanguageChange}
              hasTranslation={hasAnyTranslation}
              disabled={isLoading}
              isTranslating={translation.isAnyTranslating}
              size="small"
            />
          )}
        </div>
        {Object.keys(translation.translationErrors).length > 0 && (
          <div style={{ color: "var(--error-text)", fontSize: "12px" }}>
            {Object.values(translation.translationErrors)[0]}
          </div>
        )}
        {cardPhase && phaseModule?.renderAdditionalButtons && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {phaseModule.renderAdditionalButtons({
              isDone,
              cardPhase,
              collapsed,
              vendor,
            })}
          </div>
        )}
      </div>

      {isLoadingWithoutData && (
        <div style={{ padding: 6, color: "#6b7280", fontSize: 12 }}>
          Loading...
        </div>
      )}

      {error && !isLoadingWithoutData && (
        <div style={{
          color: "var(--error-text)",
          marginBottom: 8,
          fontSize: 13,
          padding: 8,
          background: "var(--error-bg)",
          border: "1px solid var(--error-border)",
          borderRadius: 4
        }}>
          {error}
        </div>
      )}

      {error && !hasPhaseData && onRetryPhaseFetch && (
        <div style={{ marginBottom: 10 }}>
          <button
            type="button"
            onClick={() => {
              void onRetryPhaseFetch(cardPhase, vendor);
            }}
            style={{
              fontSize: 13,
              padding: "6px 12px",
              background: "var(--button-bg)",
              color: "var(--text-color)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {!isLoadingWithoutData && (
      <div style={contentContainerStyle}>
        {cardPhase && phaseModule?.renderContent && (
          phaseModule.renderContent({
            EditableField,
            EditableFeedback,
            cardPhaseEdits,
            cardPhaseData,
            handleEditChange,
            isLoading,
            previousPhaseApproved,
            approved,
            phaseObj,
            cardPhase,
            vendor,
            feedback,
            feedbackKeys,
            feedbackOverrides,
            activeFeedbackKey,
            feedbackItemApprovals,
            setSelectedFeedbackTab,
            setFeedbackItemApprovals,
            handleSaveFeedbackOverride,
            translation,
            inputClusterText,
            broadcastInputCluster,
          })
        )}
      </div>
      )}
    </div>
  );
}
