// Auto-capture of approved jobs (OPPORTUNITY_PIPELINE_PLAN.md §4.7). The extension only remembers
// which hosts have pending jobs, so ordinary browsing never leaves the browser; whether a loaded
// page is one of them is answered by `lookup` — a Firestore query by canonical key when signed in
// (pipeline.js computes the keys, like the phone app), or the app server's /pending/ as fallback.
/* exported LW_PENDING */
const LW_PENDING = (() => {
  const REFRESH_MINUTES = 15;

  function hostOf(url) {
    try {
      const host = new URL(url).hostname.toLowerCase();
      return host.startsWith("www.") ? host.slice(4) : host;
    } catch {
      return "";
    }
  }

  /** Hosts of the pending jobs, so only pages on those hosts are checked. */
  function pendingHosts(opportunities) {
    const hosts = new Set();
    for (const o of opportunities || []) {
      const h = hostOf(o && o.url);
      if (h) hosts.add(h);
    }
    return [...hosts];
  }

  function hostIsPending(url, hosts) {
    const h = hostOf(url);
    if (!h) return false;
    return (hosts || []).some((p) => h === p || h.endsWith(`.${p}`) || p.endsWith(`.${h}`));
  }

  async function fetchPending(fetchFn, origin, url = null, timeoutMs = 8000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const query = url ? `?url=${encodeURIComponent(url)}` : "";
      const response = await fetchFn(`${origin}/api/job-capture/pending/${query}`, {
        credentials: "include",
        signal: controller.signal,
      });
      if (!response.ok) return [];
      const data = await response.json().catch(() => ({}));
      return Array.isArray(data.opportunities) ? data.opportunities : [];
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Decide what to do with a finished page load. Returns the matching opportunity, or null.
   * `done` holds ids already captured this session, so a reload does not send the page twice.
   * `lookup(url)` answers whether this exact page is a pending job (opportunity or null).
   */
  async function matchLoadedPage({ url, hosts, done, lookup }) {
    if (!/^https?:/i.test(url || "") || !hostIsPending(url, hosts)) return null;
    const match = await lookup(url);
    return match && match.id && !(done || new Set()).has(match.id) ? match : null;
  }

  return { REFRESH_MINUTES, hostOf, pendingHosts, hostIsPending, fetchPending, matchLoadedPage };
})();

if (typeof module !== "undefined") {
  module.exports = LW_PENDING;
}
