import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AnnotatedDraft from "../AnnotatedDraft";
import { KnownWeaknessesPanel } from "./KnownWeaknessesPanel";
import { FixRow } from "./feedback-rows/FixRow";
import { GoodRow } from "./feedback-rows/GoodRow";
import { FeedbackItemsPanel } from "./FeedbackItemsPanel";
import { FEEDBACK_TYPES, mergeCategoryItems, newId, categoryHasPleaseFix, categoryAllItemsApproved, itemIsApproved, pleaseFixItems, isLayaHidden } from "./feedbackItemUtils";
import { InvalidItemsSection } from "./feedback-rows/FeedbackSections";
import { useFeedbackItemApprovals } from "../../hooks/useFeedbackItemApprovals";
import { useFeedbackItemEditing } from "../../hooks/useFeedbackItemEditing";
import { resolveQuoteSpan } from "../../utils/resolveQuoteSpan";
import { nextAnchoredNoteId } from "../../utils/nextAnchoredNoteId";
import { FEEDBACK_TOPIC_LABELS, TOPIC_NOTE_COLORS, vendorNoteColor, vendorNoteTitle } from "../../constants/feedbackTopics";
import LanguageSelector from "../LanguageSelector";

function SingleItemFeedback({
  categoryKey,
  itemId,
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
  duplicateLinkFlat,
  inputClusterText,
  onInputClusterBroadcast,
  vendor,
  onRemoved,
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
    removeItemAndApprovals: (id) => {
      approvals.removeItemAndApprovals(id);
      onRemoved?.(id);
    },
    maybeAdvanceTab: approvals.maybeAdvanceTab,
  });

  const it = items.find((row) => row.id === itemId);
  useEffect(() => {
    if (it && it.type === FEEDBACK_TYPES.PLEASE_FIX && !String(it.observation || "").trim() && editing.editingId !== it.id) {
      editing.startEdit(it);
    }
    // Intentionally run when the empty item appears, not on every editing identity change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [it?.id, it?.observation, it?.type]);

  if (!it) return <div style={{ fontSize: 13, color: "#6b7280" }}>This note was removed.</div>;

  const displayedObservation =
    translation && categoryKey
      ? translation.getTranslatedText(`feedback_${categoryKey}_${it.id}`, it.observation || "")
      : it.observation || "";

  if (it.type === FEEDBACK_TYPES.ALREADY_GOOD) {
    return (
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        <GoodRow
          it={it}
          isEditing={editing.editingId === it.id}
          disabled={disabled}
          draftObservation={editing.draftObservation}
          setDraftObservation={editing.setDraftObservation}
          editingPromoteToFix={editing.editingPromoteToFix}
          setEditingPromoteToFix={editing.setEditingPromoteToFix}
          displayedObservation={displayedObservation}
          onSave={editing.saveEdit}
          onCancel={editing.cancelEdit}
          onStartEdit={editing.startEdit}
          onRemove={editing.onRemove}
        />
      </ul>
    );
  }

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
    <ul style={{ listStyle: "none", margin: 0, padding: 0, flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <FixRow
        it={it}
        approved={feedbackItemApprovals[it.id] === true}
        isEditing={editing.editingId === it.id}
        pinActions
        {...fixRowProps}
      />
    </ul>
  );
}

export function DraftFeedbackView({
  cardPhaseEdits,
  cardPhaseData,
  handleEditChange,
  isLoading,
  approved,
  vendor,
  feedback,
  feedbackKeys,
  feedbackOverrides,
  activeFeedbackKey,
  feedbackItemApprovals,
  setFeedbackItemApprovals,
  setSelectedFeedbackTab,
  handleSaveFeedbackOverride,
  translation,
  inputClusterText,
  broadcastInputCluster,
}) {
  const letter = cardPhaseEdits.draft_letter ?? cardPhaseData.draft_letter ?? "";
  const [editingLetter, setEditingLetter] = useState(false);
  const [letterDraft, setLetterDraft] = useState(letter);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    if (!editingLetter) setLetterDraft(letter);
  }, [letter, editingLetter]);

  const fieldId = "draft_letter";
  useEffect(() => {
    if (translation && fieldId) translation.resetFieldTranslation(fieldId, letter || "");
  }, [letter, translation]);

  const viewLanguage = translation ? translation.getFieldViewLanguage(fieldId) : "source";
  const viewingTranslation = Boolean(translation && viewLanguage && viewLanguage !== "source");
  const displayedText = translation ? translation.getTranslatedText(fieldId, letter || "") : letter;

  const handleFieldLanguageChange = async (code) => {
    if (!translation) return;
    translation.setFieldViewLanguage(fieldId, code);
    if (code === "source") return;
    if (letter) await translation.translateField(fieldId, letter, code);
  };

  const duplicateLinkFlat = useMemo(() => {
    const rows = [];
    for (const k of feedbackKeys) {
      for (const it of mergeCategoryItems(feedback, feedbackOverrides, k)) {
        if (it.duplicate_group_id || it.input_cluster_key) {
          rows.push({
            id: it.id,
            categoryKey: k,
            duplicate_group_id: it.duplicate_group_id,
            input_cluster_key: it.input_cluster_key,
          });
        }
      }
    }
    return rows;
  }, [feedbackKeys, feedback, feedbackOverrides]);

  const itemsByCategory = useMemo(() => {
    const map = {};
    for (const k of feedbackKeys) {
      map[k] = mergeCategoryItems(feedback, feedbackOverrides, k);
    }
    return map;
  }, [feedbackKeys, feedback, feedbackOverrides]);

  const isWholeLetterItem = useCallback((it) => {
    if (viewingTranslation) return true;
    return !resolveQuoteSpan(letter, it.quote, it.matched_text);
  }, [letter, viewingTranslation]);

  const notes = useMemo(() => {
    const out = [];
    for (const key of feedbackKeys) {
      for (const it of itemsByCategory[key] || []) {
        if (viewingTranslation) continue;
        if (isLayaHidden(it)) continue;
        const span = resolveQuoteSpan(letter, it.quote, it.matched_text);
        if (!span) continue;
        out.push({
          id: it.id,
          categoryKey: key,
          title: vendorNoteTitle(it.type, key),
          color: vendorNoteColor(key),
          faint: itemIsApproved(it, feedbackItemApprovals),
          start: span.start,
          end: span.end,
          unanchored: false,
          body: it.observation,
        });
      }
    }
    return out;
  }, [feedbackKeys, itemsByCategory, letter, viewingTranslation, feedbackItemApprovals]);

  const wholeLetterKeys = useMemo(
    () => feedbackKeys.filter((key) => (itemsByCategory[key] || []).some(isWholeLetterItem)),
    [feedbackKeys, itemsByCategory, isWholeLetterItem],
  );

  const prevNoteStateRef = useRef(new Map());
  useEffect(() => {
    const prev = prevNoteStateRef.current;
    const nextMap = new Map(notes.map((n) => [n.id, n.faint]));
    if (prev.size === 0) {
      prevNoteStateRef.current = nextMap;
      return;
    }
    const currentGone = Boolean(expandedId) && !notes.some((n) => n.id === expandedId);
    const currentNowDealt = notes.some(
      (n) => n.id === expandedId && n.faint && prev.get(expandedId) === false,
    );
    prevNoteStateRef.current = nextMap;
    if (currentGone || currentNowDealt) {
      setExpandedId(nextAnchoredNoteId(notes, expandedId));
    }
  }, [notes, expandedId]);

  const layaUnscoredNotice = useMemo(() => {
    for (const key of feedbackKeys) {
      for (const it of itemsByCategory[key] || []) {
        if (it.laya_verdict === "unscored" && it.laya_error) return String(it.laya_error);
      }
    }
    return "";
  }, [feedbackKeys, itemsByCategory]);

  const hiddenAnchored = useMemo(() => {
    const out = [];
    for (const key of feedbackKeys) {
      for (const it of itemsByCategory[key] || []) {
        if (!isLayaHidden(it) || isWholeLetterItem(it)) continue;
        out.push({ ...it, categoryKey: key });
      }
    }
    return out;
  }, [feedbackKeys, itemsByCategory, isWholeLetterItem]);

  const restoreAnchored = (it) => {
    const key = it.categoryKey;
    const next = (itemsByCategory[key] || []).map((row) =>
      row.id === it.id ? { ...row, laya_restored: true } : row,
    );
    handleSaveFeedbackOverride(key, next);
  };

  const addCritique = (categoryKey) => {
    const id = newId();
    const items = itemsByCategory[categoryKey] || [];
    handleSaveFeedbackOverride(categoryKey, [
      ...items,
      { id, observation: "", type: FEEDBACK_TYPES.PLEASE_FIX, quote: "", matched_text: "" },
    ]);
    setFeedbackItemApprovals((prev) => ({ ...prev, [id]: false }));
    setExpandedId(id);
    setSelectedFeedbackTab?.(categoryKey);
  };

  return (
    <div data-testid="vendor-draft-view">
      <div style={{ fontSize: 13, color: "#374151" }}>
        {approved
          ? "Draft letter is approved. Edit to rerun refinement if needed."
          : "Review the draft and notes on the letter, then approve to generate the final letter."}
      </div>
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ fontWeight: 600, fontSize: 13, flex: 1 }}>Draft letter</label>
          {!editingLetter && (
            <button
              type="button"
              onClick={() => setEditingLetter(true)}
              disabled={isLoading}
              style={{
                fontSize: 12,
                padding: "4px 8px",
                opacity: isLoading ? 0.6 : 1,
                cursor: isLoading ? "not-allowed" : "pointer",
              }}
            >
              ✎ Edit
            </button>
          )}
        </div>
        {editingLetter ? (
          <>
            <textarea
              style={{ width: "100%", minHeight: 220, padding: 8 }}
              value={letterDraft}
              onChange={(e) => setLetterDraft(e.target.value)}
              disabled={isLoading}
              wrap="soft"
              spellCheck={true}
            />
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={() => {
                  handleEditChange("draft_letter", letterDraft);
                  setEditingLetter(false);
                }}
                disabled={isLoading}
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  setLetterDraft(letter);
                  setEditingLetter(false);
                }}
                disabled={isLoading}
              >
                Discard
              </button>
            </div>
          </>
        ) : (
          <div style={{ position: "relative" }}>
            {translation && (
              <div
                style={{
                  position: "absolute",
                  right: -1,
                  top: -10,
                  zIndex: 10,
                  background: "#f9fafb",
                  border: "1px solid #e5e7eb",
                  borderLeft: "none",
                  borderTopRightRadius: 4,
                  borderBottomRightRadius: 4,
                  padding: "2px 2px 2px 4px",
                }}
              >
                <LanguageSelector
                  languages={translation.languages}
                  viewLanguage={viewLanguage}
                  onLanguageChange={handleFieldLanguageChange}
                  hasTranslation={(code) => translation.hasTranslation(fieldId, code)}
                  disabled={isLoading}
                  isTranslating={translation.isTranslating[fieldId] || false}
                  size="tiny"
                />
              </div>
            )}
            <AnnotatedDraft
              text={displayedText}
              notes={notes}
              expandedId={expandedId}
              onToggle={setExpandedId}
              translationNotice={
                viewingTranslation
                  ? "Notes attach to the source letter. Switch back to the original language to see highlights."
                  : null
              }
              renderExpanded={(note) => (
                <SingleItemFeedback
                  key={note.id}
                  categoryKey={note.categoryKey}
                  itemId={note.id}
                  items={itemsByCategory[note.categoryKey] || []}
                  feedbackItemApprovals={feedbackItemApprovals}
                  setFeedbackItemApprovals={setFeedbackItemApprovals}
                  handleSaveFeedbackOverride={handleSaveFeedbackOverride}
                  feedbackKeys={feedbackKeys}
                  feedback={feedback}
                  feedbackOverrides={feedbackOverrides}
                  activeFeedbackKey={activeFeedbackKey}
                  setSelectedFeedbackTab={setSelectedFeedbackTab}
                  disabled={isLoading}
                  translation={translation}
                  duplicateLinkFlat={duplicateLinkFlat}
                  inputClusterText={inputClusterText || {}}
                  onInputClusterBroadcast={broadcastInputCluster}
                  vendor={vendor}
                />
              )}
            />
          </div>
        )}
      </div>
      {wholeLetterKeys.length > 0 && (
        <div data-testid="unanchored-notes" style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 4 }}>
            Notes on the letter as a whole
          </div>
          {wholeLetterKeys.map((key) => (
            <FeedbackItemsPanel
              key={`${vendor}-whole-${key}`}
              categoryKey={key}
              items={itemsByCategory[key] || []}
              itemPredicate={isWholeLetterItem}
              hideAddButton
              hideEmptyFixPlaceholder
              feedbackItemApprovals={feedbackItemApprovals}
              setFeedbackItemApprovals={setFeedbackItemApprovals}
              handleSaveFeedbackOverride={handleSaveFeedbackOverride}
              feedbackKeys={feedbackKeys}
              feedback={feedback}
              feedbackOverrides={feedbackOverrides}
              activeFeedbackKey={activeFeedbackKey}
              setSelectedFeedbackTab={setSelectedFeedbackTab}
              disabled={isLoading}
              translation={translation}
              duplicateLinkFlat={duplicateLinkFlat}
              inputClusterText={inputClusterText || {}}
              onInputClusterBroadcast={broadcastInputCluster}
              vendor={vendor}
            />
          ))}
        </div>
      )}
      {layaUnscoredNotice && (
        <div style={{ fontSize: 12, color: "#92400e", marginTop: 10 }}>
          Laya did not score these comments: {layaUnscoredNotice}
        </div>
      )}
      <InvalidItemsSection items={hiddenAnchored} disabled={isLoading} onRestore={restoreAnchored} />
      <KnownWeaknessesPanel items={cardPhaseData.known_weaknesses} />
      {feedbackKeys.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 6 }}>
            Feedback summary
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {feedbackKeys.map((key) => {
              const baseItems = mergeCategoryItems(feedback, {}, key);
              const displayItems = itemsByCategory[key] || [];
              const fixItems = pleaseFixItems(displayItems);
              const machineStatus = categoryHasPleaseFix(baseItems) ? "📜" : "✅";
              const humanOk = categoryAllItemsApproved(displayItems, feedbackItemApprovals);
              const humanStatus = fixItems.length === 0 ? "✅" : humanOk ? "👍" : "❔";
              const pending = fixItems.filter((it) => !itemIsApproved(it, feedbackItemApprovals));
              const topicColor = TOPIC_NOTE_COLORS[key] || "#6b7280";
              const topicLabel = FEEDBACK_TOPIC_LABELS[key] || key.replace(/_/g, " ");
              return (
                <div
                  key={`${vendor}-sum-${key}`}
                  style={{ display: "inline-flex", alignItems: "center", gap: 2 }}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedFeedbackTab(key);
                      const target = pending[0] || fixItems[0];
                      if (target) setExpandedId(target.id);
                    }}
                    style={{
                      padding: "4px 8px",
                      fontSize: 12,
                      borderRadius: 4,
                      border: `1px solid ${topicColor}`,
                      borderLeftWidth: 4,
                      background: "#f9fafb",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {key}
                    <span data-testid={`feedback-count-${key}`} style={{ color: "#6b7280" }}>{fixItems.length}</span>
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 0, marginLeft: 4 }}>
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 2, padding: "0 4px" }}>
                        🤖 {machineStatus}
                      </div>
                      <div style={{ width: 2, background: "#d1d5db", height: 14, margin: "0 4px" }} />
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 2, padding: "0 4px" }}>
                        🧑 {humanStatus}
                      </div>
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label={`Add critique · ${topicLabel}`}
                    title={`Add critique · ${topicLabel}`}
                    onClick={() => addCritique(key)}
                    disabled={isLoading}
                    style={{
                      width: 22,
                      height: 22,
                      padding: 0,
                      fontSize: 16,
                      lineHeight: 1,
                      border: `1px solid ${topicColor}`,
                      borderRadius: 4,
                      background: "#f9fafb",
                      color: topicColor,
                      cursor: isLoading ? "not-allowed" : "pointer",
                      opacity: isLoading ? 0.6 : 1,
                    }}
                  >
                    +
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
