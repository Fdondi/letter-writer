import { sanitizeReturnUrl } from "../LoginPage";

describe("LoginPage sanitizeReturnUrl", () => {
  it("keeps same-site relative paths", () => {
    expect(sanitizeReturnUrl("/")).toBe("/");
    expect(sanitizeReturnUrl("/intake")).toBe("/intake");
    expect(sanitizeReturnUrl("/vendor?job=123#top")).toBe("/vendor?job=123#top");
  });

  it("rejects absolute, protocol-relative and backslash URLs", () => {
    expect(sanitizeReturnUrl("https://accounts.youtube.com")).toBe("/");
    expect(sanitizeReturnUrl("http://localhost:8443/intake")).toBe("/");
    expect(sanitizeReturnUrl("//evil.example/phish")).toBe("/");
    expect(sanitizeReturnUrl("/\\evil.example")).toBe("/");
  });

  it("rejects javascript: URLs and empty input", () => {
    expect(sanitizeReturnUrl("javascript:alert(1)")).toBe("/");
    expect(sanitizeReturnUrl("")).toBe("/");
    expect(sanitizeReturnUrl(null)).toBe("/");
    expect(sanitizeReturnUrl(undefined)).toBe("/");
  });
});
