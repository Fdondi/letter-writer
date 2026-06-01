import React, { useState, useEffect } from "react";
import { USER_MONTHLY_COST_EVENT } from "../utils/apiHelpers";
import { COST_TRACKING_ERROR_EVENT, parseApiErrorDetail } from "../utils/costTracking";

/**
 * Displays the user's total API cost for the current month.
 * Fetches from BigQuery via /api/costs/user/ endpoint.
 *
 * @param {function} onNavigate - Called when user clicks to view details
 */
export default function CostDisplay({ onNavigate }) {
  const [cost, setCost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchCost();

    const handleCostUpdate = (event) => {
      const nextCost = event?.detail?.value;
      if (typeof nextCost === "number" && !Number.isNaN(nextCost)) {
        setCost(nextCost);
        setError(null);
        setLoading(false);
      }
    };

    const handleCostError = (event) => {
      const message = event?.detail?.message;
      if (message) {
        setError(message);
        setLoading(false);
      }
    };

    window.addEventListener(USER_MONTHLY_COST_EVENT, handleCostUpdate);
    window.addEventListener(COST_TRACKING_ERROR_EVENT, handleCostError);
    return () => {
      window.removeEventListener(USER_MONTHLY_COST_EVENT, handleCostUpdate);
      window.removeEventListener(COST_TRACKING_ERROR_EVENT, handleCostError);
    };
  }, []);

  const fetchCost = async () => {
    try {
      const res = await fetch("/api/costs/user/?months=1", {
        credentials: "include",
      });

      if (res.status === 401) {
        setCost(null);
        setError(null);
        setLoading(false);
        return;
      }

      const text = await res.text();
      if (!res.ok) {
        throw new Error(parseApiErrorDetail(text));
      }

      const data = JSON.parse(text);
      if (data.error || data.cost_available === false) {
        throw new Error(data.error || "Cost analytics unavailable");
      }

      setCost(data.total_cost ?? 0);
      setError(null);
    } catch (err) {
      console.warn("Could not fetch cost:", err);
      setError(err.message || String(err));
      setCost(null);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return null;
  }

  if (error) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          padding: "4px 10px",
          backgroundColor: "var(--error-bg, #fef2f2)",
          border: "1px solid var(--error-border, #fecaca)",
          borderRadius: "4px",
          fontSize: "11px",
          color: "var(--error-text, #b91c1c)",
          maxWidth: 220,
          cursor: onNavigate ? "pointer" : "default",
        }}
        title={error}
        onClick={onNavigate}
        role="alert"
      >
        <span>⚠️</span>
        <span>Costs unavailable</span>
      </div>
    );
  }

  if (cost === null) {
    return null;
  }

  const formattedCost = cost < 0.01 && cost > 0
    ? "< $0.01"
    : `$${cost.toFixed(2)}`;

  const handleClick = () => {
    if (onNavigate) {
      onNavigate();
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        padding: "4px 10px",
        backgroundColor: "var(--panel-bg)",
        border: "1px solid var(--border-color)",
        borderRadius: "4px",
        fontSize: "12px",
        color: "var(--secondary-text-color)",
        cursor: onNavigate ? "pointer" : "default",
      }}
      title={`Your API usage this month: ${formattedCost}\nClick for details`}
      onClick={handleClick}
      role="button"
      tabIndex={0}
    >
      <span style={{ opacity: 0.7 }}>💰</span>
      <span>{formattedCost}</span>
      <span style={{ opacity: 0.5, fontSize: "10px" }}>/mo</span>
    </div>
  );
}
