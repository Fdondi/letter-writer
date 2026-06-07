import React, { useState, useEffect, useCallback } from "react";
import { clearOAuthRedirectCooldown } from "../utils/googleOAuthRedirect";
import {
  AUTH_SESSION_RESTORED_EVENT,
  reportSessionExpired,
} from "../utils/authSession.js";

/**
 * Simple Google OAuth account button.
 * 
 * To use Google OAuth:
 * 1. Create OAuth 2.0 credentials in Google Cloud Console: https://console.cloud.google.com/apis/credentials
 * 2. Set authorized redirect URI to: http://localhost:8000/accounts/google/login/callback/ (development)
 * 3. For production, use your production domain
 * 4. Set environment variables:
 *    - GOOGLE_OAUTH_CLIENT_ID: Your OAuth client ID
 *    - GOOGLE_OAUTH_SECRET: Your OAuth client secret
 */
export default function AuthButton() {
  // This component is only rendered when user is authenticated (App.jsx checks auth first)
  // So we only need to fetch and display user info, not handle login
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(() => {
    setLoading(true);
    fetch("/api/auth/user/", {
      credentials: "include",
    })
      .then((res) => {
        if (res.status === 401) {
          reportSessionExpired();
          return null;
        }
        return res.json();
      })
      .then((data) => {
        if (data && data.user) {
          setUser(data.user);
        } else if (data && data.authenticated === false) {
          reportSessionExpired();
        }
        setLoading(false);
      })
      .catch((e) => {
        console.error("Failed to fetch user info:", e);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    loadUser();
    const onRestored = () => loadUser();
    window.addEventListener(AUTH_SESSION_RESTORED_EVENT, onRestored);
    return () => window.removeEventListener(AUTH_SESSION_RESTORED_EVENT, onRestored);
  }, [loadUser]);

  const handleLogout = async () => {
    console.log("Logout button clicked - starting logout...");
    try {
      const { fetchWithHeartbeat } = await import("../utils/apiHelpers.js");
      console.log("Calling /api/auth/logout/...");
      const result = await fetchWithHeartbeat("/api/auth/logout/", {
        method: "POST",
      });
      console.log("Logout response:", result);
      clearOAuthRedirectCooldown();
      window.location.reload();
    } catch (e) {
      console.error("Failed to logout:", e);
      alert("Failed to logout: " + (e.message || e));
      // Even on error, reload - App.jsx will handle the state
      window.location.reload();
    }
  };

  if (loading) {
    return (
      <div style={{ padding: "8px 16px", fontSize: "14px", color: "#666" }}>
        Loading...
      </div>
    );
  }

  // Only render if user is available (should always be true if this component is rendered)
  if (!user) {
    // This shouldn't happen, but if it does, don't render anything
    // (App.jsx should have redirected already)
    return null;
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "8px 16px" }}>
      <div style={{ fontSize: "14px", color: "#333" }}>
        <strong>{user.name || user.email}</strong>
        {user.provider && (
          <span style={{ fontSize: "12px", color: "#666", marginLeft: "8px" }}>
            ({user.provider})
          </span>
        )}
      </div>
      <button
        onClick={handleLogout}
        style={{
          padding: "6px 12px",
          fontSize: "12px",
          backgroundColor: "#f44336",
          color: "white",
          border: "none",
          borderRadius: "4px",
          cursor: "pointer",
        }}
      >
        Logout
      </button>
    </div>
  );
}
