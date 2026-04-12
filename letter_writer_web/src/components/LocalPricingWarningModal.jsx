import React from "react";

const STORAGE_KEY = "letterWriterDismissLocalPricingWarning";

export function isLocalPricingWarningDismissed() {
  try {
    return sessionStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function dismissLocalPricingWarningForSession() {
  try {
    sessionStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* ignore */
  }
}

/**
 * Shown when enabling the local vendor without LOCAL_GPU_WATTS_AT_100 / LOCAL_ENERGY_PRICE_PER_KWH on the server.
 */
export default function LocalPricingWarningModal({
  isOpen,
  onContinue,
  onCancel,
  dismissChecked,
  onDismissCheckedChange,
}) {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="local-pricing-warning-title"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 10000,
        backgroundColor: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        style={{
          maxWidth: 440,
          width: "100%",
          padding: 20,
          borderRadius: 8,
          backgroundColor: "var(--card-bg, #fff)",
          border: "1px solid var(--border-color, #ccc)",
          color: "var(--text-color, #111)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 id="local-pricing-warning-title" style={{ marginTop: 0, marginBottom: 12, fontSize: 18 }}>
          Local model cost not configured
        </h3>
        <p style={{ margin: "0 0 12px 0", fontSize: 14, lineHeight: 1.5 }}>
          Local runs are priced from <strong>inference time</strong>, your GPU&apos;s power draw at{" "}
          <strong>100% load</strong> (watts), and your <strong>local electricity price</strong> per kWh. Set{" "}
          <code style={{ fontSize: 13 }}>LOCAL_GPU_WATTS_AT_100</code> and{" "}
          <code style={{ fontSize: 13 }}>LOCAL_ENERGY_PRICE_PER_KWH</code> in the server environment (see README).
        </p>
        <p style={{ margin: "0 0 16px 0", fontSize: 14, lineHeight: 1.5, color: "var(--secondary-text-color, #555)" }}>
          Until then, usage is still tracked, but <strong>reported cost stays $0</strong>.
        </p>
        <label
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            cursor: "pointer",
            fontSize: 14,
            marginBottom: 16,
          }}
        >
          <input
            type="checkbox"
            checked={dismissChecked}
            onChange={(e) => onDismissCheckedChange(e.target.checked)}
            style={{ marginTop: 2 }}
          />
          <span>Don&apos;t show this again this browser session</span>
        </label>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button
            type="button"
            onClick={onCancel}
            style={{
              padding: "8px 16px",
              borderRadius: 4,
              border: "1px solid var(--border-color)",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onContinue}
            style={{
              padding: "8px 16px",
              borderRadius: 4,
              border: "none",
              backgroundColor: "#3b82f6",
              color: "white",
              cursor: "pointer",
              fontSize: 14,
            }}
          >
            Enable local anyway
          </button>
        </div>
      </div>
    </div>
  );
}
