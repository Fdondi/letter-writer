import React, { useState, useEffect } from "react";

/**
 * Detailed cost breakdown page showing:
 * - Total cost this month
 * - Breakdown by vendor/service
 * - Breakdown by day
 */
export default function CostsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userCosts, setUserCosts] = useState(null);
  const [dailyCosts, setDailyCosts] = useState(null);
  const [months, setMonths] = useState(1);

  useEffect(() => {
    fetchCosts();
  }, [months]);

  const fetchCosts = async () => {
    setLoading(true);
    setError(null);
    
    try {
      // Fetch user costs summary
      const userRes = await fetch(`/api/costs/user/?months=${months}`, {
        credentials: "include",
      });
      
      if (!userRes.ok) {
        throw new Error("Failed to fetch cost data");
      }
      
      const userData = await userRes.json();
      setUserCosts(userData);
      
      // Fetch daily breakdown
      const dailyRes = await fetch(`/api/costs/daily/?months=${months}`, {
        credentials: "include",
      });
      
      if (dailyRes.ok) {
        const dailyData = await dailyRes.json();
        setDailyCosts(dailyData);
      }
      
    } catch (err) {
      console.error("Error fetching costs:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatCost = (cost) => {
    if (cost === 0) return "$0.00";
    if (cost < 0.01) return "< $0.01";
    return `$${cost.toFixed(2)}`;
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", { 
      month: "short", 
      day: "numeric",
      weekday: "short"
    });
  };

  // Service name formatting
  const formatServiceName = (service) => {
    if (service === "translate") return "Translation";
    if (service.startsWith("background_")) return `${service.replace("background_", "")} (research)`;
    if (service.startsWith("draft_")) return `${service.replace("draft_", "")} (draft)`;
    if (service.startsWith("refine_")) return `${service.replace("refine_", "")} (refine)`;
    return service;
  };

  // Group services by vendor
  const groupByVendor = (byService) => {
    const vendors = {};
    
    for (const [service, data] of Object.entries(byService || {})) {
      let vendor = service;
      
      if (service === "translate") {
        vendor = "translate";
      } else if (service.includes("_")) {
        vendor = service.split("_").slice(1).join("_");
      }
      
      if (!vendors[vendor]) {
        vendors[vendor] = { total_cost: 0, request_count: 0, phases: {} };
      }
      
      vendors[vendor].total_cost += data.total_cost;
      vendors[vendor].request_count += data.request_count;
      vendors[vendor].phases[service] = data;
    }
    
    return vendors;
  };

  if (loading) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <p>Loading cost data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 20 }}>
        <div style={{ 
          padding: 16, 
          backgroundColor: "var(--error-bg)", 
          border: "1px solid var(--error-border)",
          borderRadius: 8,
          color: "#ef4444"
        }}>
          Error: {error}
        </div>
      </div>
    );
  }

  const vendorBreakdown = groupByVendor(userCosts?.by_service);

  return (
    <div style={{ padding: 20, maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>API Costs</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ fontSize: 14 }}>Period:</label>
          <select
            value={months}
            onChange={(e) => setMonths(parseInt(e.target.value))}
            style={{
              padding: "6px 12px",
              borderRadius: 4,
              border: "1px solid var(--border-color)",
              backgroundColor: "var(--input-bg)",
              color: "var(--text-color)",
            }}
          >
            <option value={1}>Last month</option>
            <option value={3}>Last 3 months</option>
            <option value={6}>Last 6 months</option>
            <option value={12}>Last year</option>
          </select>
          <button
            onClick={fetchCosts}
            style={{
              padding: "6px 12px",
              borderRadius: 4,
              border: "1px solid var(--border-color)",
              backgroundColor: "var(--button-bg)",
              color: "var(--button-text)",
              cursor: "pointer",
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Total Cost Card */}
      <div style={{
        padding: 20,
        backgroundColor: "var(--card-bg)",
        border: "1px solid var(--border-color)",
        borderRadius: 8,
        marginBottom: 20,
        textAlign: "center",
      }}>
        <div style={{ fontSize: 14, color: "var(--secondary-text-color)", marginBottom: 8 }}>
          Total Cost ({months === 1 ? "This Month" : `Last ${months} Months`})
        </div>
        <div style={{ fontSize: 36, fontWeight: 700, color: "var(--text-color)" }}>
          {formatCost(userCosts?.total_cost || 0)}
        </div>
        {userCosts?.pending_cost > 0 && (
          <div style={{ fontSize: 12, color: "var(--secondary-text-color)", marginTop: 4 }}>
            (includes {formatCost(userCosts.pending_cost)} pending)
          </div>
        )}
        <div style={{ fontSize: 12, color: "var(--secondary-text-color)", marginTop: 8 }}>
          {userCosts?.total_requests || 0} API requests
        </div>
      </div>

      {/* Two column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        
        {/* By Vendor */}
        <div style={{
          padding: 16,
          backgroundColor: "var(--card-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: 8,
        }}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: 16 }}>By Vendor</h3>
          
          {Object.keys(vendorBreakdown).length === 0 ? (
            <p style={{ color: "var(--secondary-text-color)", fontSize: 14 }}>No cost data yet</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {Object.entries(vendorBreakdown)
                .sort((a, b) => b[1].total_cost - a[1].total_cost)
                .map(([vendor, data]) => (
                  <div key={vendor}>
                    <div style={{ 
                      display: "flex", 
                      justifyContent: "space-between", 
                      alignItems: "center",
                      marginBottom: 4,
                    }}>
                      <span style={{ 
                        fontWeight: 600, 
                        textTransform: "capitalize",
                        fontSize: 14,
                      }}>
                        {vendor === "translate" ? "🌐 Translation" : `🤖 ${vendor}`}
                      </span>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>
                        {formatCost(data.total_cost)}
                      </span>
                    </div>
                    
                    {/* Phase breakdown */}
                    <div style={{ paddingLeft: 16, fontSize: 12, color: "var(--secondary-text-color)" }}>
                      {Object.entries(data.phases).map(([phase, phaseData]) => (
                        <div key={phase} style={{ display: "flex", justifyContent: "space-between" }}>
                          <span>{formatServiceName(phase)}</span>
                          <span>{formatCost(phaseData.total_cost)} ({phaseData.request_count})</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>

        {/* By Day */}
        <div style={{
          padding: 16,
          backgroundColor: "var(--card-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: 8,
        }}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: 16 }}>By Day</h3>
          
          {!dailyCosts?.days || dailyCosts.days.length === 0 ? (
            <p style={{ color: "var(--secondary-text-color)", fontSize: 14 }}>No daily data yet</p>
          ) : (
            <div style={{ 
              display: "flex", 
              flexDirection: "column", 
              gap: 8,
              maxHeight: 400,
              overflowY: "auto",
            }}>
              {dailyCosts.days
                .sort((a, b) => new Date(b.date) - new Date(a.date))
                .map((day) => (
                  <div 
                    key={day.date}
                    style={{ 
                      display: "flex", 
                      justifyContent: "space-between",
                      padding: "8px 12px",
                      backgroundColor: "var(--panel-bg)",
                      borderRadius: 4,
                      fontSize: 14,
                    }}
                  >
                    <span>{formatDate(day.date)}</span>
                    <div style={{ textAlign: "right" }}>
                      <span style={{ fontWeight: 600 }}>{formatCost(day.total_cost)}</span>
                      <span style={{ 
                        fontSize: 12, 
                        color: "var(--secondary-text-color)",
                        marginLeft: 8,
                      }}>
                        ({day.request_count} req)
                      </span>
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* Service Details Table */}
      <div style={{
        marginTop: 20,
        padding: 16,
        backgroundColor: "var(--card-bg)",
        border: "1px solid var(--border-color)",
        borderRadius: 8,
      }}>
        <h3 style={{ margin: "0 0 16px 0", fontSize: 16 }}>Service Details</h3>
        
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
              <th style={{ textAlign: "left", padding: "8px 12px" }}>Service</th>
              <th style={{ textAlign: "right", padding: "8px 12px" }}>Requests</th>
              <th style={{ textAlign: "right", padding: "8px 12px" }}>Cost</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(userCosts?.by_service || {})
              .sort((a, b) => b[1].total_cost - a[1].total_cost)
              .map(([service, data]) => (
                <tr key={service} style={{ borderBottom: "1px solid var(--border-color)" }}>
                  <td style={{ padding: "8px 12px" }}>{formatServiceName(service)}</td>
                  <td style={{ textAlign: "right", padding: "8px 12px" }}>{data.request_count}</td>
                  <td style={{ textAlign: "right", padding: "8px 12px", fontWeight: 600 }}>
                    {formatCost(data.total_cost)}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
