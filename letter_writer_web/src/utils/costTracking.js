export const COST_TRACKING_ERROR_EVENT = "cost-tracking-error-updated";

/** Extract a user-visible message from a FastAPI error response body. */
export function parseApiErrorDetail(bodyText) {
  if (!bodyText) return "Request failed";
  try {
    const json = JSON.parse(bodyText);
    const detail = json.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    }
    return json.message || bodyText;
  } catch {
    return bodyText;
  }
}

export function publishCostTrackingSignals(payload) {
  if (typeof window === "undefined" || !payload) return;

  const err = payload.cost_tracking_error;
  if (typeof err === "string" && err.trim()) {
    window.dispatchEvent(
      new CustomEvent(COST_TRACKING_ERROR_EVENT, { detail: { message: err.trim() } })
    );
  }

  const monthlyCost = payload.user_monthly_cost;
  if (typeof monthlyCost === "number" && !Number.isNaN(monthlyCost)) {
    window.dispatchEvent(
      new CustomEvent("user-monthly-cost-updated", { detail: { value: monthlyCost } })
    );
  }
}
