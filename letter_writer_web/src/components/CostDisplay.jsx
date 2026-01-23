import React, { useState, useEffect } from "react";

/**
 * Displays the user's total API cost for the current month.
 * Fetches from BigQuery via /api/costs/user/ endpoint.
 */
export default function CostDisplay() {
  const [cost, setCost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchCost();
    
    // Refresh every 5 minutes
    const interval = setInterval(fetchCost, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const fetchCost = async () => {
    try {
      const res = await fetch("/api/costs/user/?months=1", {
        credentials: "include",
      });
      
      if (res.status === 401) {
        // Not authenticated - don't show anything
        setCost(null);
        setLoading(false);
        return;
      }
      
      if (!res.ok) {
        throw new Error("Failed to fetch cost");
      }
      
      const data = await res.json();
      setCost(data.total_cost || 0);
      setError(null);
    } catch (err) {
      console.warn("Could not fetch cost:", err);
      setError(err.message);
      setCost(null);
    } finally {
      setLoading(false);
    }
  };

  // Don't render if not authenticated or loading
  if (loading || cost === null) {
    return null;
  }

  // Format cost
  const formattedCost = cost < 0.01 && cost > 0
    ? "< $0.01"
    : `$${cost.toFixed(2)}`;

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
      }}
      title={`Your API usage this month: ${formattedCost}\nClick to refresh`}
      onClick={fetchCost}
      role="button"
      tabIndex={0}
    >
      <span style={{ opacity: 0.7 }}>💰</span>
      <span>{formattedCost}</span>
      <span style={{ opacity: 0.5, fontSize: "10px" }}>/mo</span>
    </div>
  );
}
