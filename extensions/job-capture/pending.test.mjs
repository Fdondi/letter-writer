// node --test extensions/job-capture/  (no dependencies; fake browser API and fake server)
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const P = require("./pending.js");
const PL = require("./pipeline.js");
const FS = require("./firestore.js");

const JOB = "https://www.jobs.ch/de/stellenangebote/detail/11111111-2222-4333-8444-555555555555/";
const JOB_KEY = "jobs.ch:11111111-2222-4333-8444-555555555555";
const SIGNED_IN = {
  refreshToken: "fake-refresh-token",
  idToken: "fake-firebase-id-token",
  expiresAt: Date.now() + 3600e3,
  userId: "google-sub-1",
  email: "u@example.com",
};

test("pending hosts and host matching", () => {
  const hosts = P.pendingHosts([{ url: JOB }, { url: "https://www.linkedin.com/jobs/view/1" }, { url: "" }, {}]);
  assert.deepEqual(hosts.sort(), ["jobs.ch", "linkedin.com"]);
  assert.equal(P.hostIsPending("https://jobs.ch/x", hosts), true);
  assert.equal(P.hostIsPending("https://ch.linkedin.com/jobs/view/1", hosts), true);
  assert.equal(P.hostIsPending("https://example.com/", hosts), false);
  assert.equal(P.hostIsPending("not a url", hosts), false);
});

test("a page is looked up only on a pending host, and only once per job", async () => {
  const calls = [];
  const lookup = async (url) => {
    calls.push(url);
    return url.includes("11111111") ? { id: "o1", url: JOB } : null;
  };
  assert.equal(await P.matchLoadedPage({ url: "https://example.com/", hosts: ["jobs.ch"], done: new Set(), lookup }), null);
  assert.equal(calls.length, 0);
  const match = await P.matchLoadedPage({ url: `${JOB}?utm_source=x`, hosts: ["jobs.ch"], done: new Set(), lookup });
  assert.deepEqual(match, { id: "o1", url: JOB });
  assert.equal(calls[0], `${JOB}?utm_source=x`);
  assert.equal(await P.matchLoadedPage({ url: JOB, hosts: ["jobs.ch"], done: new Set(["o1"]), lookup }), null);
  assert.equal(await P.matchLoadedPage({ url: "https://www.jobs.ch/de/other/", hosts: ["jobs.ch"], done: new Set(), lookup }), null);
});

test("an unreachable or failing server means no capture, not a crash", async () => {
  const failing = async () => ({ ok: false, json: async () => ({}) });
  assert.deepEqual(await P.fetchPending(failing, "https://x"), []);
  const garbage = async () => ({ ok: true, json: async () => ({ opportunities: "nope" }) });
  assert.deepEqual(await P.fetchPending(garbage, "https://x"), []);
});

function fakeBrowser({ serverOpportunities, ingestReply }) {
  const listeners = {};
  const on = (name) => ({ addListener: (fn) => (listeners[name] = fn) });
  const badges = [];
  const titles = [];
  const created = [];
  const ingested = [];
  const fetched = [];
  const store = {};
  const chrome = {
    action: {
      onClicked: on("action"),
      setBadgeText: async (b) => badges.push(b),
      setTitle: async (t) => titles.push(t),
    },
    runtime: { onInstalled: on("installed"), onStartup: on("startup") },
    tabs: { onUpdated: on("updated"), create: async (t) => created.push(t) },
    alarms: { create: () => {}, onAlarm: on("alarm") },
    storage: {
      local: {
        get: async (defaults) => ({ ...defaults, ...store }),
        set: async (v) => Object.assign(store, v),
        remove: async (k) => {
          delete store[k];
        },
      },
    },
    scripting: {
      executeScript: async () => [{ result: { url: JOB, title: "Job", text: "Posting text", html: "<p>Posting</p>" } }],
    },
    permissions: { request: async () => true },
    // no identity, no contextMenus: like Firefox for Android
  };
  const fetch = async (url, opts = {}) => {
    fetched.push(url);
    if (url.includes("/api/job-capture/pending/")) {
      const q = new URL(url).searchParams.get("url");
      const list = q ? serverOpportunities.filter((o) => q.startsWith(o.url)) : serverOpportunities;
      return { ok: true, json: async () => ({ opportunities: list }) };
    }
    if (url.includes("/api/job-capture/ingest/")) {
      ingested.push(JSON.parse(opts.body));
      return { ok: true, statusText: "OK", json: async () => ingestReply };
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  return { chrome, fetch, listeners, badges, titles, created, ingested, fetched, store };
}

function loadBackground(env) {
  const context = vm.createContext({
    chrome: env.chrome,
    fetch: env.fetch,
    console: { warn() {}, error() {}, log() {} },
    URL,
    URLSearchParams,
    AbortController,
    setTimeout,
    clearTimeout,
    encodeURIComponent,
    crypto,
    TextEncoder,
  });
  vm.runInContext(readFileSync(path.join(here, "pending.js"), "utf8"), context);
  vm.runInContext(readFileSync(path.join(here, "pipeline.js"), "utf8"), context);
  vm.runInContext(readFileSync(path.join(here, "firestore.js"), "utf8"), context);
  vm.runInContext(readFileSync(path.join(here, "background.js"), "utf8"), context);
  return context;
}

const tick = () => new Promise((r) => setTimeout(r, 20));

test("background: without a sign-in API (Firefox for Android) auto-capture stays off and no server is called", async () => {
  const env = fakeBrowser({
    serverOpportunities: [{ id: "o1", url: JOB }],
    ingestReply: { status: "ok", opportunity_id: "o1", opportunity_status: "captured", message: "Posting text attached." },
  });
  loadBackground(env);
  env.listeners.installed();
  await tick();
  env.listeners.updated(7, { status: "complete" }, { id: 7, url: `${JOB}?utm_source=x`, title: "Job" });
  await tick();
  assert.equal(env.fetched.length, 0, "no pending-list fetch and no ingest without a sign-in API");
  assert.equal(env.ingested.length, 0);
  assert.equal(env.created.length, 0);
  // refreshStats resets the global badge/title, but no per-tab badge is ever set.
  assert.equal(env.badges.filter((b) => b.tabId !== undefined).length, 0);
  assert.deepEqual([...(env.store.pendingHosts || [])], [], "the pending list is cleared");
});

test("background: the toolbar button hands the page to the Letter Writer app when there is no sign-in API", async () => {
  const env = fakeBrowser({ serverOpportunities: [], ingestReply: { status: "ok", capture_id: "c1" } });
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(env.ingested.length, 0, "no server ingest without a sign-in API");
  assert.equal(env.fetched.length, 0);
  assert.equal(env.created.length, 1, "the handoff URL opens the app");
  const handoff = new URL(env.created[0].url);
  assert.equal(handoff.protocol, "letterwriter:");
  assert.equal(handoff.host, "capture");
  assert.equal(handoff.searchParams.get("url"), JOB);
  assert.equal(handoff.searchParams.get("text"), "Posting text");
  assert.ok(env.badges.some((b) => b.tabId === 3 && b.text === "→"));
  assert.ok(env.titles.some((t) => t.tabId === 3 && /handed to the Letter Writer app/.test(t.title || "")));
});

test("background: on a browser without a sign-in API a stored queue-off is ignored — the handoff always runs", async () => {
  const env = fakeBrowser({ serverOpportunities: [], ingestReply: {} });
  env.store.queueJobs = false; // the stash flow would be a dead end: no app server on the phone
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(env.ingested.length, 0, "no server ingest");
  assert.equal(env.fetched.length, 0);
  assert.equal(env.created.length, 1, "the handoff still runs");
  assert.equal(new URL(env.created[0].url).protocol, "letterwriter:");
  assert.ok(env.badges.some((b) => b.tabId === 3 && b.text === "→"));
});

test("background: the app handoff URL round-trips tricky text", async () => {
  const env = fakeBrowser({ serverOpportunities: [], ingestReply: {} });
  const tricky = "Stelle & Titel — 100% «remote» in Zürich\nzweite Zeile";
  env.chrome.scripting.executeScript = async () => [{ result: { url: JOB, title: "Job", text: tricky, html: "<p>x</p>" } }];
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  const handoff = new URL(env.created[0].url);
  assert.equal(handoff.searchParams.get("url"), JOB);
  assert.equal(handoff.searchParams.get("text"), tricky);
});

test("background: an oversized posting is handed off without text — the app fetches the page itself", async () => {
  const env = fakeBrowser({ serverOpportunities: [], ingestReply: {} });
  env.chrome.scripting.executeScript = async () => [{ result: { url: JOB, title: "Job", text: "x".repeat(200000), html: "<p>x</p>" } }];
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(env.created.length, 1);
  const handoff = new URL(env.created[0].url);
  assert.equal(handoff.searchParams.get("url"), JOB);
  assert.equal(handoff.searchParams.has("text"), false, "text beyond the budget is left out");
});

test("background: with queueing off (signed out, desktop browser), the toolbar button still opens the intake tab", async () => {
  const env = fakeSignedInBrowser({ ingestReply: { status: "ok", capture_id: "c1" } });
  env.store.queueJobs = false; // stash flow: store the page, do not queue it as a job
  loadBackground(env);
  env.listeners.action({ id: 4, url: "https://example.com/job", title: "Job" });
  await tick();
  assert.equal(env.ingested.length, 1, "the page is stashed at the app origin");
  assert.equal(env.ingested[0].queue, undefined, "the stash payload carries no queue flag");
  assert.equal(env.commits.length, 0, "no Firestore write with queueing off");
  assert.equal(JSON.stringify(env.created), JSON.stringify([{ url: "https://localhost:8443/?capture=c1" }]));
});

// --- direct-to-Firestore queueing (signed in via the identity API) ---

function fakeSignedInBrowser({ firestoreDocs = {}, commits = [], approved = [], byKey = [], allStatuses = [], ingestReply = { status: "ok", capture_id: "c1" } } = {}) {
  const listeners = {};
  const on = (name) => ({ addListener: (fn) => (listeners[name] = fn) });
  const badges = [];
  const titles = [];
  const created = [];
  const ingested = [];
  const store = {};
  const chrome = {
    action: {
      onClicked: on("action"),
      setBadgeText: async (b) => badges.push(b),
      setTitle: async (t) => titles.push(t),
    },
    runtime: {
      onInstalled: on("installed"),
      onStartup: on("startup"),
      getURL: (p) => `chrome-extension://pdmjgkmedcgadkkljfkhapdoifcdflon/${p || ""}`,
    },
    tabs: { onUpdated: on("updated"), create: async (t) => created.push(t) },
    alarms: { create: () => {}, onAlarm: on("alarm") },
    storage: {
      local: {
        get: async (defaults) => ({ ...defaults, ...store }),
        set: async (v) => Object.assign(store, v),
        remove: async (k) => {
          delete store[k];
        },
      },
    },
    scripting: {
      executeScript: async () => [{ result: { url: JOB, title: "Job", text: "Posting text", html: "<p>Posting</p>" } }],
    },
    permissions: { request: async () => true },
    identity: {
      getRedirectURL: () => "https://pdmjgkmedcgadkkljfkhapdoifcdflon.chromiumapp.org/",
      launchWebAuthFlow: (details, cb) => {
        // Chrome: the redirect URI rides in the url's redirect_uri parameter.
        cb(`${new URL(details.url).searchParams.get("redirect_uri")}#id_token=fake-google-id-token`);
      },
    },
  };
  const docRow = (o) => ({ document: { name: `${FS.FIRESTORE_BASE}/opportunities/${o.id}`, fields: FS.encodeFields(o) } });
  const fetch = async (url, opts = {}) => {
    if (url.includes("identitytoolkit.googleapis.com")) {
      return {
        ok: true,
        json: async () => ({
          idToken: "fake-firebase-id-token",
          refreshToken: "fake-refresh-token",
          expiresIn: "3600",
          localId: "firebase-uid-1",
          federatedId: "google-sub-1",
          email: "u@example.com",
        }),
      };
    }
    if (url.includes("securetoken.googleapis.com")) {
      return {
        ok: true,
        json: async () => ({ id_token: "fake-firebase-id-token", refresh_token: "fake-refresh-token", expires_in: "3600" }),
      };
    }
    if (url.includes("firestore.googleapis.com")) {
      if (opts.method === "POST" && url.endsWith(":commit")) {
        commits.push(JSON.parse(opts.body));
        return { ok: true, json: async () => ({}) };
      }
      if (opts.method === "POST" && url.endsWith(":runQuery")) {
        const filters = JSON.parse(opts.body).structuredQuery.where.compositeFilter.filters.map((f) => [
          f.fieldFilter.field.fieldPath,
          f.fieldFilter.value.stringValue,
        ]);
        const key = filters.find(([f]) => f === "canonical_key");
        const status = filters.find(([f]) => f === "status");
        // queryApproved/queryByCanonicalKey carry a status filter; the stats query only filters
        // on user_id and sees every pipeline status.
        const list = key
          ? byKey.filter((o) => o.canonical_key === key[1])
          : status
            ? approved.filter((o) => o.status === status[1])
            : allStatuses;
        return { ok: true, json: async () => list.map(docRow) };
      }
      if (url.includes("/documents/opportunities/")) {
        const id = url.split("/documents/opportunities/")[1];
        const doc = firestoreDocs[id];
        if (!doc) return { status: 404, ok: false, statusText: "Not Found", json: async () => ({}) };
        return { ok: true, json: async () => ({ name: `${FS.FIRESTORE_BASE}/opportunities/${id}`, fields: FS.encodeFields(doc) }) };
      }
    }
    if (url.includes("/api/job-capture/pending/")) {
      const q = new URL(url).searchParams.get("url");
      const list = q ? approved.filter((o) => q.startsWith(o.url)) : approved;
      return { ok: true, json: async () => ({ opportunities: list }) };
    }
    if (url.includes("/api/job-capture/ingest/")) {
      ingested.push(JSON.parse(opts.body));
      return { ok: true, statusText: "OK", json: async () => ingestReply };
    }
    throw new Error(`unexpected fetch ${url}`);
  };
  return { chrome, fetch, listeners, badges, titles, created, ingested, commits, store };
}

test("background: queueing writes the job to Firestore directly — no app server call", async () => {
  const env = fakeSignedInBrowser();
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(env.ingested.length, 0, "no ingest call");
  assert.equal(env.created.length, 0, "no intake tab");
  assert.equal(env.commits.length, 1);
  const write = env.commits[0].writes[0];
  const expectedId = await PL.documentId("google-sub-1", JOB_KEY);
  const expectedName = `projects/${FS.PROJECT_ID}/databases/${FS.DATABASE_ID}/documents/opportunities/${expectedId}`;
  assert.ok(write.update, "a new job is written");
  assert.equal(write.update.name, expectedName, "resource path, not a URL");
  assert.equal(write.currentDocument.exists, false, "create-if-absent precondition");
  assert.equal(write.update.fields.status.stringValue, "captured");
  assert.equal(write.update.fields.user_id.stringValue, "google-sub-1");
  assert.equal(write.update.fields.canonical_key.stringValue, JOB_KEY);
  assert.equal(write.update.fields.capture.mapValue.fields.text.stringValue, "Posting text");
  assert.equal(write.update.fields.capture.mapValue.fields.via.stringValue, "extension");
  assert.ok(env.badges.some((b) => b.tabId === 3 && b.text === "✓"));
  assert.ok(
    env.titles.some((t) => t.tabId === 3 && t.title === "Letter Writer: Job"),
    "the ✓ tooltip names the job (page title fallback), not the success boilerplate",
  );
  assert.ok(
    !env.titles.some((t) => t.tabId === 3 && /Saved\. The desktop drafts it/.test(t.title || "")),
    "no success boilerplate on a plain capture",
  );
  assert.ok(
    !env.titles.some((t) => (t.title || "").includes("opportunities/")),
    "no Firestore internals in any tooltip",
  );
  assert.equal(env.store.lwAuth.userId, "google-sub-1", "the sign-in profile is stored");
});

test("background: the badge clears when the tab navigates to another page", async () => {
  const env = fakeSignedInBrowser();
  env.store.lwAuth = { ...SIGNED_IN };
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.ok(env.badges.some((b) => b.tabId === 3 && b.text === "✓"));
  env.listeners.updated(3, { status: "loading" }, { id: 3, url: "https://example.com/other", title: "Other" });
  await tick();
  const last = env.badges.filter((b) => b.tabId === 3).pop();
  assert.equal(last.text, "", "the ✓ disappears when the page changes");
  const lastTitle = env.titles.filter((t) => t.tabId === 3).pop();
  assert.ok(
    /0 queued · 0 running · 0 ready/.test(lastTitle.title || ""),
    "the per-tab tooltip resets to the pipeline counts summary",
  );
});

test("background: auto-capture attaches an approved job's posting through Firestore", async () => {
  const expectedId = await PL.documentId("google-sub-1", JOB_KEY);
  const approvedJob = { id: "o1", url: JOB, canonical_key: JOB_KEY, status: "approved" };
  const env = fakeSignedInBrowser({
    firestoreDocs: {
      [expectedId]: { status: "approved", url: JOB, user_id: "google-sub-1", title: "Senior Engineer", company: "Acme" },
    },
    approved: [approvedJob],
    byKey: [approvedJob],
  });
  env.store.lwAuth = { ...SIGNED_IN };
  loadBackground(env);
  env.listeners.installed();
  await tick();
  env.listeners.updated(7, { status: "complete" }, { id: 7, url: `${JOB}?utm_source=x`, title: "Job" });
  await tick();
  assert.equal(env.ingested.length, 0, "no ingest call");
  assert.equal(env.commits.length, 1);
  const write = env.commits[0].writes[0];
  assert.ok(write.update, "the existing approved job is updated");
  assert.equal(write.update.name, `projects/${FS.PROJECT_ID}/databases/${FS.DATABASE_ID}/documents/opportunities/${expectedId}`);
  assert.equal(write.update.fields.status.stringValue, "captured");
  assert.deepEqual(write.updateMask.fieldPaths.sort(), ["capture", "skip_reason", "status", "updated_at"]);
  assert.equal(write.currentDocument.exists, true, "update only when present");
  assert.ok(env.badges.some((b) => b.tabId === 7 && b.text === "✓"));
  assert.ok(
    env.titles.some((t) => t.tabId === 7 && t.title === "Letter Writer: Senior Engineer — Acme"),
    "the ✓ tooltip uses the stored job title and company",
  );
  // Reloading the page does not send it again.
  env.listeners.updated(7, { status: "complete" }, { id: 7, url: JOB, title: "Job" });
  await tick();
  assert.equal(env.commits.length, 1);
});

test("background: signed out with a sign-in API, auto-capture falls back to the app server", async () => {
  const approvedJob = { id: "o1", url: JOB, status: "approved" };
  const env = fakeSignedInBrowser({
    approved: [approvedJob],
    ingestReply: { status: "ok", opportunity_id: "o1", opportunity_status: "captured", message: "Posting text attached." },
  });
  // No lwAuth in the store: signed out, so the pending list comes from the server.
  loadBackground(env);
  env.listeners.installed();
  await tick();
  env.listeners.updated(7, { status: "complete" }, { id: 7, url: `${JOB}?utm_source=x`, title: "Job" });
  await tick();
  assert.equal(env.commits.length, 0, "no Firestore write while signed out");
  assert.equal(env.ingested.length, 1, "the app server ingests the posting");
  assert.equal(env.ingested[0].text, "Posting text");
  assert.ok(env.badges.some((b) => b.tabId === 7 && b.text === "✓"));
});

test("background: a job the desktop is drafting is reported, not rewritten", async () => {
  const expectedId = await PL.documentId("google-sub-1", JOB_KEY);
  const env = fakeSignedInBrowser({
    firestoreDocs: { [expectedId]: { status: "drafting", url: JOB, user_id: "google-sub-1" } },
  });
  env.store.lwAuth = { ...SIGNED_IN };
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(env.commits.length, 0, "no write");
  assert.ok(env.badges.some((b) => b.tabId === 3 && b.text === "✓"));
  assert.ok(env.titles.some((t) => t.tabId === 3 && /drafting this job right now/.test(t.title || "")));
});

test("background: the global badge shows the ready count and the tooltip breaks the pipeline down", async () => {
  const env = fakeSignedInBrowser({
    approved: [],
    allStatuses: [
      { id: "a", status: "captured" },
      { id: "b", status: "captured" },
      { id: "c", status: "captured" },
      { id: "d", status: "drafting" },
      { id: "e", status: "ready" },
      { id: "f", status: "ready" },
      { id: "g", status: "done" },
    ],
  });
  env.store.lwAuth = { ...SIGNED_IN };
  loadBackground(env);
  env.listeners.installed();
  await tick();
  await tick();
  assert.ok(
    env.badges.some((b) => b.tabId === undefined && b.text === "2"),
    "the global badge shows how many drafts are ready for attention",
  );
  assert.ok(
    env.titles.some((t) => t.tabId === undefined && /3 queued · 1 running · 2 ready/.test(t.title || "")),
    "the global tooltip breaks the pipeline down",
  );
});

test("background: sign-in calls launchWebAuthFlow with {url, interactive} only — the redirect URI rides in the URL", async () => {
  // Verified against both browsers' schemas: Firefox's identity.json declares `url` +
  // `interactive` only (and Chrome's is the same), and both reject unknown properties with
  // "Unexpected property" — in any spelling. The redirect URI is the authorization URL's
  // redirect_uri parameter; each browser intercepts its own generated redirect URL there.
  const collect = (env, details) => {
    env.chrome.identity.launchWebAuthFlow = (d, cb) => {
      details.push(d);
      cb(`${new URL(d.url).searchParams.get("redirect_uri")}#id_token=fake-google-id-token`);
    };
  };

  const chromeEnv = fakeSignedInBrowser();
  const chromeDetails = [];
  collect(chromeEnv, chromeDetails);
  loadBackground(chromeEnv);
  chromeEnv.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(chromeDetails.length, 1);
  assert.deepEqual(Object.keys(chromeDetails[0]).sort(), ["interactive", "url"]);
  assert.equal(
    new URL(chromeDetails[0].url).searchParams.get("redirect_uri"),
    "https://pdmjgkmedcgadkkljfkhapdoifcdflon.chromiumapp.org/",
  );

  // Firefox: the same call shape; the redirect URI is the mozoauth2 loopback derived from
  // getRedirectURL() (RFC 8252 — Google needs a domain it can verify).
  const firefoxEnv = fakeSignedInBrowser();
  firefoxEnv.chrome.identity.getRedirectURL = () => "https://abc123.extensions.allizom.org/";
  const firefoxDetails = [];
  collect(firefoxEnv, firefoxDetails);
  loadBackground(firefoxEnv);
  firefoxEnv.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(firefoxDetails.length, 1);
  assert.deepEqual(Object.keys(firefoxDetails[0]).sort(), ["interactive", "url"]);
  assert.equal(new URL(firefoxDetails[0].url).searchParams.get("redirect_uri"), "http://127.0.0.1/mozoauth2/abc123");
});

test("auth: the Firebase exchange sends an http(s) requestUri — identitytoolkit rejects the extension origin", async () => {
  // Probed against the REST endpoint: requestUri=moz-extension://<uuid>/ → 400
  // INVALID_REQUEST_URI; http://localhost is accepted (verification then proceeds to the
  // id_token itself). The extension origin must not be sent as requestUri.
  const requestUris = [];
  const api = {
    identity: {
      getRedirectURL: () => "https://abc123.extensions.allizom.org/",
      launchWebAuthFlow: (details, cb) =>
        cb(`${new URL(details.url).searchParams.get("redirect_uri")}#id_token=fake-google-id-token`),
    },
    runtime: { getURL: (p) => `moz-extension://some-install-uuid/${p || ""}` },
    storage: { local: { get: async (d) => ({ ...d }), set: async () => {}, remove: async () => {} } },
  };
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts = {}) => {
    if (String(url).includes("identitytoolkit.googleapis.com")) {
      requestUris.push(new URLSearchParams(opts.body).get("requestUri"));
      return {
        ok: true,
        json: async () => ({ idToken: "t", refreshToken: "r", expiresIn: "3600", localId: "u", email: "e" }),
      };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };
  try {
    await FS.createAuth({ api }).signIn(true);
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.deepEqual(requestUris, ["http://localhost"]);
});

test("auth: the stored user id is the Google sub, not the Firebase localId", async () => {
  // The rules key on the Firebase token's identities['google.com'][0] (the Google sub) — the
  // phone app's user id and the personal_data doc id. The Firebase localId differs when the
  // account was created with email/password and Google linked later, and federatedId is not
  // reliably the raw sub — so the sub is read from the tokens.
  const b64url = (obj) => Buffer.from(JSON.stringify(obj)).toString("base64url");
  const googleIdToken = `h.${b64url({ sub: "107281079540942343648" })}.s`;
  const firebaseIdToken = `h.${b64url({
    sub: "LnGdTMgPpbPaADVQKpHoW2NVUnQ2",
    firebase: { identities: { "google.com": ["107281079540942343648"] } },
  })}.s`;
  let stored = null;
  const api = {
    identity: {
      getRedirectURL: () => "https://abc123.extensions.allizom.org/",
      launchWebAuthFlow: (details, cb) =>
        cb(`${new URL(details.url).searchParams.get("redirect_uri")}#id_token=${googleIdToken}`),
    },
    runtime: { getURL: (p) => `moz-extension://some-install-uuid/${p || ""}` },
    storage: {
      local: {
        get: async (d) => ({ ...d }),
        set: async (v) => { stored = v.lwAuth; },
        remove: async () => {},
      },
    },
  };
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      idToken: firebaseIdToken,
      refreshToken: "r",
      expiresIn: "3600",
      localId: "LnGdTMgPpbPaADVQKpHoW2NVUnQ2",
      federatedId: "google.com|107281079540942343648", // prefixed form must lose to the decoded sub
      email: "francesco314@gmail.com",
    }),
  });
  try {
    await FS.createAuth({ api }).signIn(true);
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal(stored.userId, "107281079540942343648");
});

test("background: a sign-in failure says what to do instead of reaching for localhost", async () => {
  const env = fakeSignedInBrowser();
  env.chrome.identity.launchWebAuthFlow = (details, cb) => cb(undefined);
  loadBackground(env);
  env.listeners.action({ id: 3, url: JOB, title: "Job" });
  await tick();
  assert.equal(env.ingested.length, 0);
  assert.equal(env.commits.length, 0);
  assert.ok(env.badges.some((b) => b.tabId === 3 && b.text === "!"));
  assert.ok(env.titles.some((t) => t.tabId === 3 && /Sign in with Google/.test(t.title || "")));
});
