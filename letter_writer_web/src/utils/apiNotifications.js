import { handleUnauthorizedResponse } from "./authSession.js";

// Lightweight global fetch hook that increments a counter only for
// extraction and phase card completions (not heartbeats or other API calls).
// It is safe to call multiple times; only the first call installs the hook.

let completedCount = 0;
let originalTitle = typeof document !== "undefined" ? document.title : "";
let requestedPermission = false;

const formatUrl = (input) => {
  if (typeof input === "string") return input;
  if (input && typeof input === "object" && input.url) return input.url;
  return "API call";
};

/**
 * Check if this URL should trigger a notification.
 * Only count:
 * - Extractions: /api/extract/
 * - Phase cards: /api/phases/{plan|draft|refine}/<vendor>/
 * Exclude silent session bookkeeping (/session/, /init/, /state/, backups) and agentic
 * (agentic completion is notified separately when ongoing becomes false in App).
 */
const shouldNotify = (url) => {
  if (typeof url !== "string") return false;
  if (url.includes("/api/phases/agentic")) return false;

  if (url.includes("/api/extract/")) {
    return true;
  }

  // Phase card completions only — not session metadata syncs (those spam "Session started").
  if (/\/api\/phases\/(plan|draft|refine)\/[^/]+\//.test(url)) {
    return true;
  }

  return false;
};

export { shouldNotify };

const updateTitleBadge = () => {
  if (typeof document === "undefined") return;
  document.title =
    completedCount > 0 ? `(${completedCount}) Letter Writer` : originalTitle;
};

const formatNotificationMessage = (url, status) => {
  // Check if status indicates success (numeric 200-299) or failure (anything else including "error" string)
  const isSuccess = typeof status === "number" && status >= 200 && status < 300;

  if (typeof status === "number" && status == 401) {
    return "Authentication required";
  }

  if (typeof status === "number" && status == 403) {
    return "Authorization required";
  }

  if (typeof status === "number" && status == 404) {
    return "Not found";
  }
  
  // Extract endpoint
  if (url.includes("/api/extract/")) {
    return isSuccess ? "Extraction completed" : "Extraction failed";
  }
  
  // Phase cards - extract phase name and vendor name
  const phaseMatch = url.match(/\/api\/phases\/(draft|refine|plan)\/([^/]+)\//);
  if (phaseMatch) {
    const phaseName = phaseMatch[1];
    const vendor = phaseMatch[2];
    return isSuccess ? `${phaseName}/${vendor} completed` : `${phaseName}/${vendor} failed`;
  }

  // Default fallback (shouldNotify already filters; keep for safety)
  return isSuccess ? "Completed" : "Failed";
};

const doNotify = (message) => {
  if (typeof window === "undefined" || typeof Notification === "undefined") return;
  try {
    new Notification(message, { tag: "api-call" });
  } catch {
    // Ignore Notification errors (e.g., blocked by browser)
  }
};

const tryNotify = (url, status) => {
  if (typeof window === "undefined" || typeof Notification === "undefined") {
    return;
  }

  const notify = () => {
    const message = formatNotificationMessage(url, status);
    doNotify(message);
  };

  // Already allowed: fire immediately
  if (Notification.permission === "granted") {
    notify();
    return;
  }

  // Ask once, then proceed next time if granted
  if (Notification.permission === "default" && !requestedPermission) {
    requestedPermission = true;
    Notification.requestPermission().then((perm) => {
      if (perm === "granted") {
        notify();
      }
    });
  }
};

/** Show a one-off notification (e.g. agentic feedback completed). Uses same permission as API notifications. */
export function showNotification(message) {
  if (typeof window === "undefined" || typeof Notification === "undefined") return;
  if (Notification.permission === "granted") {
    doNotify(message);
  }
}

const bumpCounters = (url, status) => {
  // Only count specific endpoints (extractions and phase cards)
  if (!shouldNotify(url)) {
    return;
  }
  
  // Skip heartbeats (202 status) - these are "still processing" responses
  if (status === 202) {
    return;
  }
  
  // Notify for both success and failure
  const isSuccess = typeof status === "number" && status >= 200 && status < 300;
  if (isSuccess) {
    completedCount += 1;
    updateTitleBadge();
  }
  tryNotify(url, status);
};

export function setupApiNotifications() {
  if (typeof window === "undefined" || typeof window.fetch !== "function") {
    return;
  }
  if (window.fetch.__withNotifications) {
    return; // Already wrapped
  }

  const originalFetch = window.fetch.bind(window);

  const wrappedFetch = async (...args) => {
    const url = formatUrl(args[0]);
    try {
      const res = await originalFetch(...args);
      handleUnauthorizedResponse(res);
      bumpCounters(url, res.status);
      return res;
    } catch (err) {
      bumpCounters(url, "error");
      throw err;
    }
  };

  wrappedFetch.__withNotifications = true;
  window.fetch = wrappedFetch;
}
