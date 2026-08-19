import { useState } from "react";
import { FEEDBACK_TYPES, mergeCategoryItems, newId } from "../components/phases/feedbackItemUtils";

export function useFeedbackItemEditing({
  categoryKey,
  items,
  feedback,
  feedbackItemApprovals,
  setFeedbackItemApprovals,
  persistItems,
  removeItemAndApprovals,
  maybeAdvanceTab,
}) {
  const [editingId, setEditingId] = useState(null);
  const [requestContextLoadingId, setRequestContextLoadingId] = useState(null);
  const [draftObservation, setDraftObservation] = useState("");
  const [editingPromoteToFix, setEditingPromoteToFix] = useState(false);
  const [editingUserContextId, setEditingUserContextId] = useState(null);
  const [draftUserContext, setDraftUserContext] = useState("");
  const [inputNeededDraftById, setInputNeededDraftById] = useState({});
  const [editingContextRow, setEditingContextRow] = useState(null);
  const [draftContextLine, setDraftContextLine] = useState("");

  const resetEditFields = () => {
    setEditingId(null);
    setDraftObservation("");
    setEditingPromoteToFix(false);
    setEditingContextRow(null);
    setDraftContextLine("");
    setEditingUserContextId(null);
    setDraftUserContext("");
  };

  const clearEditingForId = (id) => {
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
    removeItemAndApprovals(id);
    clearEditingForId(id);
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

  const mapObservationSave = (obs, obsChanged, targetType) =>
    items.map((x) => {
      if (x.id !== editingId) return x;
      let row = { ...x, observation: obs, type: targetType };
      if (obsChanged && row.duplicate_group_id) {
        const { duplicate_group_id: _d, ...rest } = row;
        row = rest;
      }
      return row;
    });

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
        onRemove(editingId);
        return;
      }
      const next = mapObservationSave(obs, obsChanged, FEEDBACK_TYPES.PLEASE_FIX);
      persistItems(next);
      const nextApr = { ...feedbackItemApprovals, [editingId]: true };
      setFeedbackItemApprovals(nextApr);
      maybeAdvanceTab(next, nextApr);
    } else {
      if (!obs) return;
      if (editingPromoteToFix) {
        persistItems(mapObservationSave(obs, obsChanged, FEEDBACK_TYPES.PLEASE_FIX));
        setFeedbackItemApprovals((prev) => ({ ...prev, [editingId]: false }));
      } else {
        persistItems(mapObservationSave(obs, obsChanged, FEEDBACK_TYPES.ALREADY_GOOD));
      }
    }
    resetEditFields();
  };

  const cancelEdit = () => {
    const closedId = editingId;
    const it = items.find((i) => i.id === closedId);
    if (it && it.type === FEEDBACK_TYPES.PLEASE_FIX && !String(it.observation || "").trim()) {
      onRemove(closedId);
      return;
    }
    resetEditFields();
    if (closedId) {
      setInputNeededDraftById((prev) => {
        if (!(closedId in prev)) return prev;
        const n = { ...prev };
        delete n[closedId];
        return n;
      });
    }
  };

  return {
    editingId,
    requestContextLoadingId,
    setRequestContextLoadingId,
    draftObservation,
    setDraftObservation,
    editingPromoteToFix,
    setEditingPromoteToFix,
    editingUserContextId,
    setEditingUserContextId,
    draftUserContext,
    setDraftUserContext,
    inputNeededDraftById,
    setInputNeededDraftById,
    editingContextRow,
    setEditingContextRow,
    draftContextLine,
    setDraftContextLine,
    onAdd,
    onRemove,
    startEdit,
    saveEdit,
    cancelEdit,
  };
}
