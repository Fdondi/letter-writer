import { useEffect, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { applyRestoredSessionState } from "../utils/applySessionRestore";
import { showNotification } from "../utils/apiNotifications";

/**
 * On browser reload/back-forward, recover session from server when the intake form is still pristine.
 */
export function useSessionRehydration({
  checkingAuth,
  isAuthenticated,
  isFormSnapshotPristine,
  latestFormSnapshotRef,
  sessionSetters,
  setPendingVendorRestore,
  setPendingAgenticRestore,
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const rehydrationAttemptedRef = useRef(false);

  useEffect(() => {
    if (rehydrationAttemptedRef.current) return;
    if (checkingAuth || !isAuthenticated) return;

    const navEntry = performance.getEntriesByType("navigation")?.[0];
    const navType = navEntry?.type || "navigate";
    const isReloadLikeNav = navType === "reload" || navType === "back_forward";
    if (!isReloadLikeNav) {
      rehydrationAttemptedRef.current = true;
      return;
    }

    if (!isFormSnapshotPristine(latestFormSnapshotRef.current)) {
      rehydrationAttemptedRef.current = true;
      return;
    }

    rehydrationAttemptedRef.current = true;
    let cancelled = false;
    const onAgenticRoute = location.pathname.startsWith("/flows/agentic");

    (async () => {
      try {
        const [sessionRes, agenticRes] = await Promise.all([
          fetch("/api/phases/state/", { credentials: "include" }),
          onAgenticRoute
            ? fetch("/api/phases/agentic/state/", { credentials: "include" })
            : Promise.resolve(null),
        ]);
        if (cancelled || !sessionRes.ok) return;

        const sessionPayload = await sessionRes.json();
        if (cancelled) return;

        if (!isFormSnapshotPristine(latestFormSnapshotRef.current)) return;

        const sessionId = sessionPayload?.session_id;
        const state = { ...(sessionPayload?.session_state || {}) };

        if (onAgenticRoute && agenticRes && agenticRes.ok) {
          const agenticPayload = await agenticRes.json();
          if (cancelled) return;
          if (agenticPayload?.agentic_state) {
            state.agentic = agenticPayload.agentic_state;
          }
        }

        const result = applyRestoredSessionState(state, sessionSetters, { sessionId });
        if (!result.restored) return;

        if (result.vendor) {
          setPendingVendorRestore(result.vendor);
          if (!location.pathname.startsWith("/flows/vendors")) {
            navigate("/flows/vendors", { replace: true, state: { rehydrated: true } });
          }
        }

        if (result.agentic) {
          setPendingAgenticRestore(result.agentic);
          if (!location.pathname.startsWith("/flows/agentic")) {
            navigate("/flows/agentic", { replace: true, state: { rehydrated: true } });
          }
        }

        showNotification("Recovered previous session after browser reload");
      } catch (e) {
        console.warn("Reload rehydration skipped:", e);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    checkingAuth,
    isAuthenticated,
    isFormSnapshotPristine,
    latestFormSnapshotRef,
    sessionSetters,
    setPendingVendorRestore,
    setPendingAgenticRestore,
    navigate,
    location.pathname,
  ]);
}
