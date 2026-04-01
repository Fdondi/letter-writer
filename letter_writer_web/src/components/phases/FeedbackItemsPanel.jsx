import React, { useMemo, useState } from "react";
import LanguageSelector from "../LanguageSelector";
import { FEEDBACK_TYPES, newId, selectNextTabIfCategoryDone } from "./feedbackItemUtils";

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
}) {
  const [editingId, setEditingId] = useState(null);
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

  const fixItems = useMemo(
    () => items.filter((it) => it.type === FEEDBACK_TYPES.PLEASE_FIX),
    [items],
  );
  const goodItems = useMemo(
    () => items.filter((it) => it.type === FEEDBACK_TYPES.ALREADY_GOOD),
    [items],
  );

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
    if (it) {
      const status = String(it.status || "NOT_NEEDED").toUpperCase();
      if (status === "INPUT_NEEDED") {
        const filled = String(it.user_context || "").trim().length > 0;
        if (!filled) return;
      }
    }
    const nextApr = { ...feedbackItemApprovals, [id]: true };
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

  /** Demote a critique to a positive note (hidden section). */
  const skipToPositive = (id, obsFromDraft) => {
    const it = items.find((i) => i.id === id);
    if (!it || it.type !== FEEDBACK_TYPES.PLEASE_FIX) return;
    const obs = (obsFromDraft !== undefined ? obsFromDraft : it.observation || "").trim();
    const finalObs = obs || (it.observation || "").trim();
    if (!finalObs) {
      onRemove(id);
      return;
    }
    const next = items.map((x) =>
      x.id === id ? { ...x, type: FEEDBACK_TYPES.ALREADY_GOOD, observation: finalObs } : x,
    );
    persistItems(next);
    const nextApr = { ...feedbackItemApprovals };
    delete nextApr[id];
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
    if (editingId === id) {
      setEditingId(null);
      setDraftObservation("");
      setEditingPromoteToFix(false);
    }
    if (editingContextRow?.itemId === id) {
      setEditingContextRow(null);
      setDraftContextLine("");
    }
    if (editingUserContextId === id) {
      setEditingUserContextId(null);
      setDraftUserContext("");
    }
    setInputNeededDraftById((prev) => {
      if (!(id in prev)) return prev;
      const n = { ...prev };
      delete n[id];
      return n;
    });
  };

  const saveEdit = () => {
    if (!editingId) return;
    const it = items.find((i) => i.id === editingId);
    if (!it) return;
    const obs = (draftObservation || "").trim();

    if (it.type === FEEDBACK_TYPES.PLEASE_FIX) {
      if (!obs) return;
      const next = items.map((x) =>
        x.id === editingId ? { ...x, observation: obs, type: FEEDBACK_TYPES.PLEASE_FIX } : x,
      );
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
        const next = items.map((x) =>
          x.id === editingId ? { ...x, observation: obs, type: FEEDBACK_TYPES.PLEASE_FIX } : x,
        );
        persistItems(next);
        setFeedbackItemApprovals((prev) => ({ ...prev, [editingId]: false }));
      } else {
        const next = items.map((x) =>
          x.id === editingId ? { ...x, observation: obs, type: FEEDBACK_TYPES.ALREADY_GOOD } : x,
        );
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
    /** Initial capture only; after Save, user text lives in user_context and is edited like other context lines. */
    const showInputEditor = needsInput && !userContextFilled;
    const inputDraft = inputNeededDraftById[it.id] ?? "";
    const userContextPlaceholder =
      userInstructions.trim() ||
      "Paste the missing facts/context here (or delete the item).";
    const displayedObservation =
      translation && fieldId
        ? translation.getTranslatedText(fieldId, it.observation || "")
        : it.observation || "";

    const setUserContext = (next) => {
      const nextItems = items.map((x) =>
        x.id === it.id ? { ...x, user_context: String(next ?? "") } : x,
      );
      persistItems(nextItems);
    };

    const commitInputNeededDraft = () => {
      const raw = String(inputNeededDraftById[it.id] ?? "");
      if (!raw.trim()) return;
      setUserContext(raw);
      setInputNeededDraftById((prev) => {
        if (!(it.id in prev)) return prev;
        const n = { ...prev };
        delete n[it.id];
        return n;
      });
    };

    const setContextItems = (nextContextItems) => {
      const arr = Array.isArray(nextContextItems) ? nextContextItems : [];
      const hasRows = arr.length > 0;
      const nonEmpty = arr.some((x) => String(x ?? "").trim().length > 0);
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

    const updateContextItem = (idx, value) => {
      const next = [...(contextItems || [])];
      next[idx] = String(value ?? "");
      setContextItems(next);
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
      const next = [...(contextItems || []), ""];
      setContextItems(next);
      const newIdx = next.length - 1;
      setEditingContextRow({ itemId: it.id, index: newIdx });
      setDraftContextLine("");
    };

    const saveContextRowInline = () => {
      if (!editingContextRow || editingContextRow.itemId !== it.id) return;
      updateContextItem(editingContextRow.index, draftContextLine);
      setEditingContextRow(null);
      setDraftContextLine("");
    };

    const cancelContextRowInline = () => {
      if (!editingContextRow || editingContextRow.itemId !== it.id) return;
      const idx = editingContextRow.index;
      const line = String(contextItems[idx] ?? "");
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
      setDraftContextLine(String(contextItems[idx] ?? ""));
    };

    const startEditUserContextRow = () => {
      setEditingContextRow(null);
      setDraftContextLine("");
      setEditingUserContextId(it.id);
      setDraftUserContext(userContext);
    };

    const saveUserContextRowInline = () => {
      if (editingUserContextId !== it.id) return;
      setUserContext(draftUserContext);
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

    const machineContextVisible = contextItems.some((x) => String(x ?? "").trim().length > 0);
    const hasDisplayContext =
      machineContextVisible ||
      userContextFilled ||
      (editingContextRow?.itemId === it.id && !isEditing) ||
      (editingUserContextId === it.id && !isEditing);

    const renderMachineRow = (idx) => {
      const text = String(contextItems[idx] ?? "");
      const isRowEditing = editingContextRow?.itemId === it.id && editingContextRow?.index === idx;
      if (!text.trim() && !isRowEditing && !isEditing) return null;

      if (isRowEditing) {
        return (
          <div key={`${it.id}-ctx-${idx}`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
            <textarea
              style={{ flex: 1, minHeight: 56, fontSize: 13, padding: 8, resize: "vertical" }}
              value={draftContextLine}
              onChange={(e) => setDraftContextLine(e.target.value)}
              disabled={disabled}
              placeholder="Paste-ready fact/snippet (no instructions)"
            />
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
          <div style={{ flex: 1, minWidth: 0, whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.45, color: "#111827" }}>
            {text.trim() ? text : "(empty)"}
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
      if (!userContextFilled && !isEditingUser) return null;

      if (isEditingUser) {
        return (
          <div key={`${it.id}-ctx-user`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
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
        );
      }

      return (
        <div key={`${it.id}-ctx-user`} style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 8 }}>
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
                setUserContext("");
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
      );
    };

    return (
      <li
        key={it.id}
        style={{
          border: "1px solid #fcd34d",
          borderRadius: 6,
          padding: 10,
          background: "#fffbeb",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "#92400e", textTransform: "uppercase", letterSpacing: "0.04em" }}>
            Critique
          </span>
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
                  value={inputDraft}
                  onChange={(e) =>
                    setInputNeededDraftById((prev) => ({ ...prev, [it.id]: e.target.value }))
                  }
                  disabled={disabled}
                  placeholder={userContextPlaceholder}
                />
                <div style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    onClick={commitInputNeededDraft}
                    disabled={disabled || !String(inputDraft).trim()}
                    style={{ fontSize: 12, padding: "4px 12px" }}
                  >
                    Save input
                  </button>
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
                  title="Add a paste-ready fact/snippet the model can use"
                >
                  Add context
                </button>
                {status === "INPUT_NEEDED" ? (
                  <span style={{ fontSize: 11, color: "#b91c1c" }}>
                    This item still requires user input before approval.
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
              <button
                type="button"
                onClick={() => skipToPositive(it.id, draftObservation)}
                disabled={disabled}
                style={{ fontSize: 12, color: "#4b5563", border: "1px solid #d1d5db", background: "#fff" }}
                title="Treat as a non-issue; move to positive notes"
              >
                Skip
              </button>
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
                  value={inputDraft}
                  onChange={(e) =>
                    setInputNeededDraftById((prev) => ({ ...prev, [it.id]: e.target.value }))
                  }
                  disabled={disabled}
                  placeholder={userContextPlaceholder}
                />
                <div style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    onClick={commitInputNeededDraft}
                    disabled={disabled || !String(inputDraft).trim()}
                    style={{ fontSize: 12, padding: "4px 12px" }}
                  >
                    Save input
                  </button>
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
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
              <button
                type="button"
                onClick={() => onApprovePleaseFix(it.id)}
                disabled={disabled || approved || (needsInput && !String(userContext || "").trim())}
                style={{ fontSize: 11 }}
              >
                {approved ? "Approved" : "Approve"}
              </button>
              <button type="button" onClick={() => startEdit(it)} disabled={disabled} style={{ fontSize: 11 }}>
                Edit
              </button>
              <button
                type="button"
                onClick={() => skipToPositive(it.id, it.observation)}
                disabled={disabled}
                style={{ fontSize: 11, color: "#4b5563" }}
              >
                Skip
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
