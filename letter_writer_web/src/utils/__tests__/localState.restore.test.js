import { countRestorableVendors, syncStateToServer } from "../localState";
import { fetchWithHeartbeat } from "../apiHelpers";

jest.mock("../apiHelpers.js", () => ({
  fetchWithHeartbeat: jest.fn(),
}));

describe("syncStateToServer", () => {
  beforeEach(() => {
    fetchWithHeartbeat.mockReset();
    fetchWithHeartbeat.mockResolvedValue({ data: { status: "ok" }, isHeartbeat: false });
  });

  it("does not post an empty snapshot that would wipe vendors", async () => {
    const ok = await syncStateToServer({
      jobText: "",
      extractedData: null,
      phaseRegistry: null,
    });
    expect(ok).toBe(false);
    expect(fetchWithHeartbeat).not.toHaveBeenCalled();
    expect(countRestorableVendors({ phaseRegistry: null })).toBe(0);
  });

  it("omits vendors when the phase registry is missing but job text is present", async () => {
    const ok = await syncStateToServer({
      jobText: "Role at Müller",
      extractedData: null,
      phaseRegistry: null,
    });
    expect(ok).toBe(true);
    const body = JSON.parse(fetchWithHeartbeat.mock.calls[0][1].body);
    expect(body.job_text).toBe("Role at Müller");
    expect(body.vendors).toBeUndefined();
  });

  it("counts vendors stored on phase cards", () => {
    const count = countRestorableVendors({
      phaseRegistry: [
        {
          phase: "draft",
          cardData: {
            gemini: { draft_letter: "Hallo" },
            mistral: { draft_letter: "Bonjour" },
          },
        },
      ],
    });
    expect(count).toBe(2);
  });
});
