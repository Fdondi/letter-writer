import React, { useState, useEffect } from "react";

// Model pricing per 1M tokens (input/output) - used for cost projections
const MODEL_PRICING = {
  // OpenAI
  "gpt-4o": { input: 2.50, output: 10.00, name: "GPT-4o" },
  "gpt-4o-mini": { input: 0.15, output: 0.60, name: "GPT-4o Mini" },
  "gpt-4-turbo": { input: 10.00, output: 30.00, name: "GPT-4 Turbo" },
  "o1": { input: 15.00, output: 60.00, name: "o1" },
  "o1-mini": { input: 1.10, output: 4.40, name: "o1 Mini" },
  "o3-mini": { input: 1.10, output: 4.40, name: "o3 Mini" },
  // Anthropic
  "claude-sonnet-4": { input: 3.00, output: 15.00, name: "Claude Sonnet 4" },
  "claude-3.5-sonnet": { input: 3.00, output: 15.00, name: "Claude 3.5 Sonnet" },
  "claude-3.5-haiku": { input: 0.80, output: 4.00, name: "Claude 3.5 Haiku" },
  "claude-3-opus": { input: 15.00, output: 75.00, name: "Claude 3 Opus" },
  // Gemini
  "gemini-2.0-flash": { input: 0.10, output: 0.40, name: "Gemini 2.0 Flash" },
  "gemini-1.5-pro": { input: 1.25, output: 5.00, name: "Gemini 1.5 Pro" },
  "gemini-1.5-flash": { input: 0.075, output: 0.30, name: "Gemini 1.5 Flash" },
  // DeepSeek
  "deepseek-chat": { input: 0.14, output: 0.28, name: "DeepSeek V3" },
  "deepseek-reasoner": { input: 0.55, output: 2.19, name: "DeepSeek R1" },
  // Mistral
  "mistral-large": { input: 2.00, output: 6.00, name: "Mistral Large" },
  "mistral-small": { input: 0.20, output: 0.60, name: "Mistral Small" },
  // Grok
  "grok-2": { input: 2.00, output: 10.00, name: "Grok 2" },
  "grok-3-mini": { input: 0.30, output: 0.50, name: "Grok 3 Mini" },
};

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
  const [months, setMonths] = useState(1);
  const [projectionModel, setProjectionModel] = useState("gpt-4o");

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

  const formatTokens = (tokens) => {
    if (!tokens) return "0";
    if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
    if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
    return tokens.toString();
  };

  // Calculate what it would cost with a different model
  const calculateProjection = (inputTokens, outputTokens, modelKey) => {
    const pricing = MODEL_PRICING[modelKey];
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
              <optgroup label="OpenAI">
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="gpt-4-turbo">GPT-4 Turbo</option>
                <option value="o1">o1</option>
                <option value="o1-mini">o1 Mini</option>
              </optgroup>
              <optgroup label="Anthropic">
                <option value="claude-sonnet-4">Claude Sonnet 4</option>
                <option value="claude-3.5-sonnet">Claude 3.5 Sonnet</option>
                <option value="claude-3.5-haiku">Claude 3.5 Haiku</option>
                <option value="claude-3-opus">Claude 3 Opus</option>
              </optgroup>
              <optgroup label="Google">
                <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
                <option value="gemini-1.5-pro">Gemini 1.5 Pro</option>
                <option value="gemini-1.5-flash">Gemini 1.5 Flash</option>
              </optgroup>
              <optgroup label="DeepSeek">
                <option value="deepseek-chat">DeepSeek V3</option>
                <option value="deepseek-reasoner">DeepSeek R1</option>
              </optgroup>
              <optgroup label="Mistral">
                <option value="mistral-large">Mistral Large</option>
                <option value="mistral-small">Mistral Small</option>
              </optgroup>
              <optgroup label="xAI">
                <option value="grok-2">Grok 2</option>
                <option value="grok-3-mini">Grok 3 Mini</option>
              </optgroup>
            </select>
          </div>
          
          <div style={{ fontSize: 14, color: "var(--secondary-text-color)" }}>
            With your token usage ({formatTokens(userCosts.total_input_tokens)} in / {formatTokens(userCosts.total_output_tokens)} out), 
            using <strong>{MODEL_PRICING[projectionModel]?.name}</strong> exclusively would cost:
          </div>
          
          <div style={{ 
            fontSize: 28, 
            fontWeight: 600, 
            color: "var(--text-color)",
            marginTop: 8,
            textAlign: "center"
          }}>
            {formatCost(calculateProjection(
              userCosts.total_input_tokens || 0,
              userCosts.total_output_tokens || 0,
              projectionModel
            ))}
            <span style={{ fontSize: 14, color: "var(--secondary-text-color)", marginLeft: 8 }}>
              (actual: {formatCost(userCosts.total_cost || 0)})
            </span>
          </div>
          
          <div style={{ fontSize: 12, color: "var(--secondary-text-color)", marginTop: 8, textAlign: "center" }}>
            @ ${MODEL_PRICING[projectionModel]?.input}/1M input, ${MODEL_PRICING[projectionModel]?.output}/1M output
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
