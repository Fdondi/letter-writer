import React from "react";

/**
 * Single competence line: Importance stars + CV fit stars + text, all on one line.
 * Tooltip shows the text label (e.g. "Senior professional", "critical"); stars show the number.
 * 
 * Props:
 * - text, presence, importance, editable, onChange, onRemove
 * - needLabel: string (e.g. "critical") for tooltip
 * - levelLabel: string (e.g. "Senior professional") for tooltip
 */
export default function CompetenceLine({
  text,
  presence = null,
  importance = null,
  needLabel = null,
  levelLabel = null,
  editable = false,
  onChange,
  onRemove,
}) {
  // Calculate color based on presence (green/red) and importance (intensity)
  const getBackgroundColor = () => {
    if (presence == null || importance == null) return "transparent";
    
    const presenceNorm = (presence - 1) / 4;
    const importanceNorm = (importance - 1) / 4;
    
    const red = Math.max(0, Math.min(255, Math.round(255 * (1 - presenceNorm))));
    const green = Math.max(0, Math.min(255, Math.round(255 * presenceNorm)));
    const blue = Math.max(0, Math.min(255, Math.round(255 * 0.2 * Math.min(presenceNorm, 1 - presenceNorm))));
    const alpha = 0.08 + importanceNorm * 0.22;
    
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  };

  const Stars = ({ rating, title: tooltip }) => {
    if (rating == null || rating < 1 || rating > 5) return null;
    return (
      <span
        style={{ flexShrink: 0, fontSize: 10, lineHeight: 1, width: 52 }}
        title={tooltip ?? undefined}
        aria-hidden
      >
        {"★".repeat(rating)}
        {"☆".repeat(5 - rating)}
      </span>
    );
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        marginBottom: 2,
        position: "relative",
        padding: "2px 6px",
        paddingRight: editable && onRemove ? 24 : 6,
        borderRadius: 3,
        backgroundColor: getBackgroundColor(),
        minHeight: 24,
      }}
    >
      {editable && onRemove && (
        <button
          type="button"
          onClick={onRemove}
          title="Remove"
          aria-label="Remove"
          style={{
            position: "absolute",
            top: 2,
            right: 2,
            width: 18,
            height: 18,
            padding: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
            lineHeight: 1,
            background: "transparent",
            color: "#dc2626",
            border: "none",
            cursor: "pointer",
            zIndex: 1,
          }}
        >
          ✕
        </button>
      )}
      <Stars rating={importance} title={needLabel} />
      <Stars rating={presence} title={levelLabel} />
      {editable ? (
        <input
          type="text"
          value={text ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Competence or requirement"
          style={{
            flex: 1,
            minWidth: 0,
            padding: "2px 6px",
            fontSize: 12,
            background: "var(--input-bg)",
            color: "var(--text-color)",
            border: "1px solid var(--border-color)",
            borderRadius: 2,
          }}
        />
      ) : (
        <span style={{ flex: 1, fontSize: 12, color: "var(--text-color)", paddingRight: 4, minWidth: 0 }}>
          {text ?? ""}
        </span>
      )}
    </div>
  );
}
