import React from "react";

function formatWeakness(it) {
  const req = String(it?.requirement || "").trim();
  const gap = String(it?.gap || "").trim();
  if (req && gap) return { title: req, body: gap };
  if (req) return { title: null, body: req };
  if (gap) return { title: null, body: gap };
  return null;
}

/**
 * Collapsed, non-blocking list of objective gaps the applicant cannot fix.
 */
export function KnownWeaknessesPanel({ items }) {
  const rows = Array.isArray(items)
    ? items.map(formatWeakness).filter(Boolean)
    : [];
  if (rows.length === 0) return null;

  return (
    <details
      style={{
        marginTop: 12,
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        padding: "10px 12px",
        background: "#fafafa",
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
        Known weaknesses ({rows.length}) — cannot be fixed; no approval needed
      </summary>
      <p style={{ fontSize: 12, color: "#9ca3af", margin: "8px 0 10px" }}>
        Objective requirement gaps you are already aware of. Feedback will not ask you to obtain missing credentials,
        but will still flag dishonest framing (e.g. calling B2 "fluent").
      </p>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.map((row, idx) => (
          <li
            key={items[idx]?.id || idx}
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 6,
              padding: 8,
              background: "#fff",
              fontSize: 13,
              color: "#4b5563",
            }}
          >
            {row.title ? (
              <>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>{row.title}</div>
                <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{row.body}</div>
              </>
            ) : (
              <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{row.body}</div>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
