import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

export const FLOW_LEAVE_PROMPT =
  "Go back to job details? This screen will close. Open the same flow again to bring the generated letters back.";

/**
 * Trackpad and browser Back fire popstate and unmount the flow immediately.
 * A duplicate history entry absorbs that first swipe. The capture listener
 * runs before React Router, puts the flow URL back, and only leaves after confirm.
 */
export function useFlowHistoryGuard({ enabled, onLeave }) {
  const location = useLocation();
  const onLeaveRef = useRef(onLeave);
  const allowLeaveRef = useRef(false);
  onLeaveRef.current = onLeave;

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return undefined;
    // MemoryRouter tests do not mirror the route into window.location.
    if (window.location.pathname !== location.pathname) return undefined;

    const href = `${location.pathname}${location.search}${location.hash}`;
    const arm = () => {
      const prev = window.history.state;
      const state =
        prev && typeof prev === "object"
          ? { ...prev, lwHistoryGuard: true }
          : { lwHistoryGuard: true };
      window.history.pushState(state, "", href);
    };
    arm();

    const onPop = (event) => {
      if (allowLeaveRef.current) return;
      event.stopImmediatePropagation();
      arm();
      if (!window.confirm(FLOW_LEAVE_PROMPT)) return;
      allowLeaveRef.current = true;
      onLeaveRef.current?.();
    };

    window.addEventListener("popstate", onPop, true);
    return () => window.removeEventListener("popstate", onPop, true);
  }, [enabled, location.pathname, location.search, location.hash]);

  return () => {
    allowLeaveRef.current = true;
  };
}
