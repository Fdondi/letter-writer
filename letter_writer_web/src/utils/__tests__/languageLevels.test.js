import { CEFR_LEVELS, defaultLevelForCode, normalizeLanguageEntry } from "../languageLevels";

describe("languageLevels", () => {
  it("normalizes German with default level and umlaut instructions", () => {
    const entry = normalizeLanguageEntry({ code: "de", label: "DE", enabled: true });
    expect(entry.level).toBe("B2");
    expect(entry.instructions).toMatch(/Umlaute/);
  });

  it("defaults English to C2", () => {
    expect(defaultLevelForCode("en")).toBe("C2");
  });

  it("accepts native level", () => {
    const entry = normalizeLanguageEntry({ code: "fr", level: "native" });
    expect(entry.level).toBe("native");
    expect(CEFR_LEVELS).toContain("native");
  });
});
