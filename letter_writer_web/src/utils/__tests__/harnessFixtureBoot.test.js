import { harnessRestorePath, loadHarnessFixture } from "../harnessFixtureBoot";

describe("harnessFixtureBoot", () => {
  test("maps vendor restore to vendor flow", () => {
    expect(harnessRestorePath({ vendor: { vendorStage: "phases" } })).toBe("/flows/vendors");
  });

  test("maps agentic restore to agentic flow", () => {
    expect(harnessRestorePath({ agentic: { stage: "agentic" } })).toBe("/flows/agentic");
  });

  test("maps intake-only restore to home", () => {
    expect(harnessRestorePath({ restored: true })).toBe("/");
  });

  test("loadHarnessFixture posts the id and returns JSON", async () => {
    const fetchFn = jest.fn(async () => ({
      ok: true,
      json: async () => ({ status: "ok", fixture_id: "empty-intake", session_state: {} }),
    }));
    const payload = await loadHarnessFixture("empty-intake", { fetchFn });
    expect(fetchFn).toHaveBeenCalledWith("/api/harness/load/empty-intake", {
      method: "POST",
      credentials: "include",
    });
    expect(payload.fixture_id).toBe("empty-intake");
  });
});
