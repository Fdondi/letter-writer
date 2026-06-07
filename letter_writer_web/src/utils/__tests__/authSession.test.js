import {
  AUTH_SESSION_EXPIRED_EVENT,
  AUTH_SESSION_RESTORED_EVENT,
  clearSessionExpiredReport,
  fetchAuthStatus,
  handleUnauthorizedResponse,
  markInitialAuthCheckComplete,
  reportSessionExpired,
  resetAuthSessionTracking,
} from "../authSession.js";

describe("authSession", () => {
  beforeEach(() => {
    resetAuthSessionTracking();
    clearSessionExpiredReport();
    global.fetch = jest.fn();
  });

  it("does not report expiry before initial auth check completes", () => {
    const handler = jest.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, handler);
    reportSessionExpired();
    expect(handler).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, handler);
  });

  it("reports expiry only once after user had been authenticated", () => {
    markInitialAuthCheckComplete(true);
    const handler = jest.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, handler);
    reportSessionExpired();
    reportSessionExpired();
    expect(handler).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, handler);
  });

  it("handleUnauthorizedResponse reports on 401", () => {
    markInitialAuthCheckComplete(true);
    const handler = jest.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, handler);
    handleUnauthorizedResponse({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, handler);
  });

  it("fetchAuthStatus returns authenticated false when request fails", async () => {
    global.fetch.mockResolvedValue({ ok: false });
    await expect(fetchAuthStatus()).resolves.toEqual({ authenticated: false });
  });

  it("notifySessionRestored clears expired flag", async () => {
    const { notifySessionRestored, isSessionExpiredReported } = await import("../authSession.js");
    markInitialAuthCheckComplete(true);
    reportSessionExpired();
    expect(isSessionExpiredReported()).toBe(true);
    const restored = jest.fn();
    window.addEventListener(AUTH_SESSION_RESTORED_EVENT, restored);
    notifySessionRestored();
    expect(isSessionExpiredReported()).toBe(false);
    expect(restored).toHaveBeenCalled();
    window.removeEventListener(AUTH_SESSION_RESTORED_EVENT, restored);
  });
});
