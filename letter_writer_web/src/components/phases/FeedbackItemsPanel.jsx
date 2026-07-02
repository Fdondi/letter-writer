import React, { useCallback, useMemo, useState } from "react";
import LanguageSelector from "../LanguageSelector";
import { fetchWithHeartbeat } from "../../utils/apiHelpers";
import { showNotification } from "../../utils/apiNotifications";
import {
  CONTEXT_SOURCES,
  CONTEXT_SOURCE_LABELS,
  CONTEXT_USER_SOURCE,
  FEEDBACK_TYPES,
  mergeCategoryItems,
  filteredFeedbackDetailsFromRaw,
  newId,
  selectNextTabIfCategoryDone,
} from "./feedbackItemUtils";

function LanguageSelectorTiny({ fieldId, observation, translation, disabled }) {
  const fieldViewLanguage = translation.getFieldViewLanguage(fieldId);
  const handleFieldLanguageChange = async (code) => {
    translation.setFieldViewLanguage(fieldId, code);
    if (code === "source" || !observation) return;
    await translation.translateField(fieldId, observation, code);
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

export function FeedbackItemsPanel({
  categoryKey,
  items,
  feedbackItemApprovals,
  setFeedbackItemApprovals,
  handleSaveFeedbackOverride,
  feedbackKeys,
  feedback,
  feedbackOverrides,
  activeFeedbackKey,
  setSelectedFeedbackTab,
  disabled,
  translation,
  duplicateLinkFlat = [],
  inputClusterText = {},
  onInputClusterBroadcast = undefined,
  vendor = undefined,
}) {
  const [editingId, setEditingId] = useState(null);
  /** Set while POST /feedback/request-context/ is in flight for one item id. */
  const [requestContextLoadingId, setRequestContextLoadingId] = useState(null);
  const [draftObservation, setDraftObservation] = useState("");
  /** When editing a positive note, true after "Turn into critique" — save as PLEASE_FIX. */
  const [editingPromoteToFix, setEditingPromoteToFix] = useState(false);
  /** Inline edit for user_context (same UX as machine context lines). */
  const [editingUserContextId, setEditingUserContextId] = useState(null);
  const [draftUserContext, setDraftUserContext] = useState("");
  /** INPUT_NEEDED: unsaved text in the capture box (committed only via Save). */
  const [inputNeededDraftById, setInputNeededDraftById] = useState({});
  /** Inline edit for one machine context line: { itemId, index }. */
  const [editingContextRow, setEditingContextRow] = useState(null);
  const [draftContextLine, setDraftContextLine] = useState("");

  /** Same duplicate_group_id (phase 3) or input_cluster_key (phase 4) → one approval applies to all. */
  const linkedApprovalIds = useCallback(
    (item) => {
      const ids = new Set([item.id]);
      const dg = item.duplicate_group_id;
      const ick = item.input_cluster_key;
      for (const row of duplicateLinkFlat) {
        if (dg && row.duplicate_group_id === dg) ids.add(row.id);
        if (ick && row.input_cluster_key === ick) ids.add(row.id);
      }
      return [...ids];
    },
    [duplicateLinkFlat],
  );

  const fixItems = useMemo(() => {
    const raw = items.filter((it) => it.type === FEEDBACK_TYPES.PLEASE_FIX);
    return [...raw].sort((a, b) => {
      const ap = feedbackItemApprovals[a.id] === true;
      const bp = feedbackItemApprovals[b.id] === true;
      if (ap !== bp) return ap ? 1 : -1;
      return 0;
    });
  }, [items, feedbackItemApprovals]);
  const goodItems = useMemo(
    () => items.filter((it) => it.type === FEEDBACK_TYPES.ALREADY_GOOD),
    [items],
  );

  const filteredFeedbackDetails = useMemo(() => {
    const raw = feedbackOverrides[categoryKey] !== undefined ? feedbackOverrides[categoryKey] : feedback[categoryKey];
    return filteredFeedbackDetailsFromRaw(raw);
  }, [feedback, feedbackOverrides, categoryKey]);

  const persistItems = (nextItems) => {
    handleSaveFeedbackOverride(categoryKey, nextItems);
  };

  const onAdd = () => {
    const id = newId();
    const next = [...items, { id, observation: "", type: FEEDBACK_TYPES.PLEASE_FIX }];
    persistItems(next);
    setFeedbackItemApprovals((prev) => ({ ...prev, [id]: false }));
    setEditingId(id);
    setDraftObservation("");
    setEditingPromoteToFix(false);
  };

  const onRemove = (id) => {
    const nextItems = items.filter((it) => it.id !== id);
    persistItems(nextItems);
    const nextApr = { ...feedbackItemApprovals };
    delete nextApr[id];
    setFeedbackItemApprovals(nextApr);
    const nextTab = selectNextTabIfCategoryDone(
      activeFeedbackKey,
      feedbackKeys,
      feedback,
      feedbackOverrides,
      categoryKey,
      nextItems,
      nextApr,
    );
    if (nextTab) setSelectedFeedbackTab(nextTab);
    if (editingId === id) {
      setEditingId(null);
      setDraftObservation("");
      setEditingPromoteToFix(false);
    }
    if (editingUserContextId === id) {
      setEditingUserContextId(null);
      setDraftUserContext("");
    }
    if (editingContextRow?.itemId === id) {
      setEditingContextRow(null);
      setDraftContextLine("");
    }
    setInputNeededDraftById((prev) => {
      if (!(id in prev)) return prev;
      const n = { ...prev };
      delete n[id];
      return n;
    });
  };

  const onApprovePleaseFix = (id) => {
    const it = items.find((x) => x.id === id);
    if (!it) return;
    {
      const status = String(it.status || "NOT_NEEDED").toUpperCase();
      if (status === "INPUT_NEEDED") {
        const filled = String(it.user_context || "").trim().length > 0;
        const declined = it.input_declined === true;
        if (!filled && !declined) return;
      }
    }
    const idsToApprove = linkedApprovalIds(it);
    const nextApr = { ...feedbackItemApprovals };
    idsToApprove.forEach((i) => {
      nextApr[i] = true;
    });
    setFeedbackItemApprovals(nextApr);
    const nextTab = selectNextTabIfCategoryDone(
      activeFeedbackKey,
      feedbackKeys,
      feedback,
      feedbackOverrides,
      categoryKey,
      items,
      nextApr,
    );
    if (nextTab) setSelectedFeedbackTab(nextTab);
  };

  const startEdit = (it) => {
    setEditingId(it.id);
    setDraftObservation(it.observation || "");
    setEditingPromoteToFix(false);
    setEditingContextRow(null);
    setDraftContextLine("");
    setEditingUserContextId(null);
    setDraftUserContext("");
  };

  const saveEdit = () => {
    if (!editingId) return;
    const it = items.find((i) => i.id === editingId);
    if (!it) return;
    const obs = (draftObservation || "").trim();
    const baseRow = mergeCategoryItems(feedback, {}, categoryKey).find((x) => x.id === editingId);
    const origObs = String(baseRow?.observation || "").trim();
    const obsChanged = origObs !== obs;

    if (it.type === FEEDBACK_TYPES.PLEASE_FIX) {
      if (!obs) {
        // If they cleared the text entirely (or clicked save on an empty new critique), remove it
        onRemove(editingId);
        return;
      }
      const next = items.map((x) => {
        if (x.id !== editingId) return x;
        let row = { ...x, observation: obs, type: FEEDBACK_TYPES.PLEASE_FIX };
        if (obsChanged && row.duplicate_group_id) {
          const { duplicate_group_id: _d, ...rest } = row;
          row = rest;
        }
        return row;
      });
      persistItems(next);
      const nextApr = { ...feedbackItemApprovals, [editingId]: true };
      setFeedbackItemApprovals(nextApr);
      const nextTab = selectNextTabIfCategoryDone(
        activeFeedbackKey,
        feedbackKeys,
        feedback,
        feedbackOverrides,
        categoryKey,
        next,
        nextApr,
      );
      if (nextTab) setSelectedFeedbackTab(nextTab);
    } else {
      if (!obs) return;
      if (editingPromoteToFix) {
        const next = items.map((x) => {
          if (x.id !== editingId) return x;
          let row = { ...x, observation: obs, type: FEEDBACK_TYPES.PLEASE_FIX };
          if (obsChanged && row.duplicate_group_id) {
            const { duplicate_group_id: _d, ...rest } = row;
            row = rest;
          }
          return row;
        });
        persistItems(next);
        setFeedbackItemApprovals((prev) => ({ ...prev, [editingId]: false }));
      } else {
        const next = items.map((x) => {
          if (x.id !== editingId) return x;
          let row = { ...x, observation: obs, type: FEEDBACK_TYPES.ALREADY_GOOD };
          if (obsChanged && row.duplicate_group_id) {
            const { duplicate_group_id: _d, ...rest } = row;
            row = rest;
          }
          return row;
        });
        persistItems(next);
      }
    }
    setEditingId(null);
    setDraftObservation("");
    setEditingPromoteToFix(false);
    setEditingContextRow(null);
    setDraftContextLine("");
    setEditingUserContextId(null);
    setDraftUserContext("");
  };

  const cancelEdit = () => {
    const closedId = editingId;
    
    // If we were adding a brand new critique and cancelled before saving any text, remove it
    const it = items.find((i) => i.id === closedId);
    if (it && it.type === FEEDBACK_TYPES.PLEASE_FIX && !String(it.observation || "").trim()) {
      onRemove(closedId);
      return;
    }

    setEditingId(null);
    setDraftObservation("");
    setEditingPromoteToFix(false);
    setEditingContextRow(null);
    setDraftContextLine("");
    setEditingUserContextId(null);
    setDraftUserContext("");
    if (closedId) {
      setInputNeededDraftById((prev) => {
        if (!(closedId in prev)) return prev;
        const n = { ...prev };
        delete n[closedId];
        return n;
      });
    }
  };

  const renderFixRow = (it) => {
    const approved = feedbackItemApprovals[it.id] === true;
    const isEditing = editingId === it.id;
    const fieldId = `feedback_${categoryKey}_${it.id}`;
    const status = String(it.status || "NOT_NEEDED").toUpperCase();
    const needsInput = status === "INPUT_NEEDED";
    const contextItems = Array.isArray(it?.context_field?.items) ? it.context_field.items : [];
    const userContext = String(it.user_context || "");
    const userInstructions = String(it.user_instructions || "");
    const userContextFilled = userContext.trim().length > 0;
    const inputDeclined = it.input_declined === true;
    const persistUserContextToCv = it.persist_user_context_to_cv !== false;
    const persistUserContextForAgents =
      it.persist_user_context_for_agents !== undefined
        ? it.persist_user_context_for_agents !== false
        : persistUserContextToCv;
    const persistScope =
      persistUserContextToCv && persistUserContextForAgents
        ? "both"
        : !persistUserContextToCv && persistUserContextForAgents
          ? "agent"
          : "none";
    /** Initial capture only; after Save, user text lives in user_context and is edited like other context lines. */
    const showInputEditor = needsInput && !userContextFilled && !inputDeclined;
    const clusterPre = it.input_cluster_key && inputClusterText[it.input_cluster_key];
    const inputDraftEffective =
      inputNeededDraftById[it.id] ??
      (clusterPre && !userContextFilled ? clusterPre : "");
    const userContextPlaceholder =
      userInstructions.trim() ||
      "Paste the missing facts/context here (or delete the item).";
    const displayedObservation =
      translation && fieldId
        ? translation.getTranslatedText(fieldId, it.observation || "")
        : it.observation || "";

    const setUserContext = (next, patch = {}) => {
      const text = String(next ?? "");
      const nextItems = items.map((x) =>
        x.id === it.id ? { ...x, user_context: text, ...patch } : x,
      );
      persistItems(nextItems);
      if (onInputClusterBroadcast && it.input_cluster_key && text.trim()) {
        onInputClusterBroadcast(it.input_cluster_key, text);
      }
    };

    const setPersistScope = (scope) => {
      const cv = scope === "both";
      const agent = scope === "both" || scope === "agent";
      const nextItems = items.map((x) =>
        x.id === it.id
          ? { ...x, persist_user_context_to_cv: cv, persist_user_context_for_agents: agent }
          : x,
      );
      persistItems(nextItems);
    };

    const commitInputNeededDraft = () => {
      const raw = String(inputDraftEffective ?? "");
      if (!raw.trim()) return;
      const nextItems = items.map((x) =>
        x.id === it.id
          ? {
              ...x,
              user_context: raw,
              input_declined: false,
              persist_user_context_to_cv: persistUserContextToCv,
              persist_user_context_for_agents: persistUserContextForAgents,
            }
          : x,
      );
      persistItems(nextItems);
      if (onInputClusterBroadcast && it.input_cluster_key) {
        onInputClusterBroadcast(it.input_cluster_key, raw);
      }
      // Providing required info should approve this and all linked items (same input cluster).
      setFeedbackItemApprovals((prev) => {
        const nextApr = { ...prev };
        linkedApprovalIds(it).forEach((i) => {
          nextApr[i] = true;
        });
        const nextTab = selectNextTabIfCategoryDone(
          activeFeedbackKey,
          feedbackKeys,
          feedback,
          feedbackOverrides,
          categoryKey,
          nextItems,
          nextApr,
        );
        if (nextTab) setSelectedFeedbackTab(nextTab);
        return nextApr;
      });
      setInputNeededDraftById((prev) => {
        if (!(it.id in prev)) return prev;
        const n = { ...prev };
        delete n[it.id];
        return n;
      });
    };

    const approveWithoutInput = () => {
      const nextItems = items.map((x) =>
        x.id === it.id ? { ...x, input_declined: true } : x,
      );
      persistItems(nextItems);
      const nextApr = { ...feedbackItemApprovals };
      linkedApprovalIds(it).forEach((i) => {
        nextApr[i] = true;
      });
      setFeedbackItemApprovals(nextApr);
      const nextTab = selectNextTabIfCategoryDone(
        activeFeedbackKey,
        feedbackKeys,
        feedback,
        feedbackOverrides,
        categoryKey,
        nextItems,
        nextApr,
      );
      if (nextTab) setSelectedFeedbackTab(nextTab);
    };

    const renderPersistRadios = () => (
      <div style={{ marginTop: 8, fontSize: 12, color: "#374151" }}>
        <div style={{ marginBottom: 4, fontWeight: 600 }}>Save your reply</div>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer", marginBottom: 4 }}>
          <input
            type="radio"
            name={`persist-${it.id}`}
            checked={persistScope === "both"}
            onChange={() => setPersistScope("both")}
            disabled={disabled}
          />
          CV appendix and model context — reuse in future checks
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer", marginBottom: 4 }}>
          <input
            type="radio"
            name={`persist-${it.id}`}
            checked={persistScope === "agent"}
            onChange={() => setPersistScope("agent")}
            disabled={disabled}
          />
          Model context only (not CV appendix) — if this is already in your CV
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer" }}>
          <input
            type="radio"
            name={`persist-${it.id}`}
            checked={persistScope === "none"}
            onChange={() => setPersistScope("none")}
            disabled={disabled}
          />
          No — only use for this revision
        </label>
      </div>
    );

    const setContextItems = (nextContextItems) => {
      const arr = Array.isArray(nextContextItems) ? nextContextItems : [];
      const hasRows = arr.length > 0;
      const nonEmpty = arr.some((x) => String(x?.text ?? x ?? "").trim().length > 0);
      const nextStatus =
        status === "INPUT_NEEDED"
          ? "INPUT_NEEDED"
          : hasRows || nonEmpty
            ? "SUFFICIENT"
            : "NOT_NEEDED";

      const nextItems = items.map((x) => {
        if (x.id !== it.id) return x;
        return {
          ...x,
          status: nextStatus,
          context_field: { ...(x.context_field || {}), items: arr },
        };
      });
      persistItems(nextItems);
    };

    const requestMoreMachineContext = async () => {
      if (!vendor) return;
      const obs = String(it.observation || "").trim();
      if (!obs) return;
      setRequestContextLoadingId(it.id);
      try {
        const { data, isHeartbeat } = await fetchWithHeartbeat(
          `/api/phases/feedback/request-context/${encodeURIComponent(vendor)}/`,
          { method: "POST", body: JSON.stringify({ category: categoryKey, item_id: it.id }) },
        );
        if (isHeartbeat) {
          showNotification("Request still processing; try again in a moment.");
          return;
        }
        const incoming = Array.isArray(data?.items) ? data.items : [];
        const seen = new Set(
          contextItems
            .map((r) => {
              const t = String(r?.text ?? r ?? "").trim().toLowerCase();
              return t;
            })
            .filter(Boolean),
        );
        const appended = [];
        for (const row of incoming) {
          const text = String(row?.text ?? "").trim();
          if (!text) continue;
          const low = text.toLowerCase();
          if (seen.has(low)) continue;
          seen.add(low);
          let src = String(row?.source ?? "CV").trim().toUpperCase();
          if (!CONTEXT_SOURCES.includes(src)) src = "CV";
          appended.push({ text, source: src });
        }
        if (appended.length === 0) {
          showNotification("No additional context lines found in the same materials.");
          return;
        }
        const nextRows = [...contextItems, ...appended];
        const hasRows = nextRows.some((x) => String(x?.text ?? x ?? "").trim().length > 0);
        const nonEmpty = nextRows.some((x) => String(x?.text ?? x ?? "").trim().length > 0);
        const nextStatus =
          status === "INPUT_NEEDED"
            ? "INPUT_NEEDED"
            : hasRows || nonEmpty
              ? "SUFFICIENT"
              : "NOT_NEEDED";
        const nextItems = items.map((x) =>
          x.id === it.id
            ? {
                ...x,
                status: nextStatus,
                context_field: { ...(x.context_field || {}), items: nextRows },
              }
            : x,
        );
        persistItems(nextItems);
        showNotification(`Added ${appended.length} context line(s).`);
      } catch (e) {
        showNotification(e?.message || String(e));
      } finally {
        setRequestContextLoadingId(null);
      }
    };

    const updateContextItem = (idx, patch) => {
      const next = [...(contextItems || [])];
      const prev = next[idx];
      const base =
        prev && typeof prev === "object" && !Array.isArray(prev)
          ? { ...prev }
          : { text: String(prev ?? ""), source: "CV" };
      const merged = { ...base, ...(patch || {}) };
      merged.text = String(merged.text ?? "");
      const us = String(merged.source ?? "").toUpperCase();
      if (us === CONTEXT_USER_SOURCE) {
        merged.source = CONTEXT_USER_SOURCE;
        if (patch && "persist_to_cv" in patch) {
          merged.persist_to_cv = patch.persist_to_cv !== false;
        } else if (merged.persist_to_cv === undefined) {
          merged.persist_to_cv = true;
        } else {
          merged.persist_to_cv = merged.persist_to_cv !== false;
        }
        if (patch && "persist_for_agents" in patch) {
          merged.persist_for_agents = patch.persist_for_agents !== false;
        } else if (merged.persist_for_agents === undefined) {
          merged.persist_for_agents = merged.persist_to_cv !== false;
        } else {
          merged.persist_for_agents = merged.persist_for_agents !== false;
        }
      } else {
        merged.source = CONTEXT_SOURCES.includes(us) ? us : "CV";
        delete merged.persist_to_cv;
        delete merged.persist_for_agents;
      }
      next[idx] = merged;
      setContextItems(next);
    };

    const renderPersistUserLineRadios = (idx) => {
      const row = contextItems[idx];
      const persistLineToCv = row && typeof row === "object" && row.persist_to_cv !== false;
      const persistLineForAgents =
        row && typeof row === "object" && row.persist_for_agents !== undefined
          ? row.persist_for_agents !== false
          : persistLineToCv;
      const persistLineScope =
        persistLineToCv && persistLineForAgents
          ? "both"
          : !persistLineToCv && persistLineForAgents
            ? "agent"
            : "none";
      const setLinePersistScope = (scope) => {
        const cv = scope === "both";
        const agent = scope === "both" || scope === "agent";
        updateContextItem(idx, { persist_to_cv: cv, persist_for_agents: agent });
      };
      return (
        <div style={{ marginTop: 8, fontSize: 12, color: "#374151" }}>
          <div style={{ marginBottom: 4, fontWeight: 600 }}>Save your reply</div>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer", marginBottom: 4 }}>
            <input
              type="radio"
              name={`persist-user-line-${it.id}-${idx}`}
              checked={persistLineScope === "both"}
              onChange={() => setLinePersistScope("both")}
              disabled={disabled}
            />
            CV appendix and model context — reuse in future checks
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer", marginBottom: 4 }}>
            <input
              type="radio"
              name={`persist-user-line-${it.id}-${idx}`}
              checked={persistLineScope === "agent"}
              onChange={() => setLinePersistScope("agent")}
              disabled={disabled}
            />
            Model context only (not CV appendix) — if this is already in your CV
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: disabled ? "not-allowed" : "pointer" }}>
            <input
              type="radio"
              name={`persist-user-line-${it.id}-${idx}`}
              checked={persistLineScope === "none"}
              onChange={() => setLinePersistScope("none")}
              disabled={disabled}
            />
            No — only use for this revision
          </label>
        </div>
      );
    };

    const removeContextItem = (idx) => {
      const next = (contextItems || []).filter((_, i) => i !== idx);
      setContextItems(next);
      if (editingContextRow?.itemId === it.id) {
        setEditingContextRow(null);
        setDraftContextLine("");
      }
    };

    const addContextItem = (e) => {
      if (e && typeof e.preventDefault === "function") e.preventDefault();
      if (e && typeof e.stopPropagation === "function") e.stopPropagation();
      setEditingUserContextId(null);
      setDraftUserContext("");
      const next = [
        ...(contextItems || []),
        { text: "", source: CONTEXT_USER_SOURCE, persist_to_cv: true, persist_for_agents: true },
      ];
      setContextItems(next);
      const newIdx = next.length - 1;
      setEditingContextRow({ itemId: it.id, index: newIdx });
      setDraftContextLine("");
    };

    const saveContextRowInline = () => {
      if (!editingContextRow || editingContextRow.itemId !== it.id) return;
      updateContextItem(editingContextRow.index, { text: draftContextLine });
      setEditingContextRow(null);
      setDraftContextLine("");
    };

    const cancelContextRowInline = () => {
      if (!editingContextRow || editingContextRow.itemId !== it.id) return;
      const idx = editingContextRow.index;
      const line = String((contextItems[idx] && typeof contextItems[idx] === "object") ? contextItems[idx].text : (contextItems[idx] ?? ""));
      if (!line.trim() && contextItems.length > 0) {
        removeContextItem(idx);
        return;
      }
      setEditingContextRow(null);
      setDraftContextLine("");
    };

    const startEditContextRow = (idx) => {
      setEditingUserContextId(null);
      setDraftUserContext("");
      setEditingContextRow({ itemId: it.id, index: idx });
      const prev = contextItems[idx];
      setDraftContextLine(
        String(prev && typeof prev === "object" && !Array.isArray(prev) ? prev.text : (prev ?? "")),
      );
    };

    const startEditUserContextRow = () => {
      setEditingContextRow(null);
      setDraftContextLine("");
      setEditingUserContextId(it.id);
      setDraftUserContext(userContext);
    };

    const saveUserContextRowInline = () => {
      if (editingUserContextId !== it.id) return;
      setUserContext(draftUserContext, { input_declined: false });
      if (String(draftUserContext || "").trim()) {
        setFeedbackItemApprovals((prev) => {
          const next = { ...prev };
          linkedApprovalIds(it).forEach((i) => {
            next[i] = true;
          });
          return next;
        });
      } else {
        setFeedbackItemApprovals((prev) => {
          const next = { ...prev };
          linkedApprovalIds(it).forEach((i) => {
            next[i] = false;
          });
          return next;
        });
      }
      setEditingUserContextId(null);
      setDraftUserContext("");
    };

    const cancelUserContextRowInline = () => {
      if (editingUserContextId !== it.id) return;
      setEditingUserContextId(null);
      setDraftUserContext("");
    };

    const iconBtnStyle = {
      fontSize: 14,
      lineHeight: 1,
      padding: "2px 6px",
      border: "1px solid #d1d5db",
      background: "#fff",
      borderRadius: 4,
      cursor: disabled ? "not-allowed" : "pointer",
      color: "#374151",
    };

    const machineContextVisible = contextItems.some((x) => String(x?.text ?? x ?? "").trim().length > 0);
    const hasDisplayContext =
      machineContextVisible ||
      userContextFilled ||
      inputDeclined ||
      (editingContextRow?.itemId === it.id && !isEditing) ||
      (editingUserContextId === it.id && !isEditing);

    /** Same gate as showInputEditor: missing saved user_context and not declined — Approve stays off until input or this path. */
    const needsInputOrDeclineChoice = needsInput && !userContextFilled && !inputDeclined;
    const rowGateBlocksApprove =
      disabled ||
      approved ||
      (needsInput && !String(userContext || "").trim() && !inputDeclined);
    const renderApproveWithoutInputButton = () => (
      <button
        type="button"
        onClick={approveWithoutInput}
        disabled={disabled}
        style={{
          fontSize: 11,
          padding: "4px 10px",
          fontWeight: 600,
          color: "#1e40af",
          border: "1px solid #93c5fd",
          background: "#eff6ff",
        }}
        title="Keep this critique in the letter; the model will not receive new facts for this point"
      >
        No input needed
      </button>
    );

    const renderMachineRow = (idx) => {
      const raw = contextItems[idx];
      const text = String(raw && typeof raw === "object" && !Array.isArray(raw) ? raw.text : (raw ?? ""));
      const src = String(raw && typeof raw === "object" && !Array.isArray(raw) ? raw.source : "CV").toUpperCase();
      const normalizedSrc =
        src === CONTEXT_USER_SOURCE
          ? CONTEXT_USER_SOURCE
          : CONTEXT_SOURCES.includes(src)
            ? src
            : "CV";
      const isUserAdded = normalizedSrc === CONTEXT_USER_SOURCE;
      const isRowEditing = editingContextRow?.itemId === it.id && editingContextRow?.index === idx;
      if (!text.trim() && !isRowEditing && !isEditing) return null;

      if (isRowEditing) {
        if (isUserAdded) {
          return (
            <div key={`${it.id}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#b91c1c", marginBottom: 6 }}>
                  Your context
                </div>
                <textarea
                  style={{
                    width: "100%",
                    minHeight: 56,
                    fontSize: 13,
                    padding: 8,
                    resize: "vertical",
                    border: "1px solid #fca5a5",
                    background: "#fff",
                  }}
                  value={draftContextLine}
                  onChange={(e) => setDraftContextLine(e.target.value)}
                  disabled={disabled}
                  placeholder="Facts or notes for this critique (not labeled as CV / job material)"
                />
                {renderPersistUserLineRadios(idx)}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
                <button type="button" onClick={saveContextRowInline} disabled={disabled} style={iconBtnStyle} title="Save" aria-label="Save">
                  ✓
                </button>
                <button type="button" onClick={cancelContextRowInline} disabled={disabled} style={iconBtnStyle} title="Cancel" aria-label="Cancel">
                  ×
                </button>
              </div>
            </div>
          );
        }
        return (
          <div key={`${it.id}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>
                Source
              </div>
              <select
                value={normalizedSrc}
                onChange={(e) => updateContextItem(idx, { source: e.target.value })}
                disabled={disabled}
                style={{ fontSize: 12, padding: "4px 8px", marginBottom: 6, maxWidth: 220 }}
              >
                {CONTEXT_SOURCES.map((s) => (
                  <option key={s} value={s}>
                    {CONTEXT_SOURCE_LABELS[s] ?? s}
                  </option>
                ))}
              </select>
              <textarea
                style={{ width: "100%", minHeight: 56, fontSize: 13, padding: 8, resize: "vertical" }}
                value={draftContextLine}
                onChange={(e) => setDraftContextLine(e.target.value)}
                disabled={disabled}
                placeholder="Paste-ready fact/snippet (no instructions)"
              />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
              <button type="button" onClick={saveContextRowInline} disabled={disabled} style={iconBtnStyle} title="Save" aria-label="Save">
                ✓
              </button>
              <button type="button" onClick={cancelContextRowInline} disabled={disabled} style={iconBtnStyle} title="Cancel" aria-label="Cancel">
                ×
              </button>
            </div>
          </div>
        );
      }

      if (isUserAdded) {
        return (
          <div key={`${it.id}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#b91c1c", marginBottom: 4 }}>
                Your context
              </div>
              <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.45, color: "#111827" }}>
                {text.trim() ? text : "(empty)"}
              </div>
              {text.trim() ? renderPersistUserLineRadios(idx) : null}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
              <button
                type="button"
                onClick={() => startEditContextRow(idx)}
                disabled={disabled}
                style={iconBtnStyle}
                title="Edit"
                aria-label="Edit context line"
              >
                ✎
              </button>
              <button
                type="button"
                onClick={() => removeContextItem(idx)}
                disabled={disabled}
                style={{ ...iconBtnStyle, color: "#b91c1c", borderColor: "#fca5a5" }}
                title="Remove"
                aria-label="Remove context line"
              >
                ×
              </button>
            </div>
          </div>
        );
      }

      return (
        <div key={`${it.id}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 11, color: "#9ca3af", marginBottom: 2 }}>
              {CONTEXT_SOURCE_LABELS[normalizedSrc] ?? normalizedSrc}
            </div>
            <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.45, color: "#111827" }}>
              {text.trim() ? text : "(empty)"}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
            <button
              type="button"
              onClick={() => startEditContextRow(idx)}
              disabled={disabled}
              style={iconBtnStyle}
              title="Edit"
              aria-label="Edit context line"
            >
              ✎
            </button>
            <button
              type="button"
              onClick={() => removeContextItem(idx)}
              disabled={disabled}
              style={{ ...iconBtnStyle, color: "#b91c1c", borderColor: "#fca5a5" }}
              title="Remove"
              aria-label="Remove context line"
            >
              ×
            </button>
          </div>
        </div>
      );
    };

    const renderUserContextRow = () => {
      if (showInputEditor) return null;
      const isEditingUser = editingUserContextId === it.id;
      if (inputDeclined && !userContextFilled && !isEditingUser) {
        return (
          <div key={`${it.id}-ctx-user`} style={{ marginTop: 8, fontSize: 12, color: "#6b7280", fontStyle: "italic" }}>
            You approved this critique without adding missing facts. The model will not receive new facts for this point.
          </div>
        );
      }
      if (!userContextFilled && !isEditingUser) return null;

      if (isEditingUser) {
        return (
          <div key={`${it.id}-ctx-user`} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <textarea
                style={{ flex: 1, minHeight: 56, fontSize: 13, padding: 8, resize: "vertical", border: "1px solid #fca5a5", background: "#fff" }}
                value={draftUserContext}
                onChange={(e) => setDraftUserContext(e.target.value)}
                disabled={disabled}
                placeholder={userContextPlaceholder}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
                <button type="button" onClick={saveUserContextRowInline} disabled={disabled} style={iconBtnStyle} title="Save" aria-label="Save">
                  ✓
                </button>
                <button type="button" onClick={cancelUserContextRowInline} disabled={disabled} style={iconBtnStyle} title="Cancel" aria-label="Cancel">
                  ×
                </button>
              </div>
            </div>
            {needsInput ? renderPersistRadios() : null}
          </div>
        );
      }

      return (
        <div key={`${it.id}-ctx-user`} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0, whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.45, color: "#111827" }}>
              {userContext}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
              <button
                type="button"
                onClick={startEditUserContextRow}
                disabled={disabled}
                style={iconBtnStyle}
                title="Edit"
                aria-label="Edit context line"
              >
                ✎
              </button>
              <button
                type="button"
                onClick={() => {
                  setUserContext("", { input_declined: false });
                  // Clearing required info revokes approval.
                  setFeedbackItemApprovals((prev) => ({ ...prev, [it.id]: false }));
                  setEditingUserContextId(null);
                  setDraftUserContext("");
                  setInputNeededDraftById((prev) => {
                    if (!(it.id in prev)) return prev;
                    const n = { ...prev };
                    delete n[it.id];
                    return n;
                  });
                }}
                disabled={disabled}
                style={{ ...iconBtnStyle, color: "#b91c1c", borderColor: "#fca5a5" }}
                title="Remove"
                aria-label="Remove context line"
              >
                ×
              </button>
            </div>
          </div>
          {needsInput && userContextFilled ? renderPersistRadios() : null}
        </div>
      );
    };

    return (
      <li
        key={it.id}
        style={{
          border: approved ? "1px solid #e5e7eb" : "1px solid #fcd34d",
          borderRadius: 6,
          padding: 10,
          background: approved ? "#f3f4f6" : "#fffbeb",
          color: approved ? "#6b7280" : undefined,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: approved ? "#9ca3af" : "#92400e", textTransform: "uppercase", letterSpacing: "0.04em" }}>
            Critique
          </span>
          {it.duplicate_group_id ? (
            <span
              style={{ fontSize: 10, color: "#9ca3af" }}
              title="Linked to the same issue in another category; approve once to approve all."
            >
              Linked
            </span>
          ) : null}
          {needsInput ? (
            <span style={{ fontSize: 11, fontWeight: 700, color: "#b91c1c", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              INPUT NEEDED
            </span>
          ) : null}
          {translation && (
            <div style={{ marginLeft: "auto" }}>
              <LanguageSelectorTiny fieldId={fieldId} observation={it.observation || ""} translation={translation} disabled={disabled} />
            </div>
          )}
        </div>
        {isEditing ? (
          <>
            <textarea
              style={{ width: "100%", minHeight: 88, padding: 8, fontSize: 13 }}
              value={draftObservation}
              onChange={(e) => setDraftObservation(e.target.value)}
              disabled={disabled}
            />
            {needsInput && showInputEditor ? (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#b91c1c", marginBottom: 6 }}>
                  Provide missing context before approving
                </div>
                <textarea
                  style={{
                    width: "100%",
                    minHeight: 72,
                    padding: 8,
                    fontSize: 13,
                    border: "1px solid #fca5a5",
                    background: "#fef2f2",
                  }}
                  value={inputDraftEffective}
                  onChange={(e) =>
                    setInputNeededDraftById((prev) => ({ ...prev, [it.id]: e.target.value }))
                  }
                  disabled={disabled}
                  placeholder={userContextPlaceholder}
                />
                {renderPersistRadios()}
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <button
                    type="button"
                    onClick={commitInputNeededDraft}
                    disabled={disabled || !String(inputDraftEffective).trim()}
                    style={{ fontSize: 12, padding: "4px 12px" }}
                  >
                    Save
                  </button>
                  {renderApproveWithoutInputButton()}
                </div>
              </div>
            ) : null}
            <div style={{ marginTop: 10, fontSize: 12, color: "#374151" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={addContextItem}
                  disabled={disabled}
                  style={{ fontSize: 11, padding: "2px 8px" }}
                  title="Add your own facts or notes (same as required input — not tied to CV / job labels). Choose whether to save to your profile."
                >
                  Add context
                </button>
                {vendor ? (
                  <button
                    type="button"
                    onClick={requestMoreMachineContext}
                    disabled={
                      disabled ||
                      requestContextLoadingId === it.id ||
                      !String(it.observation || "").trim()
                    }
                    style={{ fontSize: 11, padding: "2px 8px" }}
                    title="Run the checker context again to suggest snippets the first pass may have missed"
                  >
                    {requestContextLoadingId === it.id ? "…" : "Request context"}
                  </button>
                ) : null}
                {status === "INPUT_NEEDED" ? (
                  <span style={{ fontSize: 11, color: "#b91c1c" }}>
                    Use Save, or the blue &quot;No input needed&quot; button above.
                  </span>
                ) : null}
              </div>
              {contextItems.map((_, idx) => renderMachineRow(idx))}
              {renderUserContextRow()}
            </div>
            <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <button type="button" onClick={saveEdit} disabled={disabled} style={{ fontSize: 12 }}>
                Save
              </button>
              {needsInputOrDeclineChoice ? renderApproveWithoutInputButton() : null}
              <button type="button" onClick={cancelEdit} style={{ fontSize: 12 }}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            {needsInput && showInputEditor ? (
              <div
                style={{
                  border: "1px solid #fca5a5",
                  background: "#fef2f2",
                  borderRadius: 6,
                  padding: 8,
                  marginBottom: 8,
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 800, color: "#b91c1c" }}>Input needed</div>
                <textarea
                  style={{ width: "100%", minHeight: 72, padding: 8, fontSize: 13, border: "1px solid #fca5a5", marginTop: 6 }}
                  value={inputDraftEffective}
                  onChange={(e) =>
                    setInputNeededDraftById((prev) => ({ ...prev, [it.id]: e.target.value }))
                  }
                  disabled={disabled}
                  placeholder={userContextPlaceholder}
                />
                {renderPersistRadios()}
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <button
                    type="button"
                    onClick={commitInputNeededDraft}
                    disabled={disabled || !String(inputDraftEffective).trim()}
                    style={{ fontSize: 12, padding: "4px 12px" }}
                  >
                    Save
                  </button>
                  {renderApproveWithoutInputButton()}
                </div>
              </div>
            ) : null}
            <div style={{ fontSize: 13, whiteSpace: "pre-wrap", color: "#111827" }}>{displayedObservation || "(empty)"}</div>
            {hasDisplayContext ? (
              <div style={{ marginTop: 8, fontSize: 12, color: "#374151" }}>
                {contextItems.map((_, idx) => renderMachineRow(idx))}
                {renderUserContextRow()}
              </div>
            ) : null}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
              <button
                type="button"
                onClick={() => onApprovePleaseFix(it.id)}
                disabled={
                  disabled ||
                  approved ||
                  (needsInput && !String(userContext || "").trim() && !inputDeclined)
                }
                style={{ fontSize: 11 }}
                title={
                  needsInputOrDeclineChoice && !approved
                    ? "Add facts above and Save, or use No input needed to keep the critique without new data"
                    : undefined
                }
              >
                {approved ? "Approved" : rowGateBlocksApprove ? "Check feedback" : "Approve"}
              </button>
              <button type="button" onClick={() => startEdit(it)} disabled={disabled} style={{ fontSize: 11 }}>
                Edit
              </button>
              {vendor ? (
                <button
                  type="button"
                  onClick={requestMoreMachineContext}
                  disabled={
                    disabled ||
                    requestContextLoadingId === it.id ||
                    !String(it.observation || "").trim()
                  }
                  style={{ fontSize: 11 }}
                  title="Run the checker context again to suggest snippets the first pass may have missed"
                >
                  {requestContextLoadingId === it.id ? "…" : "Request context"}
                </button>
              ) : null}
              <button type="button" onClick={() => onRemove(it.id)} disabled={disabled} style={{ fontSize: 11, color: "#b91c1c" }}>
                Remove
              </button>
            </div>
          </>
        )}
      </li>
    );
  };

  const renderGoodRow = (it) => {
    const isEditing = editingId === it.id;
    const fieldId = `feedback_${categoryKey}_${it.id}`;
    const displayedObservation =
      translation && fieldId
        ? translation.getTranslatedText(fieldId, it.observation || "")
        : it.observation || "";

    return (
      <li
        key={it.id}
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 6,
          padding: 8,
          background: "#fafafa",
          fontSize: 13,
          color: "#4b5563",
        }}
      >
        {isEditing ? (
          <>
            <textarea
              style={{ width: "100%", minHeight: 72, padding: 8, fontSize: 13 }}
              value={draftObservation}
              onChange={(e) => setDraftObservation(e.target.value)}
              disabled={disabled}
            />
            <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <button
                type="button"
                onClick={() => setEditingPromoteToFix(true)}
                disabled={disabled || editingPromoteToFix}
                style={{
                  fontSize: 12,
                  border: "1px solid #d97706",
                  color: "#92400e",
                  background: "#fffbeb",
                }}
              >
                Turn into critique
              </button>
              {editingPromoteToFix ? (
                <span style={{ fontSize: 11, color: "#92400e" }}>Will save as an issue to fix</span>
              ) : null}
              <button type="button" onClick={saveEdit} disabled={disabled} style={{ fontSize: 12 }}>
                Save
              </button>
              <button type="button" onClick={cancelEdit} style={{ fontSize: 12 }}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{ whiteSpace: "pre-wrap" }}>{displayedObservation || "(empty)"}</div>
            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
              <button type="button" onClick={() => startEdit(it)} disabled={disabled} style={{ fontSize: 11 }}>
                Edit
              </button>
              <button type="button" onClick={() => onRemove(it.id)} disabled={disabled} style={{ fontSize: 11, color: "#b91c1c" }}>
                Remove
              </button>
            </div>
          </>
        )}
      </li>
    );
  };

  return (
    <div style={{ marginTop: 8, padding: 10, border: "1px solid #e5e7eb", borderRadius: 6, background: "#f9fafb" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontWeight: 700, color: "#111827" }}>{categoryKey.replace(/_/g, " ")}</div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
            AI observations. Approve, edit, or reject them, then approve the vendor for final letter generation.
          </div>
        </div>
        <button
          type="button"
          onClick={onAdd}
          disabled={disabled}
          style={{ fontSize: 12, padding: "4px 10px", cursor: disabled ? "not-allowed" : "pointer" }}
        >
          Add critique
        </button>
      </div>

      {fixItems.length === 0 ? (
        <div style={{ fontSize: 13, color: "#059669", padding: "10px 0", fontWeight: 500 }}>
          No open critiques in this category.
        </div>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {fixItems.map((it) => renderFixRow(it))}
        </ul>
      )}

      {filteredFeedbackDetails.length > 0 ? (
        <details
          style={{
            marginTop: 16,
            borderTop: "1px solid #e5e7eb",
            paddingTop: 12,
          }}
        >
          <summary
            style={{
              cursor: "pointer",
              fontSize: 13,
              color: "#6b7280",
              fontWeight: 500,
            }}
          >
            Filtered feedback ({filteredFeedbackDetails.length}) — not shown as critiques
          </summary>
          <p style={{ fontSize: 12, color: "#9ca3af", margin: "8px 0 10px" }}>
            The model (or legacy format) sent text that is intentionally not imported as open issues — for example NO
            COMMENT, SKIP, or an empty PLEASE FIX line.
          </p>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
            {filteredFeedbackDetails.map((entry, idx) => (
              <li
                key={`filtered-${idx}`}
                style={{
                  border: "1px solid #e5e7eb",
                  borderRadius: 6,
                  padding: 8,
                  background: "#fafafa",
                  fontSize: 13,
                  color: "#4b5563",
                }}
              >
                <div style={{ fontSize: 11, fontWeight: 600, color: "#9ca3af", marginBottom: 6 }}>{entry.label}</div>
                <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{entry.text}</div>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {goodItems.length > 0 ? (
        <details
          style={{
            marginTop: 16,
            borderTop: "1px solid #e5e7eb",
            paddingTop: 12,
          }}
        >
          <summary
            style={{
              cursor: "pointer",
              fontSize: 13,
              color: "#6b7280",
              fontWeight: 500,
            }}
          >
            Positive or neutral model notes ({goodItems.length}) — no approval needed
          </summary>
          <p style={{ fontSize: 12, color: "#9ca3af", margin: "8px 0 10px" }}>
            These are optional to read. Use Edit → “Turn into critique” if the model was too optimistic.
          </p>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            {goodItems.map((it) => renderGoodRow(it))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
