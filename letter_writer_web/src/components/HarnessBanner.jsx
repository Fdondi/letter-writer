import React, { useEffect, useState } from "react";

/**
 * Persistent notice when the SPA is talking to HARNESS_MODE.
 * Hidden unless /api/harness/info/ reports synthetic mode.
 */
export default function HarnessBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/harness/info/", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled) return;
        if (data && data.mode === true && data.synthetic === true) {
          setVisible(true);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!visible) return null;

  return (
    <div
      data-testid="harness-banner"
      role="status"
      style={{
        marginBottom: 12,
        padding: "8px 12px",
        backgroundColor: "#fef3c7",
        border: "1px solid #f59e0b",
        borderRadius: 6,
        color: "#92400e",
        fontSize: 13,
        flexShrink: 0,
      }}
    >
      Harness · synthetic data · LLM disabled
    </div>
  );
}
