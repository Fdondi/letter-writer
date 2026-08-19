import { useCallback } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { showNotification } from "../utils/apiNotifications";
import {
  CONTEXT_SOURCES,
  CONTEXT_USER_SOURCE,
  selectNextTabIfCategoryDone,
} from "../components/phases/feedbackItemUtils";

/**
 * Duplicate-link resolution, approval gates, and context mutation handlers for feedback items.
 */
export function useFeedbackItemApprovals({
  categoryKey,
  items,
  feedbackItemApprovals,
  setFeedbackItemApprovals,
  duplicateLinkFlat,
  feedbackKeys,
  feedback,
  feedbackOverrides,
  activeFeedbackKey,
  setSelectedFeedbackTab,
  handleSaveFeedbackOverride,
  vendor,
  onInputClusterBroadcast,
}) {
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

  const persistItems = useCallback(
    (nextItems) => {
      handleSaveFeedbackOverride(categoryKey, nextItems);
    },
    [handleSaveFeedbackOverride, categoryKey],
  );

  const maybeAdvanceTab = useCallback(
    (nextItems, nextApr) => {
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
    },
    [activeFeedbackKey, feedbackKeys, feedback, feedbackOverrides, categoryKey, setSelectedFeedbackTab],
  );

  const applyLinkedApproval = useCallback(
    (item, nextApr, approved) => {
      linkedApprovalIds(item).forEach((i) => {
        nextApr[i] = approved;
      });
      return nextApr;
    },
    [linkedApprovalIds],
  );

  const onApprovePleaseFix = useCallback(
    (id) => {
      const it = items.find((x) => x.id === id);
      if (!it) return;
      const status = String(it.status || "NOT_NEEDED").toUpperCase();
      if (status === "INPUT_NEEDED") {
        const filled = String(it.user_context || "").trim().length > 0;
        const declined = it.input_declined === true;
        if (!filled && !declined) return;
      }
      const nextApr = { ...feedbackItemApprovals };
      applyLinkedApproval(it, nextApr, true);
      setFeedbackItemApprovals(nextApr);
      maybeAdvanceTab(items, nextApr);
    },
    [items, feedbackItemApprovals, applyLinkedApproval, setFeedbackItemApprovals, maybeAdvanceTab],
  );

  const approveLinkedItems = useCallback(
    (item, nextItems) => {
      setFeedbackItemApprovals((prev) => {
        const nextApr = { ...prev };
        applyLinkedApproval(item, nextApr, true);
        maybeAdvanceTab(nextItems, nextApr);
        return nextApr;
      });
    },
    [applyLinkedApproval, setFeedbackItemApprovals, maybeAdvanceTab],
  );

  const revokeLinkedItems = useCallback(
    (item) => {
      setFeedbackItemApprovals((prev) => {
        const next = { ...prev };
        applyLinkedApproval(item, next, false);
        return next;
      });
    },
    [applyLinkedApproval, setFeedbackItemApprovals],
  );

  const approveWithoutInput = useCallback(
    (item) => {
      const nextItems = items.map((x) =>
        x.id === item.id ? { ...x, input_declined: true } : x,
      );
      persistItems(nextItems);
      const nextApr = { ...feedbackItemApprovals };
      applyLinkedApproval(item, nextApr, true);
      setFeedbackItemApprovals(nextApr);
      maybeAdvanceTab(nextItems, nextApr);
    },
    [items, persistItems, feedbackItemApprovals, applyLinkedApproval, setFeedbackItemApprovals, maybeAdvanceTab],
  );

  const removeItemAndApprovals = useCallback(
    (id) => {
      const nextItems = items.filter((it) => it.id !== id);
      persistItems(nextItems);
      const nextApr = { ...feedbackItemApprovals };
      delete nextApr[id];
      setFeedbackItemApprovals(nextApr);
      maybeAdvanceTab(nextItems, nextApr);
      return nextItems;
    },
    [items, persistItems, feedbackItemApprovals, setFeedbackItemApprovals, maybeAdvanceTab],
  );

  const setUserContext = useCallback(
    (item, next, patch = {}) => {
      const text = String(next ?? "");
      const nextItems = items.map((x) =>
        x.id === item.id ? { ...x, user_context: text, ...patch } : x,
      );
      persistItems(nextItems);
      if (onInputClusterBroadcast && item.input_cluster_key && text.trim()) {
        onInputClusterBroadcast(item.input_cluster_key, text);
      }
      return nextItems;
    },
    [items, persistItems, onInputClusterBroadcast],
  );

  const setPersistScope = useCallback(
    (item, scope) => {
      const cv = scope === "both";
      const agent = scope === "both" || scope === "agent";
      const nextItems = items.map((x) =>
        x.id === item.id
          ? { ...x, persist_user_context_to_cv: cv, persist_user_context_for_agents: agent }
          : x,
      );
      persistItems(nextItems);
    },
    [items, persistItems],
  );

  const commitInputNeededDraft = useCallback(
    (item, raw, persistUserContextToCv, persistUserContextForAgents) => {
      if (!String(raw ?? "").trim()) return null;
      const nextItems = items.map((x) =>
        x.id === item.id
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
      if (onInputClusterBroadcast && item.input_cluster_key) {
        onInputClusterBroadcast(item.input_cluster_key, raw);
      }
      approveLinkedItems(item, nextItems);
      return nextItems;
    },
    [items, persistItems, onInputClusterBroadcast, approveLinkedItems],
  );

  const setContextItems = useCallback(
    (item, nextContextItems) => {
      const arr = Array.isArray(nextContextItems) ? nextContextItems : [];
      const status = String(item.status || "NOT_NEEDED").toUpperCase();
      const hasRows = arr.length > 0;
      const nonEmpty = arr.some((x) => String(x?.text ?? x ?? "").trim().length > 0);
      const nextStatus =
        status === "INPUT_NEEDED"
          ? "INPUT_NEEDED"
          : hasRows || nonEmpty
            ? "SUFFICIENT"
            : "NOT_NEEDED";

      const nextItems = items.map((x) => {
        if (x.id !== item.id) return x;
        return {
          ...x,
          status: nextStatus,
          context_field: { ...(x.context_field || {}), items: arr },
        };
      });
      persistItems(nextItems);
      return nextItems;
    },
    [items, persistItems],
  );

  const updateContextItem = useCallback(
    (item, contextItems, idx, patch) => {
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
      setContextItems(item, next);
      return next;
    },
    [setContextItems],
  );

  const requestMoreMachineContext = useCallback(
    async (item) => {
      if (!vendor) return;
      const obs = String(item.observation || "").trim();
      if (!obs) return;
      const contextItems = Array.isArray(item?.context_field?.items) ? item.context_field.items : [];
      const status = String(item.status || "NOT_NEEDED").toUpperCase();
      try {
        const { data, isHeartbeat } = await fetchWithHeartbeat(
          `/api/phases/feedback/request-context/${encodeURIComponent(vendor)}/`,
          { method: "POST", body: JSON.stringify({ category: categoryKey, item_id: item.id }) },
        );
        if (isHeartbeat) {
          showNotification("Request still processing; try again in a moment.");
          return false;
        }
        const incoming = Array.isArray(data?.items) ? data.items : [];
        const seen = new Set(
          contextItems
            .map((r) => String(r?.text ?? r ?? "").trim().toLowerCase())
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
          return false;
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
          x.id === item.id
            ? {
                ...x,
                status: nextStatus,
                context_field: { ...(x.context_field || {}), items: nextRows },
              }
            : x,
        );
        persistItems(nextItems);
        showNotification(`Added ${appended.length} context line(s).`);
        return true;
      } catch (e) {
        showNotification(e?.message || String(e));
        return false;
      }
    },
    [vendor, categoryKey, items, persistItems],
  );

  const saveUserContextRow = useCallback(
    (item, draftUserContext) => {
      setUserContext(item, draftUserContext, { input_declined: false });
      if (String(draftUserContext || "").trim()) {
        approveLinkedItems(item, items);
      } else {
        revokeLinkedItems(item);
      }
    },
    [setUserContext, approveLinkedItems, revokeLinkedItems, items],
  );

  const clearUserContext = useCallback(
    (item) => {
      setUserContext(item, "", { input_declined: false });
      setFeedbackItemApprovals((prev) => ({ ...prev, [item.id]: false }));
    },
    [setUserContext, setFeedbackItemApprovals],
  );

  return {
    linkedApprovalIds,
    persistItems,
    onApprovePleaseFix,
    approveLinkedItems,
    revokeLinkedItems,
    approveWithoutInput,
    removeItemAndApprovals,
    setUserContext,
    setPersistScope,
    commitInputNeededDraft,
    setContextItems,
    updateContextItem,
    requestMoreMachineContext,
    saveUserContextRow,
    clearUserContext,
    maybeAdvanceTab,
  };
}
