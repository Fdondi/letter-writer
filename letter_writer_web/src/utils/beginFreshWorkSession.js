/**
 * Rotate the server cookie session so a new vendor/agentic/autocomplete run
 * does not inherit letters, plans, or agentic threads from the previous run.
 * Intake fields are re-posted onto the new session id.
 */
export async function rotateWorkSession({ fetchWithHeartbeat, buildJobSessionPayload }) {
  const result = await fetchWithHeartbeat("/api/phases/clear/", { method: "POST" });
  if (result?.isHeartbeat) {
    throw new Error("Session clear is still in progress. Try again.");
  }
  const payload = result?.data || result || {};
  const newId = payload.new_session_id;
  if (!newId) {
    throw new Error("Session clear did not return a new session id");
  }
  await fetchWithHeartbeat("/api/phases/init/", {
    method: "POST",
    body: JSON.stringify({ session_id: newId }),
  });
  await fetchWithHeartbeat("/api/phases/session/", {
    method: "POST",
    body: JSON.stringify(buildJobSessionPayload(newId)),
  });
  return newId;
}
