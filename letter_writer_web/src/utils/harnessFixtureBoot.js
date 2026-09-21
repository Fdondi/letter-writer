/**
 * Load a named synthetic harness fixture and decide where to send the SPA.
 */

export function harnessRestorePath(restoreResult) {
  if (!restoreResult || typeof restoreResult !== "object") return "/";
  if (restoreResult.vendor) return "/flows/vendors";
  if (restoreResult.agentic) return "/flows/agentic";
  return "/";
}

export async function loadHarnessFixture(fixtureId, { fetchFn = fetch } = {}) {
  const id = String(fixtureId || "").trim();
  if (!id) {
    throw new Error("fixture id is required");
  }
  const res = await fetchFn(`/api/harness/load/${encodeURIComponent(id)}`, {
    method: "POST",
    credentials: "include",
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload.detail || res.statusText || `HTTP ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}
