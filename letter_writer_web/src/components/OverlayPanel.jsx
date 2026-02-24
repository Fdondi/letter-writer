import React from "react";

/**
 * Overlay panel that floats over the main flow.
 * AI Instructions, CV, Previous Examples, Settings, and Costs use this pattern:
 * they are overlays, not pages. Closing returns to where the user was.
 *
 * NOTE: Keep AI Instructions, CV, Previous Examples, and Settings as overlays.
 * Compose / Agentic flow / Vendor flow are the main flow, not navigable destinations.
 */
export default function OverlayPanel({ title, isOpen, onClose, children }) {
  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0,0,0,0.3)",
          zIndex: 999,
        }}
        aria-hidden="true"
      />
      {/* Panel - 90% viewport */}
      <div
        style={{
          position: "fixed",
          top: "5%",
          left: "5%",
          right: "5%",
          bottom: "5%",
          width: "90%",
          height: "90%",
          maxWidth: "none",
          backgroundColor: "var(--bg-color)",
          boxShadow: "0 4px 24px rgba(0,0,0,0.2)",
          borderRadius: "8px",
          zIndex: 1000,
          display: "flex",
          flexDirection: "column",
          border: "1px solid var(--border-color)",
          color: "var(--text-color)",
          overflow: "hidden",
        }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="overlay-panel-title"
      >
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border-color)",
            backgroundColor: "var(--header-bg)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexShrink: 0,
          }}
        >
          <h2 id="overlay-panel-title" style={{ margin: 0, fontSize: "1.25em", color: "var(--text-color)" }}>
            {title}
          </h2>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              fontSize: "1.5em",
              cursor: "pointer",
              color: "var(--secondary-text-color)",
              padding: "4px 8px",
              lineHeight: 1,
            }}
            aria-label="Close"
          >
            &times;
          </button>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: 20 }}>
          {children}
        </div>
      </div>
    </>
  );
}
