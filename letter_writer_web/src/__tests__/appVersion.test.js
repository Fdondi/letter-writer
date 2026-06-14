import { parseAppVersionText } from "../appVersion";

describe("parseAppVersionText", () => {
  it("returns the version from the first non-empty line", () => {
    const raw = "1.2.3 - Latest change\n0.9.0 - Older entry\n";
    expect(parseAppVersionText(raw)).toBe("1.2.3");
  });

  it("ignores blank lines before the first entry", () => {
    const raw = "\n\n2.0.0 - After leading blanks\n";
    expect(parseAppVersionText(raw)).toBe("2.0.0");
  });

  it("throws when the file is empty", () => {
    expect(() => parseAppVersionText("  \n  ")).toThrow("empty file");
  });

  it("throws when the first line is not in changelog format", () => {
    expect(() => parseAppVersionText("1.0.0")).toThrow("invalid first line");
    expect(() => parseAppVersionText("not-a-version - text")).toThrow("invalid first line");
  });
});
