import React, { useState, useEffect } from "react";

export default function LoginPage() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authAvailable, setAuthAvailable] = useState(false);

  useEffect(() => {
    async function checkAuthStatus() {
      try {
        const response = await fetch("/api/auth/status/", { credentials: "include" });
        const data = await response.json();
        setAuthAvailable(data.auth_available);
        if (data.authenticated) {
          setUser(data.user);
          
          // Force logout if we think we should be logged out? No, we can't know that easily.
          // But if the user is authenticated, we should redirect them to the app.
          // The problem is if the user clicked logout, got redirected here, and is STILL authenticated.
          
          const params = new URLSearchParams(window.location.search);
          const returnUrl = params.get("return") || sessionStorage.getItem("authReturnUrl") || "/";
          sessionStorage.removeItem("authReturnUrl");
          
          // If return URL is /login, go to root instead to avoid loop
          const target = (returnUrl === "/login" || returnUrl.includes("/login")) ? "/" : returnUrl;
          window.location.href = target;
          return;
        } else {
          // If NOT authenticated, ensure user is null
          setUser(null);
        }
      } catch (e) {
        console.error("Failed to check auth status:", e);
      } finally {
        setLoading(false);
      }
    }
    checkAuthStatus();
  }, []);

  const handleLogin = () => {
    if (!authAvailable) {
      alert(
        "Google OAuth is not available.\n\n" +
        "Required setup:\n" +
        "1. Install django-allauth: pip install django-allauth>=0.57.0\n" +
        "2. Rebuild Docker image: docker-compose build backend\n" +
        "3. Run migrations: docker-compose exec backend python manage.py migrate\n" +
        "4. Set OAuth credentials in .env: GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_SECRET\n" +
        "5. Configure Site domain in Django admin or shell"
      );
      return;
    }
    // Store return URL in session storage before redirecting to OAuth
    // This preserves it across the OAuth redirect flow
    const params = new URLSearchParams(window.location.search);
    const returnUrl = params.get("return") || "/";
    if (returnUrl && returnUrl !== "/login") {
      sessionStorage.setItem("authReturnUrl", returnUrl);
    }
    // Redirect to Google OAuth login
    window.location.href = "/accounts/google/login";
  };

  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          minHeight: "100vh",
          backgroundColor: "var(--bg-color)",
          color: "var(--text-color)",
        }}
      >
        <div>Checking authentication...</div>
      </div>
    );
  }

  if (user) {
    // Redirecting...
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          minHeight: "100vh",
          backgroundColor: "var(--bg-color)",
          color: "var(--text-color)",
        }}
      >
        <div>Redirecting...</div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "100vh",
        backgroundColor: "var(--bg-color)",
        color: "var(--text-color)",
        padding: "20px",
      }}
    >
      <div
        style={{
          maxWidth: "400px",
          width: "100%",
          padding: "40px",
          backgroundColor: "var(--panel-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: "8px",
          boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
        }}
      >
        <h1 style={{ marginTop: 0, marginBottom: "10px", fontSize: "24px", fontWeight: 600 }}>
          Letter Writer
        </h1>
        <p style={{ marginBottom: "30px", color: "var(--text-color)", opacity: 0.8 }}>
          Sign in to continue
        </p>
        
        {!authAvailable && (
          <div
            style={{
              padding: "12px",
              marginBottom: "20px",
              backgroundColor: "var(--warning-bg)",
              border: "1px solid var(--warning-border)",
              borderRadius: "4px",
              color: "var(--text-color)",
              fontSize: "14px",
            }}
          >
            Google OAuth is not configured. Please set up authentication first.
          </div>
        )}

        <button
          onClick={handleLogin}
          disabled={!authAvailable}
          style={{
            width: "100%",
            padding: "12px 24px",
            fontSize: "16px",
            fontWeight: 600,
            backgroundColor: authAvailable ? "#4285f4" : "var(--header-bg)",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: authAvailable ? "pointer" : "not-allowed",
            transition: "background-color 0.2s",
          }}
          onMouseOver={(e) => {
            if (authAvailable) {
              e.target.style.backgroundColor = "#357ae8";
            }
          }}
          onMouseOut={(e) => {
            if (authAvailable) {
              e.target.style.backgroundColor = "#4285f4";
            }
          }}
        >
          {authAvailable ? "Sign in with Google" : "OAuth Not Available"}
        </button>
      </div>
    </div>
  );
}
