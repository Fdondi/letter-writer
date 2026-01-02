// Lightweight global fetch hook that increments a counter on every
// API response and optionally shows a desktop notification.
// It is safe to call multiple times; only the first call installs the hook.

let completedCount = 0;
let originalTitle = typeof document !== "undefined" ? document.title : "";
let requestedPermission = false;

const formatUrl = (input) => {
  if (typeof input === "string") return input;
  if (input && typeof input === "object" && input.url) return input.url;
  return "API call";
};

const updateTitleBadge = () => {
  if (typeof document === "undefined") return;
  document.title =
    completedCount > 0 ? `(${completedCount}) Letter Writer` : originalTitle;
};

const tryNotify = (url, status) => {
  if (typeof window === "undefined" || typeof Notification === "undefined") {
    return;
  }

  const notify = () => {
    try {
      new Notification("API call finished", {
        body: `${url} (${status})`,
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
  completedCount += 1;
  updateTitleBadge();
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
