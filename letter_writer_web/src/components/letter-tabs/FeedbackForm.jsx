import React from "react";

export default function FeedbackForm({ rating, comment, onChange }) {
  return (
    <div style={{ marginTop: 8, padding: "8px", borderTop: "1px solid var(--border-color)", background: "var(--panel-bg)" }}>
      <div style={{ marginBottom: 4, display: "flex", gap: 4, alignItems: "center" }}>
        <span style={{ fontSize: "12px", fontWeight: 600 }}>Rating:</span>
        <div style={{ display: "flex" }}>
          {[1, 2, 3, 4, 5].map((star) => (
            <span
              key={star}
              onClick={() => onChange({ rating: star, comment })}
              style={{
                cursor: "pointer",
                fontSize: "16px",
                color: star <= (rating || 0) ? "#f59e0b" : "var(--border-color)",
                transition: "color 0.1s",
              }}
              title={`${star} stars`}
            >
              ★
            </span>
          ))}
        </div>
      </div>
      <textarea
        value={comment || ""}
        onChange={(e) => onChange({ rating, comment: e.target.value })}
        placeholder="Feedback on this vendor's output..."
        style={{
          width: "100%",
          padding: "6px",
          fontSize: "12px",
          border: "1px solid var(--border-color)",
          borderRadius: "4px",
          minHeight: "50px",
          resize: "vertical",
          background: "var(--input-bg)",
          color: "var(--text-color)",
          fontFamily: "inherit",
          boxSizing: "border-box",
        }}
      />
    </div>
  );
}
