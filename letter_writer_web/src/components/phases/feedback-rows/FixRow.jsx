import React from "react";
import { CONTEXT_USER_SOURCE } from "../feedbackItemUtils";
import { LanguageSelectorTiny } from "./LanguageSelectorTiny";
import { MachineRow } from "./MachineRow";
import { UserContextRow, computePersistScope } from "./UserContextRow";
import { PersistScopeRadios } from "./PersistScopeRadios";

export function FixRow({
  it,
  categoryKey,
  approved,
  disabled,
  translation,
  vendor,
  isEditing,
  draftObservation,
  setDraftObservation,
  editingContextRow,
  setEditingContextRow,
  draftContextLine,
  setDraftContextLine,
  editingUserContextId,
  setEditingUserContextId,
  draftUserContext,
  setDraftUserContext,
  inputNeededDraftById,
  setInputNeededDraftById,
  inputClusterText,
  requestContextLoadingId,
  setRequestContextLoadingId,
  onApprovePleaseFix,
  onRemove,
  saveEdit,
  cancelEdit,
  startEdit,
  approveWithoutInput,
  commitInputNeededDraft,
  setPersistScope,
  setContextItems,
  updateContextItem,
  requestMoreMachineContext,
  saveUserContextRow,
  clearUserContext,
}) {
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
  const persistScope = computePersistScope(persistUserContextToCv, persistUserContextForAgents);
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

  const removeContextItem = (idx) => {
    const next = (contextItems || []).filter((_, i) => i !== idx);
    setContextItems(it, next);
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
    setContextItems(it, next);
    const newIdx = next.length - 1;
    setEditingContextRow({ itemId: it.id, index: newIdx });
    setDraftContextLine("");
  };

  const saveContextRowInline = () => {
    if (!editingContextRow || editingContextRow.itemId !== it.id) return;
    updateContextItem(it, contextItems, editingContextRow.index, { text: draftContextLine });
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
    saveUserContextRow(it, draftUserContext);
    setEditingUserContextId(null);
    setDraftUserContext("");
  };

  const cancelUserContextRowInline = () => {
    if (editingUserContextId !== it.id) return;
    setEditingUserContextId(null);
    setDraftUserContext("");
  };

  const machineContextVisible = contextItems.some((x) => String(x?.text ?? x ?? "").trim().length > 0);
  const hasDisplayContext =
    machineContextVisible ||
    userContextFilled ||
    inputDeclined ||
    (editingContextRow?.itemId === it.id && !isEditing) ||
    (editingUserContextId === it.id && !isEditing);

  const needsInputOrDeclineChoice = needsInput && !userContextFilled && !inputDeclined;
  const rowGateBlocksApprove =
    disabled ||
    approved ||
    (needsInput && !String(userContext || "").trim() && !inputDeclined);

  const handleCommitInputNeededDraft = () => {
    commitInputNeededDraft(it, inputDraftEffective, persistUserContextToCv, persistUserContextForAgents);
    setInputNeededDraftById((prev) => {
      if (!(it.id in prev)) return prev;
      const n = { ...prev };
      delete n[it.id];
      return n;
    });
  };

  const handleRequestMoreMachineContext = async () => {
    setRequestContextLoadingId(it.id);
    try {
      await requestMoreMachineContext(it);
    } finally {
      setRequestContextLoadingId(null);
    }
  };

  const renderApproveWithoutInputButton = () => (
    <button
      type="button"
      onClick={() => approveWithoutInput(it)}
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

  const renderInputNeededBlock = () => (
    <>
      <textarea
        style={{
          width: "100%",
          minHeight: 72,
          padding: 8,
          fontSize: 13,
          border: "1px solid #fca5a5",
          background: isEditing ? "#fef2f2" : undefined,
          marginTop: isEditing ? undefined : 6,
        }}
        value={inputDraftEffective}
        onChange={(e) =>
          setInputNeededDraftById((prev) => ({ ...prev, [it.id]: e.target.value }))
        }
        disabled={disabled}
        placeholder={userContextPlaceholder}
      />
      <PersistScopeRadios
        name={`persist-${it.id}`}
        scope={persistScope}
        onScopeChange={(scope) => setPersistScope(it, scope)}
        disabled={disabled}
      />
      <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <button
          type="button"
          onClick={handleCommitInputNeededDraft}
          disabled={disabled || !String(inputDraftEffective).trim()}
          style={{ fontSize: 12, padding: "4px 12px" }}
        >
          Save
        </button>
        {renderApproveWithoutInputButton()}
      </div>
    </>
  );

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
              {renderInputNeededBlock()}
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
                  onClick={handleRequestMoreMachineContext}
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
            {contextItems.map((row, idx) => (
              <MachineRow
                key={`${it.id}-ctx-${idx}`}
                itemId={it.id}
                idx={idx}
                raw={row}
                isRowEditing={editingContextRow?.itemId === it.id && editingContextRow?.index === idx}
                isEditing={isEditing}
                disabled={disabled}
                draftContextLine={draftContextLine}
                setDraftContextLine={setDraftContextLine}
                onSave={saveContextRowInline}
                onCancel={cancelContextRowInline}
                onStartEdit={startEditContextRow}
                onRemove={removeContextItem}
                onUpdateSource={(i, source) => updateContextItem(it, contextItems, i, { source })}
                onUpdatePersistScope={(i, patch) => updateContextItem(it, contextItems, i, patch)}
              />
            ))}
            <UserContextRow
              itemId={it.id}
              showInputEditor={showInputEditor}
              inputDeclined={inputDeclined}
              userContextFilled={userContextFilled}
              userContext={userContext}
              userContextPlaceholder={userContextPlaceholder}
              needsInput={needsInput}
              isEditingUser={editingUserContextId === it.id}
              disabled={disabled}
              draftUserContext={draftUserContext}
              setDraftUserContext={setDraftUserContext}
              persistScope={persistScope}
              onPersistScopeChange={(cv, agent) => {
                const scope = cv && agent ? "both" : !cv && agent ? "agent" : "none";
                setPersistScope(it, scope);
              }}
              onSave={saveUserContextRowInline}
              onCancel={cancelUserContextRowInline}
              onStartEdit={startEditUserContextRow}
              onClear={() => {
                clearUserContext(it);
                setEditingUserContextId(null);
                setDraftUserContext("");
                setInputNeededDraftById((prev) => {
                  if (!(it.id in prev)) return prev;
                  const n = { ...prev };
                  delete n[it.id];
                  return n;
                });
              }}
            />
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
              {renderInputNeededBlock()}
            </div>
          ) : null}
          <div style={{ fontSize: 13, whiteSpace: "pre-wrap", color: "#111827" }}>{displayedObservation || "(empty)"}</div>
          {hasDisplayContext ? (
            <div style={{ marginTop: 8, fontSize: 12, color: "#374151" }}>
              {contextItems.map((row, idx) => (
                <MachineRow
                  key={`${it.id}-ctx-${idx}`}
                  itemId={it.id}
                  idx={idx}
                  raw={row}
                  isRowEditing={editingContextRow?.itemId === it.id && editingContextRow?.index === idx}
                  isEditing={isEditing}
                  disabled={disabled}
                  draftContextLine={draftContextLine}
                  setDraftContextLine={setDraftContextLine}
                  onSave={saveContextRowInline}
                  onCancel={cancelContextRowInline}
                  onStartEdit={startEditContextRow}
                  onRemove={removeContextItem}
                  onUpdateSource={(i, source) => updateContextItem(it, contextItems, i, { source })}
                  onUpdatePersistScope={(i, patch) => updateContextItem(it, contextItems, i, patch)}
                />
              ))}
              <UserContextRow
                itemId={it.id}
                showInputEditor={showInputEditor}
                inputDeclined={inputDeclined}
                userContextFilled={userContextFilled}
                userContext={userContext}
                userContextPlaceholder={userContextPlaceholder}
                needsInput={needsInput}
                isEditingUser={editingUserContextId === it.id}
                disabled={disabled}
                draftUserContext={draftUserContext}
                setDraftUserContext={setDraftUserContext}
                persistScope={persistScope}
                onPersistScopeChange={(cv, agent) => {
                  const scope = cv && agent ? "both" : !cv && agent ? "agent" : "none";
                  setPersistScope(it, scope);
                }}
                onSave={saveUserContextRowInline}
                onCancel={cancelUserContextRowInline}
                onStartEdit={startEditUserContextRow}
                onClear={() => {
                  clearUserContext(it);
                  setEditingUserContextId(null);
                  setDraftUserContext("");
                  setInputNeededDraftById((prev) => {
                    if (!(it.id in prev)) return prev;
                    const n = { ...prev };
                    delete n[it.id];
                    return n;
                  });
                }}
              />
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
                onClick={handleRequestMoreMachineContext}
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
}
