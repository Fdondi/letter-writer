import { useEffect, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { getScaleConfig } from "../utils/competenceScales";
import { showNotification } from "../utils/apiNotifications";

const STORAGE_KEY = "letter-writer-capture-id";

function readCaptureId(search) {
  const fromQuery = new URLSearchParams(search || "").get("capture");
  if (fromQuery) {
    try {
      sessionStorage.setItem(STORAGE_KEY, fromQuery);
    } catch {
      /* ignore quota / private mode */
    }
    return fromQuery;
  }
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function clearStoredCaptureId() {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * After login, process a ?capture= id from the browser extension and fill intake.
 */
export function useJobCapture({
  checkingAuth,
  isAuthenticated,
  applyCapturePayload,
  setExtracting,
  setCaptureImporting,
  setExtractionError,
  setSourceUrl,
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const startedRef = useRef(null);

  useEffect(() => {
    if (checkingAuth) return undefined;
    const captureId = readCaptureId(location.search);
    if (!captureId) return undefined;
    if (!isAuthenticated) return undefined;
    if (startedRef.current === captureId) return undefined;
    startedRef.current = captureId;

    let cancelled = false;
    setCaptureImporting?.(true);
    setExtracting?.(true);
    setExtractionError?.(null);

    (async () => {
      try {
        try {
          const meta = await fetchWithHeartbeat(`/api/job-capture/${encodeURIComponent(captureId)}/`);
          const url = String(meta.data?.source_url || meta.data?.url || "").trim();
          if (!cancelled && url) {
            setSourceUrl?.(url);
          }
        } catch (peekErr) {
          console.warn("Job capture URL peek failed:", peekErr);
        }
        if (cancelled) return;

        const scaleConfig = getScaleConfig();
        const result = await fetchWithHeartbeat(`/api/job-capture/${encodeURIComponent(captureId)}/process/`, {
          method: "POST",
          body: JSON.stringify({
            scale_config: {
              need: scaleConfig.need,
              level: scaleConfig.level,
              needSemantics: scaleConfig.needSemantics || {},
            },
          }),
        });
        if (cancelled) return;
        applyCapturePayload?.(result.data);
        clearStoredCaptureId();
        if (location.search.includes("capture=")) {
          navigate("/", { replace: true });
        }
        showNotification(
          result.data?.synthetic
            ? "Imported captured page text (harness, no LLM extract)"
            : "Imported job from browser"
        );
      } catch (e) {
        console.error("Job capture import failed:", e);
        if (!cancelled) {
          setExtractionError?.(e?.message || String(e));
          startedRef.current = null;
        }
      } finally {
        if (!cancelled) {
          setExtracting?.(false);
          setCaptureImporting?.(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [
    checkingAuth,
    isAuthenticated,
    location.search,
    applyCapturePayload,
    setExtracting,
    setCaptureImporting,
    setExtractionError,
    setSourceUrl,
    navigate,
  ]);
}
