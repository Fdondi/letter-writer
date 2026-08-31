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
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 8,
        flex: collapsed ? "0 0 auto" : "1 1 0",
        minHeight: collapsed ? undefined : 0,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        boxSizing: "border-box",
      }}
    >
      <div
        role="button"
        tabIndex={0}
        aria-expanded={!collapsed}
        style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", flexShrink: 0 }}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle?.();
          }
        }}
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
      </div>
      {!collapsed && (
        <div
          style={{
            display: "grid",
            gridAutoFlow: "column",
            gridAutoColumns,
            gap: 12,
            marginTop: 8,
            overflowX: "auto",
            alignItems: "stretch",
            flex: 1,
            minHeight: 0,
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}
