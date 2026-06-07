import React, { useState } from "react";
import { reauthenticateWithGoogle } from "../utils/authSession.js";

/**
 * Blocks interaction until the user re-authenticates. The app stays mounted underneath
 * so in-memory form state is preserved.
 */
export default function SessionExpiredModal({ isOpen }) {
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleSignIn = async () => {
    setSigningIn(true);
    setError(null);
    try {
      const mode = await reauthenticateWithGoogle();
      if (mode === "redirect") {
        return;
      }
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setSigningIn(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-expired-title"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 20000,
        backgroundColor: "rgba(0,0,0,0.5)",
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
          padding: 24,
          borderRadius: 8,
          backgroundColor: "var(--panel-bg, #fff)",
          border: "1px solid var(--border-color, #ccc)",
          color: "var(--text-color, #111)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.25)",
          textAlign: "center",
        }}
      >
        <h2 id="session-expired-title" style={{ marginTop: 0, marginBottom: 12, fontSize: 20 }}>
          Session expired
        </h2>
        <p style={{ margin: "0 0 20px 0", fontSize: 14, lineHeight: 1.5, opacity: 0.9 }}>
          Your sign-in timed out. Sign in again to continue. Your current work on this page is kept.
        </p>
        {error && (
          <p
            role="alert"
            style={{
              margin: "0 0 16px 0",
              fontSize: 13,
              color: "var(--error-color, #b00020)",
            }}
          >
            {error}
          </p>
        )}
        <button
          type="button"
          disabled={signingIn}
          onClick={handleSignIn}
          style={{
            width: "100%",
            padding: "12px 24px",
            fontSize: 16,
            fontWeight: 600,
            backgroundColor: signingIn ? "#9aa0a6" : "#4285f4",
            color: "white",
            border: "none",
            borderRadius: 4,
            cursor: signingIn ? "wait" : "pointer",
          }}
        >
          {signingIn ? "Waiting for Google sign-in…" : "Sign in with Google"}
        </button>
      </div>
    </div>
  );
}
