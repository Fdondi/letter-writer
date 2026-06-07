/**
 * Session expiry detection and re-authentication without tearing down the SPA.
 */

import { clearOAuthRedirectCooldown, rememberReturnUrlForOAuth } from "./googleOAuthRedirect.js";

export const AUTH_SESSION_EXPIRED_EVENT = "letter-writer-auth-session-expired";
export const AUTH_SESSION_RESTORED_EVENT = "letter-writer-auth-session-restored";

const AUTH_STATUS_URL = "/api/auth/status/";
const GOOGLE_LOGIN_PATH = "/accounts/google/login";
const POPUP_POLL_MS = 1200;
const POPUP_TIMEOUT_MS = 5 * 60 * 1000;

let sessionExpiredReported = false;
let reauthInProgress = false;
let initialAuthCheckComplete = false;
let hadAuthenticatedSession = false;

/** Called once after App finishes the mount-time /api/auth/status/ check. */
export function markInitialAuthCheckComplete(authenticated) {
  initialAuthCheckComplete = true;
  if (authenticated) {
    hadAuthenticatedSession = true;
  }
}

export function resetAuthSessionTracking() {
  initialAuthCheckComplete = false;
  hadAuthenticatedSession = false;
  sessionExpiredReported = false;
}

export function isSessionExpiredReported() {
  return sessionExpiredReported;
}

export function reportSessionExpired() {
  if (typeof window === "undefined") return;
  if (!initialAuthCheckComplete || !hadAuthenticatedSession) return;
  if (sessionExpiredReported) return;
  sessionExpiredReported = true;
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_EXPIRED_EVENT));
}

export function clearSessionExpiredReport() {
  sessionExpiredReported = false;
}

export function notifySessionRestored() {
  if (typeof window === "undefined") return;
  clearSessionExpiredReport();
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_RESTORED_EVENT));
}

/**
 * @returns {Promise<{ authenticated: boolean, user?: object, auth_available?: boolean }>}
 */
export async function fetchAuthStatus() {
  const res = await fetch(AUTH_STATUS_URL, { credentials: "include" });
  if (!res.ok) {
    return { authenticated: false };
  }
  return res.json();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Open Google OAuth in a popup and poll until the session cookie is valid again.
 * Falls back to full-page redirect if the popup is blocked.
 *
 * @returns {Promise<"popup" | "redirect">}
 */
export async function reauthenticateWithGoogle() {
  if (typeof window === "undefined") {
    throw new Error("Re-authentication is only available in the browser");
  }
  if (reauthInProgress) {
    return "popup";
  }
  reauthInProgress = true;
  rememberReturnUrlForOAuth();

  try {
    const popup = window.open(
      GOOGLE_LOGIN_PATH,
      "letter_writer_google_oauth",
      "width=520,height=640,menubar=no,toolbar=no,location=yes,status=no"
    );

    if (!popup) {
      window.location.assign(GOGLE_LOGIN_PATH);
      return "redirect";
    }

    const started = Date.now();
    while (Date.now() - started < POPUP_TIMEOUT_MS) {
      if (popup.closed) {
        const status = await fetchAuthStatus();
        if (status.authenticated) {
          clearOAuthRedirectCooldown();
          notifySessionRestored();
          return "popup";
        }
        throw new Error("Sign-in window closed before authentication completed");
      }

      const status = await fetchAuthStatus();
      if (status.authenticated) {
        try {
          popup.close();
        } catch {
          /* ignore */
        }
        clearOAuthRedirectCooldown();
        notifySessionRestored();
        return "popup";
      }

      await sleep(POPUP_POLL_MS);
    }

    try {
      popup.close();
    } catch {
      /* ignore */
    }
    throw new Error("Sign-in timed out. Try again.");
  } finally {
    reauthInProgress = false;
  }
}

/**
 * Call when any fetch returns 401 (including raw fetch not using fetchWithHeartbeat).
 */
export function handleUnauthorizedResponse(response) {
  if (response && response.status === 401) {
    reportSessionExpired();
  }
}
