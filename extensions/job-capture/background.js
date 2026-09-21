const DEFAULT_ORIGIN = "https://localhost:8443";
const MAX_TEXT_CHARS = 200000;
const MAX_HTML_CHARS = 800000;
const INGEST_TIMEOUT_MS = 8000;

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
      signal: controller.signal,
    });
    const ingest = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = ingest.detail || response.statusText || `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (!ingest.capture_id) {
      throw new Error("ingest returned no id");
    }
    return ingest;
  } finally {
    clearTimeout(timer);
  }
}

async function setBadge(text, title) {
  try {
    await api.action.setBadgeText({ text: text || "" });
    if (title) await api.action.setTitle({ title });
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

api.runtime.onInstalled.addListener(() => {
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

api.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "letter-writer-capture") {
    ingestAndOpen(tab);
  }
});
