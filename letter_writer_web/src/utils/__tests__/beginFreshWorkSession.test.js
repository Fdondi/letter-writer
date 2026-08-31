import { rotateWorkSession } from "../beginFreshWorkSession.js";

describe("rotateWorkSession", () => {
  it("clears the server session then inits and posts intake onto the new id", async () => {
    const fetchWithHeartbeat = jest.fn(async (url) => {
      if (url.includes("/clear/")) {
        return { data: { new_session_id: "sess-new", old_session_id: "sess-old" } };
      }
      return { data: { status: "ok" } };
    });
    const buildJobSessionPayload = jest.fn((id) => ({ session_id: id, job_text: "Job" }));

    const newId = await rotateWorkSession({ fetchWithHeartbeat, buildJobSessionPayload });

    expect(newId).toBe("sess-new");
    expect(fetchWithHeartbeat.mock.calls.map((c) => c[0])).toEqual([
      "/api/phases/clear/",
      "/api/phases/init/",
      "/api/phases/session/",
    ]);
    expect(JSON.parse(fetchWithHeartbeat.mock.calls[1][1].body)).toEqual({ session_id: "sess-new" });
    expect(buildJobSessionPayload).toHaveBeenCalledWith("sess-new");
    expect(JSON.parse(fetchWithHeartbeat.mock.calls[2][1].body)).toEqual({
      session_id: "sess-new",
      job_text: "Job",
    });
  });

  it("does not invent a session id when clear returns none", async () => {
    const fetchWithHeartbeat = jest.fn(async () => ({ data: { status: "ok" } }));
    await expect(
      rotateWorkSession({ fetchWithHeartbeat, buildJobSessionPayload: jest.fn() })
    ).rejects.toThrow("did not return a new session id");
    expect(fetchWithHeartbeat).toHaveBeenCalledTimes(1);
  });
});
