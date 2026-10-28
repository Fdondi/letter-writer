// Chrome runs this as a service worker; Firefox loads the modules first via manifest "scripts".
if (typeof importScripts === "function" && typeof LW_PENDING === "undefined") {
  importScripts("pending.js", "pipeline.js", "firestore.js");
}

const DEFAULT_ORIGIN = "https://localhost:8443";
const MAX_TEXT_CHARS = 200000;
const MAX_HTML_CHARS = 800000;
const INGEST_TIMEOUT_MS = 8000;

// Browsers without the extension sign-in API (Firefox for Android) cannot write to Firestore
// themselves: the page is handed to the Letter Writer app over a custom URL scheme and the app
// queues the job (it is signed in and writes Firestore like the phone share flow does).
const APP_HANDOFF_URL = "letterwriter://capture";
// Encoded-text budget for the handoff URL; a bigger posting is left out and the app downloads
// the page itself (JobPageFetcher) instead of queueing truncated text.
const HANDOFF_TEXT_BUDGET = 100000;

const api = typeof browser !== "undefined" ? browser : chrome;

function truncate(value, max) {
  const text = value == null ? "" : String(value);
  return text.length > max ? text.slice(0, max) : text;
}

function capturePage() {
  return {
    url: location.href,
    title: document.title || "",
    text: document.body ? document.body.innerText || "" : "",
    html: document.documentElement ? document.documentElement.outerHTML || "" : "",
  };
}

async function getOrigin() {
  const stored = await api.storage.local.get({
    appOrigin: DEFAULT_ORIGIN,
    appOriginExplicit: false,
  });
  if (!stored.appOriginExplicit) {
    return DEFAULT_ORIGIN;
  }
  const origin = String(stored.appOrigin || DEFAULT_ORIGIN).trim().replace(/\/+$/, "");
  return origin || DEFAULT_ORIGIN;
}

// Queue captured pages as pipeline jobs (drafted by the desktop batch), like the phone app.
// On browsers without the sign-in API (Firefox for Android) the queue path is the only one that
// works — it hands the page to the app — so the toggle is ignored there.
async function getQueueJobs() {
  if (!firestoreAuth().available()) return true;
  const stored = await api.storage.local.get({ queueJobs: true });
  return stored.queueJobs !== false;
}

function firestoreAuth() {
  return LW_FIRESTORE.createAuth({ api });
}

/** `letterwriter://capture?url=…&text=…` — the text only when it fits (the app fetches otherwise). */
function appHandoffUrl(page) {
  const params = new URLSearchParams();
  if (page.url) params.set("url", page.url);
  const text = page.text || "";
  if (text && encodeURIComponent(text).length <= HANDOFF_TEXT_BUDGET) params.set("text", text);
  return `${APP_HANDOFF_URL}?${params.toString()}`;
}

async function handoffToApp(page, tabId) {
  await api.tabs.create({ url: appHandoffUrl(page) });
  await setBadge("→", "Letter Writer: handed to the Letter Writer app — it queues the job", tabId);
}

// Queue a captured page straight into Firestore (pipeline.js + firestore.js): no local server
// involved. Returns {opportunity_id, opportunity_status, message}, or {fallback: true} when the
// browser has no extension sign-in API (the caller then queues through the app server), or
// {skipped: true} when not signed in and interactive sign-in is not allowed, or {error}.
async function queueDirectly(page, { interactive = true } = {}) {
  const auth = firestoreAuth();
  if (!auth.available()) return { fallback: true };
  if (!(await auth.getIdToken())) {
    if (!interactive) return { skipped: true };
    try {
      await auth.signIn(true);
    } catch (e) {
      return { error: `Sign in with Google to queue jobs directly (extension Options): ${e.message}` };
    }
  }
  const { userId } = await auth.status();
  if (!userId) return { error: "Sign-in did not return a user id." };
  const client = LW_FIRESTORE.createClient({ getIdToken: () => auth.getIdToken() });
  try {
    return await LW_PIPELINE.queueCapture(client, {
      userId,
      url: page.url,
      title: page.title,
      text: page.text,
      html: page.html,
      via: "extension",
    });
  } catch (e) {
    return { error: (e && e.message) || String(e) };
  }
}

async function ensureOriginPermission(origin) {
  if (typeof api.permissions?.request !== "function") return;
  try {
    await api.permissions.request({ origins: [`${origin}/*`] });
  } catch (e) {
    console.warn("Host permission request failed:", e);
  }
}

function describeFetchError(err, origin) {
  const msg = String((err && err.message) || err || "ingest failed");
  if (/NetworkError|Failed to fetch|Load failed|Network request failed|abort/i.test(msg)) {
    return `Could not reach ${origin} (${msg}). Is Letter Writer running there?`;
  }
  return msg;
}

async function ingestAtOrigin(origin, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), INGEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${origin}/api/job-capture/ingest/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      // The signed-in session cookie tells the backend whose job a queued capture is.
      credentials: "include",
      signal: controller.signal,
    });
    const ingest = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = ingest.detail || response.statusText || `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (!ingest.capture_id && !ingest.opportunity_id) {
      throw new Error("ingest returned no id");
    }
    return ingest;
  } finally {
    clearTimeout(timer);
  }
}

async function setBadge(text, title, tabId = undefined) {
  try {
    const target = tabId === undefined ? {} : { tabId };
    await api.action.setBadgeText({ ...target, text: text || "" });
    if (title) await api.action.setTitle({ ...target, title });
  } catch (e) {
    console.warn("Badge update failed:", e);
  }
}

async function ingestAndOpen(tab) {
  if (!tab || !tab.id) {
    await setBadge("!", "Letter Writer: no active tab");
    return;
  }
  const url = tab.url || "";
  if (/^(chrome|edge|about|moz-extension|chrome-extension):/i.test(url)) {
    await setBadge("!", "Letter Writer: cannot capture this page");
    return;
  }

  await setBadge("…", "Letter Writer: capturing…");
  let results;
  try {
    results = await api.scripting.executeScript({
      target: { tabId: tab.id },
      func: capturePage,
    });
  } catch (e) {
    console.error("Capture script failed:", e);
    await setBadge("!", "Letter Writer: could not read this page");
    return;
  }

  const page = (results && results[0] && results[0].result) || {};
  const payload = {
    url: truncate(page.url || url, 2000),
    title: truncate(page.title || tab.title || "", 500),
    text: truncate(page.text || "", MAX_TEXT_CHARS),
    html: truncate(page.html || "", MAX_HTML_CHARS),
  };
  if (!payload.text.trim() && !payload.html.trim()) {
    await setBadge("!", "Letter Writer: page had no text");
    return;
  }

  if (await getQueueJobs()) {
    const direct = await queueDirectly(payload);
    if (direct && direct.opportunity_id) {
      // Queued in Firestore (or an approved job's posting): the desktop drafts it on its next run.
      capturedOpportunities.add(direct.opportunity_id);
      await setBadge("✓", `Letter Writer: ${direct.message || "posting sent to the job pipeline"}`, tab.id);
      refreshPending();
      return;
    }
    if (direct && direct.error) {
      await setBadge("!", `Letter Writer: ${direct.error}`, tab.id);
      return;
    }
    // {fallback: true}: no sign-in API on this browser (Firefox for Android) — no Firestore
    // access and no app server there, so the Letter Writer app queues the job instead.
    await handoffToApp(payload, tab.id);
    return;
  }

  const origin = await getOrigin();
  await ensureOriginPermission(origin);
  let ingest;
  try {
    ingest = await ingestAtOrigin(origin, payload);
  } catch (e) {
    console.error("Ingest failed:", e);
    await setBadge("!", describeFetchError(e, origin));
    return;
  }

  if (ingest.opportunity_id) {
    // Queued (or an approved job's posting): the desktop drafts it on its next run; no intake tab.
    capturedOpportunities.add(ingest.opportunity_id);
    await setBadge("✓", `Letter Writer: ${ingest.message || "posting sent to the job pipeline"}`, tab.id);
    refreshPending();
    return;
  }

  if (ingest.note) {
    console.info("Ingest note:", ingest.note);
  }

  const captureId = ingest.capture_id;
  if (!captureId) {
    await setBadge("!", "Letter Writer: ingest returned no id");
    return;
  }

  await setBadge("", "Send job to Letter Writer");
  await api.tabs.create({ url: `${origin}/?capture=${encodeURIComponent(captureId)}` });
}

api.action.onClicked.addListener((tab) => {
  ingestAndOpen(tab);
});

// --- auto-capture of approved jobs (pending.js) ---

let pendingHosts = [];
let pendingLookup = null; // Firestore lookup by canonical key while signed in; null → server fallback
const capturedOpportunities = new Set();

async function refreshPending() {
  try {
    const auth = firestoreAuth();
    if (!auth.available()) {
      // No sign-in API (Firefox for Android): no Firestore queries and no app server — auto-capture
      // stays off; the toolbar hands pages to the Letter Writer app instead.
      pendingHosts = [];
      pendingLookup = null;
      await api.storage.local.set({ pendingHosts: [] });
      return;
    }
    if (await auth.getIdToken()) {
      const { userId } = await auth.status();
      const client = LW_FIRESTORE.createClient({ getIdToken: () => auth.getIdToken() });
      const opportunities = await client.queryApproved(userId);
      pendingHosts = LW_PENDING.pendingHosts(opportunities);
      pendingLookup = async (pageUrl) => {
        const key = LW_PIPELINE.canonicalKey(pageUrl);
        const found = await client.queryByCanonicalKey(userId, key);
        return found[0] || null;
      };
      await api.storage.local.set({ pendingHosts });
      return;
    }
    pendingLookup = null;
    const origin = await getOrigin();
    const opportunities = await LW_PENDING.fetchPending(fetch, origin);
    pendingHosts = LW_PENDING.pendingHosts(opportunities);
    await api.storage.local.set({ pendingHosts });
  } catch (e) {
    console.warn("Pending jobs refresh failed:", e);
  }
}

async function loadPendingHosts() {
  if (pendingHosts.length) return pendingHosts;
  const stored = await api.storage.local.get({ pendingHosts: [] });
  pendingHosts = Array.isArray(stored.pendingHosts) ? stored.pendingHosts : [];
  return pendingHosts;
}

async function autoCapture(tab) {
  if (!firestoreAuth().available()) return; // no sign-in API: no pending list, manual handoff only
  const origin = await getOrigin();
  const lookup =
    pendingLookup ||
    (async (pageUrl) => {
      const list = await LW_PENDING.fetchPending(fetch, origin, pageUrl);
      return list.find((o) => o && o.id) || null;
    });
  const match = await LW_PENDING.matchLoadedPage({
    url: tab.url || "",
    hosts: await loadPendingHosts(),
    done: capturedOpportunities,
    lookup,
  });
  if (!match) return;
  capturedOpportunities.add(match.id);
  let results;
  try {
    results = await api.scripting.executeScript({ target: { tabId: tab.id }, func: capturePage });
  } catch (e) {
    capturedOpportunities.delete(match.id);
    console.warn("Auto-capture could not read the page:", e);
    return;
  }
  const page = (results && results[0] && results[0].result) || {};
  const payload = {
    url: truncate(page.url || tab.url, 2000),
    title: truncate(page.title || tab.title || "", 500),
    text: truncate(page.text || "", MAX_TEXT_CHARS),
    html: truncate(page.html || "", MAX_HTML_CHARS),
  };
  try {
    const direct = await queueDirectly(payload, { interactive: false });
    if (direct && direct.opportunity_id) {
      await setBadge("✓", `Letter Writer: ${direct.message || "posting sent to the job pipeline"}`, tab.id);
    } else if (direct && direct.error) {
      console.warn("Auto-capture queueing failed:", direct.error);
    } else {
      // Not signed in (no interactive sign-in on a page load) or no sign-in API: server fallback.
      const ingest = await ingestAtOrigin(origin, payload);
      if (ingest.opportunity_id) {
        await setBadge("✓", `Letter Writer: ${ingest.message || "posting sent to the job pipeline"}`, tab.id);
      }
    }
  } catch (e) {
    capturedOpportunities.delete(match.id);
    console.warn("Auto-capture ingest failed:", e);
  }
  refreshPending();
}

api.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab && tab.url) {
    autoCapture({ ...tab, id: tabId }).catch((e) => console.warn("Auto-capture failed:", e));
  }
});

if (api.alarms) {
  api.alarms.create("lw-pending-refresh", { periodInMinutes: LW_PENDING.REFRESH_MINUTES });
  api.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "lw-pending-refresh") refreshPending();
  });
}
api.runtime.onStartup.addListener(() => refreshPending());

api.runtime.onInstalled.addListener(() => {
  refreshPending();
  // Firefox for Android has no context menus.
  if (!api.contextMenus) return;
  const createMenu = () => {
    api.contextMenus.create({
      id: "letter-writer-capture",
      title: "Send job to Letter Writer",
      contexts: ["page"],
    });
  };
  const removed = api.contextMenus.removeAll();
  if (removed && typeof removed.then === "function") {
    removed.then(createMenu).catch(createMenu);
  } else {
    createMenu();
  }
});

if (api.contextMenus) {
  api.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "letter-writer-capture") {
      ingestAndOpen(tab);
    }
  });
}
