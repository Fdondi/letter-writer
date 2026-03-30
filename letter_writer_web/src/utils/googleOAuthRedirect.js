/**
 * Single-flight navigation to Google OAuth.
 *
 * In-memory flag: duplicate calls in the same JS load (e.g. StrictMode-like double effects).
 * localStorage timestamp: extra guard for multiple top-level loads or tabs within BURST_MS.
 */

const LS_BURST_KEY = "letter_writer_oauth_burst_ts";
const BURST_MS = 5000;

let googleOAuthRedirectScheduled = false;

export function clearOAuthRedirectCooldown() {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(LS_BURST_KEY);
  } catch (_) {
    /* private mode / denied */
  }
}

/**
 * Store current location for post-login return. Skips /login (LoginPage sets ?return=…)
 * and Google paths.
 */
export function rememberReturnUrlForOAuth() {
  if (typeof window === "undefined") return;
  const path = window.location.pathname + window.location.search;
  if (!path || path.startsWith("/accounts/google")) return;
  if (path.startsWith("/login")) return;
  sessionStorage.setItem("authReturnUrl", path);
}

export function scheduleGoogleOAuthRedirect() {
  if (typeof window === "undefined") return false;

  const now = Date.now();
  let lastBurst = 0;
  try {
    lastBurst = parseInt(localStorage.getItem(LS_BURST_KEY) || "0", 10) || 0;
  } catch (_) {
    lastBurst = 0;
  }
  if (now - lastBurst < BURST_MS) {
    return false;
  }
  if (googleOAuthRedirectScheduled) {
    return false;
  }
  googleOAuthRedirectScheduled = true;
  try {
    localStorage.setItem(LS_BURST_KEY, String(now));
  } catch (_) {
    /* still proceed */
  }
  rememberReturnUrlForOAuth();
  window.location.assign("/accounts/google/login");
  return true;
}
