import React, { useMemo } from "react";
import { FEEDBACK_TYPES, filteredFeedbackDetailsFromRaw } from "./feedbackItemUtils";
import { KnownWeaknessesPanel } from "./KnownWeaknessesPanel";
import { FixRow } from "./feedback-rows/FixRow";
import { FilteredFeedbackSection, GoodItemsSection } from "./feedback-rows/FeedbackSections";
import { useFeedbackItemApprovals } from "../../hooks/useFeedbackItemApprovals";
import { useFeedbackItemEditing } from "../../hooks/useFeedbackItemEditing";

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
  knownWeaknesses = undefined,
}) {
  const approvals = useFeedbackItemApprovals({
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
  });

  const editing = useFeedbackItemEditing({
    categoryKey,
    items,
    feedback,
    feedbackItemApprovals,
    setFeedbackItemApprovals,
    persistItems: approvals.persistItems,
    removeItemAndApprovals: approvals.removeItemAndApprovals,
    maybeAdvanceTab: approvals.maybeAdvanceTab,
  });

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

  const fixRowProps = {
    categoryKey,
    disabled,
    translation,
    vendor,
    draftObservation: editing.draftObservation,
    setDraftObservation: editing.setDraftObservation,
    editingContextRow: editing.editingContextRow,
    setEditingContextRow: editing.setEditingContextRow,
    draftContextLine: editing.draftContextLine,
    setDraftContextLine: editing.setDraftContextLine,
    editingUserContextId: editing.editingUserContextId,
    setEditingUserContextId: editing.setEditingUserContextId,
    draftUserContext: editing.draftUserContext,
    setDraftUserContext: editing.setDraftUserContext,
    inputNeededDraftById: editing.inputNeededDraftById,
    setInputNeededDraftById: editing.setInputNeededDraftById,
    inputClusterText,
    requestContextLoadingId: editing.requestContextLoadingId,
    setRequestContextLoadingId: editing.setRequestContextLoadingId,
    onRemove: editing.onRemove,
    saveEdit: editing.saveEdit,
    cancelEdit: editing.cancelEdit,
    startEdit: editing.startEdit,
    onApprovePleaseFix: approvals.onApprovePleaseFix,
    approveWithoutInput: approvals.approveWithoutInput,
    commitInputNeededDraft: approvals.commitInputNeededDraft,
    setPersistScope: approvals.setPersistScope,
    setContextItems: approvals.setContextItems,
    updateContextItem: approvals.updateContextItem,
    requestMoreMachineContext: approvals.requestMoreMachineContext,
    saveUserContextRow: approvals.saveUserContextRow,
    clearUserContext: approvals.clearUserContext,
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
          onClick={editing.onAdd}
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
          {fixItems.map((it) => (
            <FixRow
              key={it.id}
              it={it}
              approved={feedbackItemApprovals[it.id] === true}
              isEditing={editing.editingId === it.id}
              {...fixRowProps}
            />
          ))}
        </ul>
      )}

      <FilteredFeedbackSection entries={filteredFeedbackDetails} />

      <GoodItemsSection
        goodItems={goodItems}
        categoryKey={categoryKey}
        translation={translation}
        editingId={editing.editingId}
        disabled={disabled}
        draftObservation={editing.draftObservation}
        setDraftObservation={editing.setDraftObservation}
        editingPromoteToFix={editing.editingPromoteToFix}
        setEditingPromoteToFix={editing.setEditingPromoteToFix}
        onSave={editing.saveEdit}
        onCancel={editing.cancelEdit}
        onStartEdit={editing.startEdit}
        onRemove={editing.onRemove}
      />

      <KnownWeaknessesPanel items={knownWeaknesses} />
    </div>
  );
}
