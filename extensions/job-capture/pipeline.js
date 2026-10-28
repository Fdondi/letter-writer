// Pipeline job keys and capture planning (OPPORTUNITY_PIPELINE_PLAN.md §3). The extension writes
// `opportunities` documents straight to Firestore, like the phone app, so it computes the same
// keys and applies the same capture rules as letter_writer/opportunity_store.py (which mirrors
// the phone's OpportunityRules.planCapture). Keys and document ids are verified against the
// shared fixture letter_writer/tests/fixtures/opportunity_keys.json — see pipeline.test.mjs.
/* exported LW_PIPELINE */
const LW_PIPELINE = (() => {
  const PROPOSED = "proposed";
  const SKIPPED = "skipped";
  const APPROVED = "approved";
  const CAPTURED = "captured";
  const DRAFTING = "drafting";
  const READY = "ready";
  const DONE = "done";
  const APPLIED = "applied";

  // The capture lives on the parent document (1 MiB limit): long text is cut, HTML too large to
  // keep is dropped (extraction then works from the text). Same limits as the Python store.
  const MAX_CAPTURE_TEXT_CHARS = 100000;
  const MAX_CAPTURE_HTML_CHARS = 300000;

  const TRACKING_PARAMS = new Set(["source", "uid", "mid", "trk", "refid", "trackingid", "gclid", "fbclid"]);
  const UUID_IN_PATH = /([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/;
  const LINKEDIN_VIEW = /\/jobs\/view\/(?:[^/]*?-)?([0-9]+)(?:\/|$)/;
  const SWISSDEVJOBS_PATH = /^\/jobs\/([^/]+)/;
  const JOBCLOUD_HOSTS = ["jobs.ch", "jobup.ch", "jobscout24.ch"];
  const SCHEME_RE = /^([A-Za-z][A-Za-z0-9+.\-]*):/;
  const ILLEGAL_ASCII = new Set(' "<>\\^`{|}');
  const BAD_ESCAPE = /%(?![0-9A-Fa-f]{2})/;
  const IPV4_RE = /^(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])){3}$/;
  const LABEL_RE = /^[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?$/;
  const ASCII_WS = /[ \t\n\x0b\f\r]+/;
  const UNICODE_SPACE_OR_CONTROL = /[\p{Cc}\p{Zs}\p{Zl}\p{Zp}]/u;

  async function sha256Hex(text) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  // --- keys (a port of the Python store, which mirrors the Kotlin side) --------------------

  function illegalChar(c) {
    const o = c.codePointAt(0);
    if (o < 0x80) return o < 0x20 || o === 0x7f || ILLEGAL_ASCII.has(c);
    return UNICODE_SPACE_OR_CONTROL.test(c);
  }

  function javaHostnameOk(host) {
    if (host.startsWith("[")) return host.endsWith("]") && host.length > 2;
    if (IPV4_RE.test(host)) return true;
    const labels = (host.endsWith(".") ? host.slice(0, -1) : host).split(".");
    if (!labels.every((l) => LABEL_RE.test(l))) return false;
    return labels.length === 1 || /[A-Za-z]/.test(labels[labels.length - 1][0]);
  }

  /** What java.net.URI(url) yields for scheme/host/port/rawPath/rawQuery, or null where the
   * Kotlin side gets an exception, a null scheme or a null (registry-based) host. */
  function parseUri(url) {
    for (const c of url) if (illegalChar(c)) return null;
    if (BAD_ESCAPE.test(url)) return null;
    const m = SCHEME_RE.exec(url);
    if (!m) return null;
    const scheme = m[1];
    let rest = url.slice(m[0].length);
    const fragAt = rest.indexOf("#");
    if (fragAt >= 0) {
      if (rest.indexOf("#", fragAt + 1) >= 0) return null;
      rest = rest.slice(0, fragAt);
    }
    if (!rest.startsWith("//")) return null;
    rest = rest.slice(2);
    let end = rest.length;
    for (const i of [rest.indexOf("/"), rest.indexOf("?")]) if (i >= 0 && i < end) end = i;
    const authority = rest.slice(0, end);
    rest = rest.slice(end);
    const qAt = rest.indexOf("?");
    const rawPath = qAt >= 0 ? rest.slice(0, qAt) : rest;
    const rawQuery = qAt >= 0 ? rest.slice(qAt + 1) : null;
    if (rawPath.includes("[") || rawPath.includes("]")) return null;
    if ((rawQuery || "").includes("[") || (rawQuery || "").includes("]")) return null;
    const hostport = authority.slice(authority.lastIndexOf("@") + 1);
    let host;
    let portPart;
    if (hostport.startsWith("[")) {
      const close = hostport.indexOf("]");
      if (close < 0) return null;
      host = hostport.slice(0, close + 1);
      portPart = hostport.slice(close + 1);
    } else {
      const colon = hostport.indexOf(":");
      if (colon >= 0) {
        host = hostport.slice(0, colon);
        portPart = hostport.slice(colon);
      } else {
        host = hostport;
        portPart = "";
      }
    }
    if (!host || !javaHostnameOk(host)) return null;
    let port = -1;
    if (portPart) {
      const digits = portPart.slice(1);
      if (!portPart.startsWith(":") || (digits && !/^[0-9]+$/.test(digits))) return null;
      port = digits ? parseInt(digits, 10) : -1;
    }
    return { scheme, host, port, rawPath, rawQuery };
  }

  function queryParams(uri) {
    const out = [];
    for (const part of (uri.rawQuery || "").split("&")) {
      if (!part) continue;
      const eq = part.indexOf("=");
      out.push(eq >= 0 ? [part.slice(0, eq), part.slice(eq + 1)] : [part, ""]);
    }
    return out;
  }

  function isTracking(name) {
    const n = name.toLowerCase();
    return n.startsWith("utm_") || TRACKING_PARAMS.has(n);
  }

  function normalizedUrl(uri, host) {
    const scheme = (uri.scheme || "https").toLowerCase();
    let path = uri.rawPath;
    if (path.length > 1) path = path.replace(/\/+$/, "");
    const kept = queryParams(uri).filter(([name]) => !isTracking(name));
    kept.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
    const query = kept.length ? "?" + kept.map(([k, v]) => (v ? `${k}=${v}` : k)).join("&") : "";
    const port = uri.port > 0 ? `:${uri.port}` : "";
    return `${scheme}://${host}${port}${path}${query}`;
  }

  function keyHost(uri) {
    const host = uri.host.toLowerCase();
    return host.startsWith("www.") ? host.slice(4) : host;
  }

  function onHost(host, domain) {
    return host === domain || host.endsWith("." + domain);
  }

  /** jobs.ch / jobup.ch / JobScout24 by vacancy UUID (``jobs.ch:<uuid>``), LinkedIn by job id,
   * swissdevjobs by slug; anything else ``url:`` + scheme, host, path and non-tracking query. */
  function canonicalKey(rawUrl) {
    const url = (rawUrl || "").trim();
    const uri = parseUri(url);
    if (!uri) return "url:" + url.toLowerCase();
    const host = keyHost(uri);
    const path = uri.rawPath;
    if (JOBCLOUD_HOSTS.some((h) => onHost(host, h))) {
      const m = UUID_IN_PATH.exec(path.toLowerCase());
      if (m) return `jobs.ch:${m[1]}`;
    }
    if (onHost(host, "linkedin.com")) {
      const m = LINKEDIN_VIEW.exec(path);
      if (m) return `linkedin:${m[1]}`;
      for (const [name, value] of queryParams(uri)) {
        if (name.toLowerCase() === "currentjobid" && value && /^[0-9]+$/.test(value)) return `linkedin:${value}`;
      }
    }
    if (onHost(host, "swissdevjobs.ch")) {
      const m = SWISSDEVJOBS_PATH.exec(path);
      if (m) return `swissdevjobs:${m[1].toLowerCase()}`;
    }
    return "url:" + normalizedUrl(uri, host).toLowerCase();
  }

  /** The URL as stored on the opportunity: tracking parameters and fragment removed, case kept. */
  function cleanUrl(rawUrl) {
    const url = (rawUrl || "").trim();
    const uri = parseUri(url);
    return uri ? normalizedUrl(uri, uri.host) : url;
  }

  /** Key for a posting with no link: ``text:`` + sha256 of its whitespace-collapsed text, 16 hex chars. */
  async function textKey(text) {
    const words = (text || "").trim().split(ASCII_WS).filter(Boolean);
    return "text:" + (await sha256Hex(words.join(" "))).slice(0, 16);
  }

  /** ``opportunities`` document id: sha256 of ``"<user_id>\n<canonical_key>"``, first 32 hex chars. */
  async function documentId(userId, key) {
    return (await sha256Hex(`${userId}\n${key}`)).slice(0, 32);
  }

  function sourceOf(key) {
    const prefix = key.split(":", 1)[0];
    return ["jobs.ch", "linkedin", "swissdevjobs"].includes(prefix) ? prefix : "manual";
  }

  function capturePayload(text, via, html, at) {
    const keptHtml = html && html.length <= MAX_CAPTURE_HTML_CHARS ? html : null;
    return {
      text: (text || "").trim().slice(0, MAX_CAPTURE_TEXT_CHARS),
      html: keptHtml,
      captured_at: at || new Date(),
      via,
    };
  }

  // --- capture planning (the phone's OpportunityRules.planCapture) -------------------------

  /** Same rules as the phone: a new job is ``captured`` with text or ``approved`` with only a
   * link; an existing one gets the text unless it is drafting, ready or done. Returns the plan:
   * ``create`` (full document), ``update`` (only the allowed fields) or ``skip`` (message only). */
  async function planCapture({ userId, key, oppId, url, title, text, html, via, existing, now }) {
    url = (url || "").trim();
    text = (text || "").trim();
    if (!url && !text) throw new Error("Paste the job text or a link first.");
    const cap = text ? capturePayload(text, via, html, now) : null;
    const base = { oppId, key };
    if (!existing) {
      const status = cap ? CAPTURED : APPROVED;
      const fields = {
        user_id: userId,
        canonical_key: key,
        source: sourceOf(key),
        url: url ? cleanUrl(url) : "",
        title: (title || "").trim(),
        company: "",
        location: "",
        status,
        skip_reason: null,
        alert_message_ids: [],
        capture: cap,
        created_at: now,
        updated_at: now,
      };
      return {
        ...base,
        action: "create",
        fields,
        status,
        message: cap
          ? "Saved. The desktop drafts it on its next run."
          : "Link saved. Paste the posting text when you have it.",
      };
    }
    const current = existing.status || "";
    if (current === DRAFTING) {
      return { ...base, action: "skip", status: current, message: "The desktop is drafting this job right now." };
    }
    if (current === READY) {
      return { ...base, action: "skip", status: current, message: "Drafts for this job are already ready." };
    }
    if (current === DONE || current === APPLIED) {
      return { ...base, action: "skip", status: current, message: "This job is already done." };
    }
    if (!cap) {
      if (current !== PROPOSED && current !== SKIPPED) {
        return { ...base, action: "skip", status: current, message: "This job is already in the pipeline." };
      }
      return {
        ...base,
        action: "update",
        updateFields: { status: APPROVED, skip_reason: null, updated_at: now },
        status: APPROVED,
        message: "Approved. Paste the posting text when you have it.",
      };
    }
    const updateFields = { status: CAPTURED, capture: cap, skip_reason: null, updated_at: now };
    if (!(existing.url || "") && url) updateFields.url = cleanUrl(url);
    const verb = current === CAPTURED ? "replaced" : "attached";
    return {
      ...base,
      action: "update",
      updateFields,
      status: CAPTURED,
      message: `Posting text ${verb}. The desktop drafts it on its next run.`,
    };
  }

  /** Read, plan and write one capture through a Firestore client (firestore.js). Retries once
   * when a create/update loses a race; a rules rejection while drafting is reported, not retried. */
  async function queueCapture(client, { userId, url, title, text, html, via }) {
    url = (url || "").trim();
    text = (text || "").trim();
    if (!url && !text) throw new Error("Paste the job text or a link first.");
    const key = url ? canonicalKey(url) : await textKey(text);
    const oppId = await documentId(userId, key);
    const path = `opportunities/${oppId}`;
    // What the caller shows in the ✓ tooltip: the page title, upgraded to the stored job's
    // title/company when the document already exists (auto-capture of an approved job).
    const display = { title: (title || "").trim(), company: "" };
    for (let attempt = 0; attempt < 2; attempt++) {
      const existing = await client.getDocument(path);
      if (existing) {
        display.title = existing.title || display.title;
        display.company = existing.company || "";
      }
      const plan = await planCapture({ userId, key, oppId, url, title, text, html, via, existing, now: new Date() });
      if (plan.action === "skip") {
        return { opportunity_id: oppId, opportunity_status: plan.status, message: plan.message, ...display };
      }
      try {
        if (plan.action === "create") {
          await client.createIfAbsent(path, plan.fields);
        } else {
          await client.update(path, plan.updateFields);
        }
        return { opportunity_id: oppId, opportunity_status: plan.status, message: plan.message, ...display };
      } catch (e) {
        if (plan.action === "update" && e && e.code === "PERMISSION_DENIED") {
          // The rules reject updates while the batch is drafting: the guard fired between read and write.
          return {
            opportunity_id: oppId,
            opportunity_status: DRAFTING,
            message: "The desktop is drafting this job right now.",
            ...display,
          };
        }
        if (
          (plan.action === "create" && e && e.code === "ALREADY_EXISTS") ||
          // The document vanished between read and write: production answers FAILED_PRECONDITION,
          // the emulator NOT_FOUND. Either way, lost a race: re-read and re-plan once.
          (plan.action === "update" && e && (e.code === "FAILED_PRECONDITION" || e.code === "NOT_FOUND"))
        ) {
          continue;
        }
        throw e;
      }
    }
    throw new Error("The job changed while saving; try again.");
  }

  return {
    MAX_CAPTURE_TEXT_CHARS,
    MAX_CAPTURE_HTML_CHARS,
    canonicalKey,
    cleanUrl,
    textKey,
    documentId,
    sourceOf,
    capturePayload,
    planCapture,
    queueCapture,
    sha256Hex,
  };
})();

if (typeof module !== "undefined") {
  module.exports = LW_PIPELINE;
}
