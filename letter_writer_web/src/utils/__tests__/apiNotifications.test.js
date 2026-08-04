import { shouldNotify } from "../apiNotifications.js";

describe("apiNotifications shouldNotify", () => {
  it("notifies for extract and phase card completions", () => {
    expect(shouldNotify("/api/extract/")).toBe(true);
    expect(shouldNotify("/api/phases/draft/openai/")).toBe(true);
    expect(shouldNotify("/api/phases/refine/anthropic/")).toBe(true);
    expect(shouldNotify("/api/phases/plan/grok/")).toBe(true);
  });

  it("does not notify for session bookkeeping endpoints", () => {
    expect(shouldNotify("/api/phases/session/")).toBe(false);
    expect(shouldNotify("/api/phases/init/")).toBe(false);
    expect(shouldNotify("/api/phases/state/")).toBe(false);
    expect(shouldNotify("/api/phases/restore-from-backup/")).toBe(false);
    expect(shouldNotify("/api/phases/agentic/poll/")).toBe(false);
  });
});
