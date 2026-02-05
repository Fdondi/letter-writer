import React, { useState, useEffect } from "react";

/**
 * Detailed cost breakdown page showing:
 * - Total cost this month
 * - Breakdown by vendor/service
 * - Breakdown by day
 * - Token usage statistics
 * - Cost projections for different models
 */
export default function CostsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userCosts, setUserCosts] = useState(null);
  const [dailyCosts, setDailyCosts] = useState(null);
  const [modelPricing, setModelPricing] = useState(null); // { vendor -> [{id, name, input, output}] }
  const [months, setMonths] = useState(1);
  const [projectionModel, setProjectionModel] = useState("");

  useEffect(() => {
    fetchCosts();
  }, [months]);

  useEffect(() => {
    fetch("/api/costs/models/", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : {}))
      .then((data) => {
        const models = data.models || data;
        setModelPricing(models);
        // Set default projection model to first available
        if (Object.keys(models).length > 0) {
          const firstVendor = Object.keys(models)[0];
          const firstModel = models[firstVendor]?.[0];
          if (firstModel) {
            setProjectionModel((prev) => (prev ? prev : firstModel.id));
          }
        }
      })
      .catch(() => setModelPricing({}));
  }, []);

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

  const formatTokens = (tokens) => {
    if (!tokens) return "0";
    if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
    if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
    return tokens.toString();
  };

  // Build flat map modelId -> {input, output, name} from vendor-grouped pricing
  const modelMap = React.useMemo(() => {
    if (!modelPricing) return {};
    const map = {};
    for (const models of Object.values(modelPricing)) {
      for (const m of models) {
        map[m.id] = { input: m.input, output: m.output, name: m.name };
      }
    }
    return map;
  }, [modelPricing]);

  // Calculate what it would cost with a different model
  const calculateProjection = (inputTokens, outputTokens, modelKey) => {
    const pricing = modelMap[modelKey];
    if (!pricing) return 0;
    return (inputTokens / 1_000_000) * pricing.input + (outputTokens / 1_000_000) * pricing.output;
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", { 
      month: "short", 
      day: "numeric",
      weekday: "short"
    });
  };

  // Phase name formatting
  const formatPhaseName = (phase) => {
    const names = {
      background: "Research",
      draft: "Draft",
      feedback: "Feedback",
      refine: "Refine",
      translate: "Translation",
      extract: "Extraction"
    };
    return names[phase] || phase;
  };

  // Vendor name formatting
  const formatVendorName = (vendor) => {
    const names = {
      openai: "OpenAI",
      anthropic: "Anthropic",
      gemini: "Google Gemini",
      mistral: "Mistral",
      grok: "xAI Grok",
      deepseek: "DeepSeek",
      google_translate: "Google Translate"
    };
    return names[vendor] || vendor;
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

  // Use new structure: by_phase and by_vendor directly from API
  const byPhase = userCosts?.by_phase || {};
  const byVendor = userCosts?.by_vendor || {};

  return (
    <div style={{ padding: 20, maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", marginBottom: 20 }}>
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
      }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20, textAlign: "center" }}>
          {/* Cost */}
          <div>
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
          </div>
          
          {/* Input Tokens */}
          <div>
            <div style={{ fontSize: 14, color: "var(--secondary-text-color)", marginBottom: 8 }}>
              Input Tokens
            </div>
            <div style={{ fontSize: 28, fontWeight: 600, color: "var(--text-color)" }}>
              {formatTokens(userCosts?.total_input_tokens || 0)}
            </div>
            <div style={{ fontSize: 12, color: "var(--secondary-text-color)", marginTop: 4 }}>
              prompt/context
            </div>
          </div>
          
          {/* Output Tokens */}
          <div>
            <div style={{ fontSize: 14, color: "var(--secondary-text-color)", marginBottom: 8 }}>
              Output Tokens
            </div>
            <div style={{ fontSize: 28, fontWeight: 600, color: "var(--text-color)" }}>
              {formatTokens(userCosts?.total_output_tokens || 0)}
            </div>
            <div style={{ fontSize: 12, color: "var(--secondary-text-color)", marginTop: 4 }}>
              generated text
            </div>
          </div>
        </div>
        
        <div style={{ textAlign: "center", fontSize: 12, color: "var(--secondary-text-color)", marginTop: 12 }}>
          {userCosts?.total_requests || 0} API requests
        </div>
      </div>

      {/* Cost Projection */}
      {(userCosts?.total_input_tokens > 0 || userCosts?.total_output_tokens > 0) && (
        <div style={{
          padding: 16,
          backgroundColor: "var(--card-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: 8,
          marginBottom: 20,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>Cost Projection</h3>
            <select
              value={projectionModel}
              onChange={(e) => setProjectionModel(e.target.value)}
              style={{
                padding: "6px 12px",
                borderRadius: 4,
                border: "1px solid var(--border-color)",
                backgroundColor: "var(--input-bg)",
                color: "var(--text-color)",
              }}
            >
              {modelPricing && Object.keys(modelPricing).length > 0 ? (
                Object.entries(modelPricing).map(([vendor, models]) => (
                  <optgroup key={vendor} label={vendor}>
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </optgroup>
                ))
              ) : (
                <option value="">
                  {modelPricing ? "No models" : "Loading models…"}
                </option>
              )}
            </select>
          </div>
          
          <div style={{ fontSize: 14, color: "var(--secondary-text-color)" }}>
            With your token usage ({formatTokens(userCosts.total_input_tokens)} in / {formatTokens(userCosts.total_output_tokens)} out), 
            using <strong>{modelMap[projectionModel]?.name ?? projectionModel ?? "—"}</strong> exclusively would cost:
          </div>
          
          <div style={{ 
            fontSize: 28, 
            fontWeight: 600, 
            color: "var(--text-color)",
            marginTop: 8,
            textAlign: "center"
          }}>
            {projectionModel && modelMap[projectionModel]
              ? formatCost(calculateProjection(
                  userCosts.total_input_tokens || 0,
                  userCosts.total_output_tokens || 0,
                  projectionModel
                ))
              : "—"}
            <span style={{ fontSize: 14, color: "var(--secondary-text-color)", marginLeft: 8 }}>
              (actual: {formatCost(userCosts.total_cost || 0)})
            </span>
          </div>
          
          <div style={{ fontSize: 12, color: "var(--secondary-text-color)", marginTop: 8, textAlign: "center" }}>
            @ ${modelMap[projectionModel]?.input ?? "—"}/1M input, ${modelMap[projectionModel]?.output ?? "—"}/1M output
          </div>
        </div>
      )}

      {/* Two column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        
        {/* By Phase */}
        <div style={{
          padding: 16,
          backgroundColor: "var(--card-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: 8,
        }}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: 16 }}>By Phase</h3>
          
          {Object.keys(byPhase).length === 0 ? (
            <p style={{ color: "var(--secondary-text-color)", fontSize: 14 }}>No cost data yet</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {Object.entries(byPhase)
                .sort((a, b) => b[1].total_cost - a[1].total_cost)
                .map(([phase, data]) => (
                  <div 
                    key={phase}
                    style={{ 
                      display: "flex", 
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "8px 12px",
                      backgroundColor: "var(--panel-bg)",
                      borderRadius: 4,
                    }}
                  >
                    <span style={{ fontWeight: 500, fontSize: 14 }}>
                      {formatPhaseName(phase)}
                    </span>
                    <div style={{ textAlign: "right" }}>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>
                        {formatCost(data.total_cost)}
                      </span>
                      {(data.input_tokens > 0 || data.output_tokens > 0) && (
                        <div style={{ fontSize: 11, color: "var(--secondary-text-color)" }}>
                          {formatTokens(data.input_tokens)} in / {formatTokens(data.output_tokens)} out
                        </div>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>

        {/* By Vendor */}
        <div style={{
          padding: 16,
          backgroundColor: "var(--card-bg)",
          border: "1px solid var(--border-color)",
          borderRadius: 8,
        }}>
          <h3 style={{ margin: "0 0 16px 0", fontSize: 16 }}>By Vendor</h3>
          
          {Object.keys(byVendor).length === 0 ? (
            <p style={{ color: "var(--secondary-text-color)", fontSize: 14 }}>No cost data yet</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {Object.entries(byVendor)
                .sort((a, b) => b[1].total_cost - a[1].total_cost)
                .map(([vendor, data]) => (
                  <div 
                    key={vendor}
                    style={{ 
                      display: "flex", 
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "8px 12px",
                      backgroundColor: "var(--panel-bg)",
                      borderRadius: 4,
                    }}
                  >
                    <span style={{ fontWeight: 500, fontSize: 14 }}>
                      {vendor === "google_translate" ? "🌐 " : "🤖 "}
                      {formatVendorName(vendor)}
                    </span>
                    <div style={{ textAlign: "right" }}>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>
                        {formatCost(data.total_cost)}
                      </span>
                      {(data.input_tokens > 0 || data.output_tokens > 0) && (
                        <div style={{ fontSize: 11, color: "var(--secondary-text-color)" }}>
                          {formatTokens(data.input_tokens)} in / {formatTokens(data.output_tokens)} out
                        </div>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* By Day */}
      <div style={{
        marginTop: 20,
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
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
            gap: 8,
            maxHeight: 300,
            overflowY: "auto",
          }}>
            {dailyCosts.days
              .sort((a, b) => new Date(b.date) - new Date(a.date))
              .map((day) => (
                <div 
                  key={day.date}
                  style={{ 
                    padding: "8px 12px",
                    backgroundColor: "var(--panel-bg)",
                    borderRadius: 4,
                    fontSize: 14,
                  }}
                >
                  <div style={{ fontSize: 12, color: "var(--secondary-text-color)" }}>
                    {formatDate(day.date)}
                  </div>
                  <div style={{ fontWeight: 600 }}>{formatCost(day.total_cost)}</div>
                  <div style={{ fontSize: 11, color: "var(--secondary-text-color)" }}>
                    {day.request_count} requests
                  </div>
                </div>
              ))}
          </div>
        )}
      </div>

    </div>
  );
}
