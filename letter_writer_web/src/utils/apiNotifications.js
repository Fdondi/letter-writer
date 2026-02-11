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
 * - Phase cards: /api/phases/draft/<vendor>/ and /api/phases/refine/<vendor>/
 */
const shouldNotify = (url) => {
  if (typeof url !== "string") return false;
  
  // Extract endpoint
  if (url.includes("/api/extract/")) {
    return true;
  }
  
  // Phase cards (draft and refine phases)
  if (url.includes("/api/phases")) {
    return true;
  }
  
  return false;
};

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
  
  // Init endpoint
  if (url.includes("/api/phases/init/")) {
    return isSuccess ? "init succeeded" : "init failed";
  }
  
  // Phase cards - extract phase name and vendor name
  const phaseMatch = url.match(/\/api\/phases\/(draft|refine)\/([^/]+)\//);
  if (phaseMatch) {
    const phaseName = phaseMatch[1];
    const vendor = phaseMatch[2];
    return isSuccess ? `${phaseName}/${vendor} completed` : `${phaseName}/${vendor} failed`;
  }
  
  // Fallback for other phase endpoints
  if (url.includes("/api/phases/session")) {
    return isSuccess ? "Session started" : "Session start failed";
  }
  
  // Default fallback
  return isSuccess ? "Completed" : "Failed";
};

const tryNotify = (url, status) => {
  if (typeof window === "undefined" || typeof Notification === "undefined") {
    return;
  }

  const notify = () => {
    try {
      const message = formatNotificationMessage(url, status);
      new Notification(message, {
        tag: "api-call",
      });
    } catch {
      // Ignore Notification errors (e.g., blocked by browser)
    }
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
