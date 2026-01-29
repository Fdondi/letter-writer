import React from "react";
import CompetenceLine from "./CompetenceLine";
import { getEffectiveRating, getEffectiveImportance } from "../utils/competenceScales";

/**
 * List of competences: each line = stars (level + need) + text. Optional edit/add/remove.
 * - requirements, competences, scaleConfig, editable, displayTexts, onRequirementsChange, onCompetencesChange
 * - overrides: { [skill]: { presence?: number, importance?: number } } for user-edited ratings
 * - onOverridesChange: (next) => void
 */
export default function CompetencesList({
  requirements = [],
  competences = {},
  scaleConfig,
  overrides = {},
  onOverridesChange,
  editable = false,
  displayTexts = null,
  onRequirementsChange,
  onCompetencesChange,
}) {
  const comp = typeof competences === "object" && competences !== null ? competences : {};
  const list = Array.isArray(requirements) ? requirements : requirements ? [requirements] : [];
  const texts = Array.isArray(displayTexts) && displayTexts.length === list.length
    ? displayTexts
    : list;

  const getRating = (skill) => {
    const t = (skill ?? "").trim();
    if (!t) return { presence: null, importance: null };
    return getEffectiveRating(t, comp, scaleConfig, overrides);
  };

  const getLabels = (skill) => {
    const t = (skill ?? "").trim();
    if (!t || !(t in comp)) return { needLabel: null, levelLabel: null };
    const val = comp[t];
    if (typeof val === "object" && val !== null && "need" in val && "level" in val) {
      return { needLabel: val.need ?? null, levelLabel: val.level ?? null };
    }
    return { needLabel: null, levelLabel: null };
  };

  // Sort by importance * (presence - 2.5). "expected" uses log-scaled importance.
  const sortedIndices = [...list.keys()].sort((a, b) => {
    const skillA = (list[a] ?? "").trim();
    const skillB = (list[b] ?? "").trim();
    const ratingA = getRating(skillA);
    const ratingB = getRating(skillB);
    const impA = getEffectiveImportance(skillA, comp, scaleConfig, overrides);
    const impB = getEffectiveImportance(skillB, comp, scaleConfig, overrides);

    if (ratingA.presence == null || impA == null) return 1;
    if (ratingB.presence == null || impB == null) return -1;

    const scoreA = impA * (ratingA.presence - 2.5);
    const scoreB = impB * (ratingB.presence - 2.5);
    const absA = Math.abs(scoreA);
    const absB = Math.abs(scoreB);
    if (Math.abs(absB - absA) < 0.01) return scoreB - scoreA;
    return absB - absA;
  });

  const handleEdit = (displayIndex, newText) => {
    if (!editable || !onRequirementsChange) return;
    const actualIndex = sortedIndices[displayIndex];
    const oldSkill = (list[actualIndex] ?? "").trim();
    const nextReqs = list.slice();
    nextReqs[actualIndex] = newText;
    onRequirementsChange(nextReqs);

    if (onCompetencesChange && oldSkill && oldSkill in comp) {
      const rating = comp[oldSkill];
      const trimmed = (newText ?? "").trim();
      const next = { ...comp };
      delete next[oldSkill];
      if (trimmed) next[trimmed] = rating;
      onCompetencesChange(next);
    }
    if (onOverridesChange && overrides && oldSkill && oldSkill in overrides) {
      const o = overrides[oldSkill];
      const trimmed = (newText ?? "").trim();
      const next = { ...overrides };
      delete next[oldSkill];
      if (trimmed) next[trimmed] = o;
      onOverridesChange(next);
    }
  };

  const handleRemove = (displayIndex) => {
    if (!editable || !onRequirementsChange) return;
    const actualIndex = sortedIndices[displayIndex];
    const oldSkill = (list[actualIndex] ?? "").trim();
    const nextReqs = list.filter((_, i) => i !== actualIndex);
    onRequirementsChange(nextReqs);

    if (onCompetencesChange && oldSkill && oldSkill in comp) {
      const next = { ...comp };
      delete next[oldSkill];
      onCompetencesChange(next);
    }
    if (onOverridesChange && overrides && oldSkill && oldSkill in overrides) {
      const next = { ...overrides };
      delete next[oldSkill];
      onOverridesChange(next);
    }
  };

  const handleImportanceChange = (displayIndex, value) => {
    if (!onOverridesChange) return;
    const actualIndex = sortedIndices[displayIndex];
    const skill = (list[actualIndex] ?? "").trim();
    if (!skill) return;
    const next = { ...(overrides || {}) };
    next[skill] = { ...(next[skill] || {}), importance: value };
    onOverridesChange(next);
  };

  const handlePresenceChange = (displayIndex, value) => {
    if (!onOverridesChange) return;
    const actualIndex = sortedIndices[displayIndex];
    const skill = (list[actualIndex] ?? "").trim();
    if (!skill) return;
    const next = { ...(overrides || {}) };
    next[skill] = { ...(next[skill] || {}), presence: value };
    onOverridesChange(next);
  };

  const handleAdd = () => {
    if (!editable || !onRequirementsChange) return;
    onRequirementsChange([...list, ""]);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {sortedIndices.map((actualIndex, displayIndex) => {
        const skill = list[actualIndex];
        const text = texts[actualIndex];
        const rating = getRating(skill);
        const labels = getLabels(skill);
        return (
          <CompetenceLine
            key={actualIndex}
            text={text}
            presence={rating.presence}
            importance={rating.importance}
            needLabel={labels.needLabel}
            levelLabel={labels.levelLabel}
            editable={editable}
            onChange={(val) => handleEdit(displayIndex, val)}
            onRemove={editable ? () => handleRemove(displayIndex) : undefined}
            onImportanceChange={editable && onOverridesChange ? (v) => handleImportanceChange(displayIndex, v) : undefined}
            onPresenceChange={editable && onOverridesChange ? (v) => handlePresenceChange(displayIndex, v) : undefined}
          />
        );
      })}
      {editable && (
        <button
          type="button"
          onClick={handleAdd}
          style={{
            alignSelf: "flex-start",
            marginTop: 4,
            padding: "2px 8px",
            fontSize: 11,
            background: "var(--panel-bg)",
            color: "var(--text-color)",
            border: "1px dashed var(--border-color)",
            borderRadius: 2,
            cursor: "pointer",
          }}
        >
          + Add competence
        </button>
      )}
    </div>
  );
}
