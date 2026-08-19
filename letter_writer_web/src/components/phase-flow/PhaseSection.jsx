import React from "react";

export default function PhaseSection({
  title,
  children,
  collapsed,
  onToggle,
  onApproveAll,
  approveAllDisabled,
  showApproveAll,
  readyCount,
  totalCount,
  gridAutoColumns = "340px",
}) {
  const approveButtonText = readyCount !== undefined && totalCount !== undefined
    ? readyCount === totalCount && readyCount > 0
      ? "Approve all"
      : `Approve (${readyCount}/${totalCount})`
    : "Approve all";

  return (
    <details open={!collapsed} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: 8 }}>
      <summary
        style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", listStyle: "none" }}
        onClick={onToggle}
      >
        <h3 style={{ margin: 0 }}>{title}</h3>
        {showApproveAll && (
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onApproveAll?.();
            }}
            disabled={approveAllDisabled || readyCount === 0}
            style={{ fontSize: 12, padding: "4px 8px", opacity: (approveAllDisabled || readyCount === 0) ? 0.6 : 1 }}
          >
            {approveButtonText}
          </button>
        )}
      </summary>
      <div
        style={{
          display: "grid",
          gridAutoFlow: "column",
          gridAutoColumns,
          gap: 12,
          marginTop: 8,
          overflowX: "auto",
          alignItems: "start",
        }}
      >
        {children}
      </div>
    </details>
  );
}
