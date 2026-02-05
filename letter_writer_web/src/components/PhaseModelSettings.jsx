import React, { useState, useEffect } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

const PHASE_LABELS = {
  background: "Research",
  draft: "Draft",
  feedback: "Feedback",
  refine: "Refinement",
};

const VENDOR_LABELS = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google",
  mistral: "Mistral",
  grok: "xAI",
  deepseek: "DeepSeek",
};

function formatCost(cost) {
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return "< $0.01";
  return `$${cost.toFixed(2)}`;
}

export default function PhaseModelSettings({
  vendors = [],
  phaseModelOverrides = {},
  onSaveOverrides,
  personalDataLoaded,
}) {
  const [modelPricing, setModelPricing] = useState(null); // { models: {...}, phase_defaults: {...} }
  const [userCosts, setUserCosts] = useState(null);
  const [localOverrides, setLocalOverrides] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLocalOverrides(phaseModelOverrides);
  }, [phaseModelOverrides]);

  useEffect(() => {
    fetch("/api/costs/models/", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : {}))
      .then((data) => setModelPricing(data))
      .catch(() => setModelPricing(null));
  }, []);

  useEffect(() => {
    fetch("/api/costs/user/?months=1", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setUserCosts(data))
      .catch(() => setUserCosts(null));
  }, []);

  const modelsByVendor = React.useMemo(() => {
    if (!modelPricing?.models) return {};
    const map = {};
    for (const models of Object.values(modelPricing.models)) {
      if (!Array.isArray(models)) continue;
      for (const m of models) {
        const v = m.vendor;
        if (v) {
          if (!map[v]) map[v] = [];
          map[v].push(m);
        }
      }
    }
    return map;
  }, [modelPricing]);

  const phaseDefaults = modelPricing?.phase_defaults || {};
  const byPhaseByVendor = userCosts?.by_phase_by_vendor || {};

  const getModelForPhaseVendor = (phase, vendor) => {
    return (
      localOverrides[phase]?.[vendor] ??
      phaseDefaults[phase]?.[vendor] ??
      ""
    );
  };

  const setModelForPhaseVendor = (phase, vendor, modelId) => {
    setLocalOverrides((prev) => {
      const next = { ...prev };
      if (!next[phase]) next[phase] = {};
      if (modelId) {
        next[phase] = { ...next[phase], [vendor]: modelId };
      } else {
        const { [vendor]: _, ...rest } = next[phase];
        next[phase] = Object.keys(rest).length ? rest : undefined;
      }
      if (!next[phase]) delete next[phase];
      return next;
    });
  };

  const calculateProjectedCost = (inputTokens, outputTokens, searchQueries, modelId) => {
    if (!modelId || !modelPricing?.models) return 0;
    let pricing = null;
    for (const models of Object.values(modelPricing.models)) {
      const m = models.find((x) => x.id === modelId);
      if (m) {
        pricing = m;
        break;
      }
    }
    if (!pricing) return 0;
    const tokenCost =
      (inputTokens / 1_000_000) * (pricing.input || 0) +
      (outputTokens / 1_000_000) * (pricing.output || 0);
    const searchCost = ((searchQueries || 0) / 1_000) * (pricing.search || 0);
    return tokenCost + searchCost;
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({ phase_model_overrides: localOverrides }),
      });
      onSaveOverrides?.(localOverrides);
    } catch (e) {
      setError("Failed to save phase model settings");
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = JSON.stringify(localOverrides) !== JSON.stringify(phaseModelOverrides);
  const phases = ["background", "draft", "feedback", "refine"];
  const vendorsToShow = vendors.length > 0 ? vendors : Object.keys(VENDOR_LABELS);

  return (
    <div
      style={{
        marginBottom: 30,
        padding: 20,
        backgroundColor: "var(--bg-color)",
        border: "1px solid var(--border-color)",
        borderRadius: "4px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 15,
        }}
      >
        <h3 style={{ margin: 0, color: "var(--text-color)" }}>
          Model per Phase
        </h3>
        <button
          onClick={handleSave}
          disabled={saving || !hasChanges}
          style={{
            padding: "6px 12px",
            backgroundColor: "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: saving || !hasChanges ? "not-allowed" : "pointer",
            opacity: saving || !hasChanges ? 0.7 : 1,
            fontSize: "14px",
          }}
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
      <p
        style={{
          marginTop: 0,
          marginBottom: 15,
          fontSize: "14px",
          color: "var(--secondary-text-color)",
        }}
      >
        Override the model used for each phase. Cost projection compares your last month&apos;s token usage with the selected model&apos;s pricing.
      </p>

      {error && (
        <div
          style={{
            padding: 8,
            marginBottom: 12,
            backgroundColor: "#fee",
            color: "#c33",
            borderRadius: 4,
            fontSize: 14,
          }}
        >
          {error}
        </div>
      )}

      {!modelPricing?.models ? (
        <p style={{ color: "var(--secondary-text-color)", fontSize: 14 }}>
          Loading model pricing…
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {phases.map((phase) => (
            <div
              key={phase}
              style={{
                padding: 12,
                backgroundColor: "var(--panel-bg)",
                borderRadius: 4,
                border: "1px solid var(--border-color)",
              }}
            >
              <div
                style={{
                  fontWeight: 600,
                  marginBottom: 10,
                  color: "var(--text-color)",
                  fontSize: 14,
                }}
              >
                {PHASE_LABELS[phase] || phase}
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "100px 1fr 120px 100px",
                  gap: 12,
                  alignItems: "center",
                  fontSize: 13,
                  color: "var(--secondary-text-color)",
                }}
              >
                <span>Vendor</span>
                <span>Model</span>
                <span>Actual (last mo.)</span>
                <span>Projected</span>
              </div>
              {vendorsToShow.map((vendor) => {
                const pvData = byPhaseByVendor[phase]?.[vendor];
                const currentModel = getModelForPhaseVendor(phase, vendor);
                const vendorModels = modelsByVendor[vendor] || [];
                const actualCost = pvData?.total_cost ?? 0;
                const inputTokens = pvData?.input_tokens ?? 0;
                const outputTokens = pvData?.output_tokens ?? 0;
                const searchQueries = pvData?.search_queries ?? 0;
                const projectedCost = calculateProjectedCost(
                  inputTokens,
                  outputTokens,
                  searchQueries,
                  currentModel
                );

                return (
                  <div
                    key={`${phase}-${vendor}`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "100px 1fr 120px 100px",
                      gap: 12,
                      alignItems: "center",
                      marginTop: 8,
                      padding: "8px 0",
                      borderTop: "1px solid var(--border-color)",
                    }}
                  >
                    <span style={{ color: "var(--text-color)", textTransform: "capitalize" }}>
                      {VENDOR_LABELS[vendor] || vendor}
                    </span>
                    <select
                      value={currentModel}
                      onChange={(e) =>
                        setModelForPhaseVendor(phase, vendor, e.target.value || null)
                      }
                      style={{
                        padding: "6px 8px",
                        fontSize: 13,
                        border: "1px solid var(--border-color)",
                        borderRadius: 4,
                        backgroundColor: "var(--input-bg)",
                        color: "var(--text-color)",
                        maxWidth: 220,
                      }}
                    >
                      <option value="">Default</option>
                      {vendorModels.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                    <span style={{ color: "var(--text-color)", fontWeight: 500 }}>
                      {formatCost(actualCost)}
                    </span>
                    <span
                      style={{
                        color:
                          projectedCost < actualCost
                            ? "#16a34a"
                            : projectedCost > actualCost
                            ? "#dc2626"
                            : "var(--text-color)",
                        fontWeight: 500,
                      }}
                    >
                      {currentModel ? formatCost(projectedCost) : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}

      {!userCosts && personalDataLoaded && (
        <p
          style={{
            marginTop: 12,
            fontSize: 12,
            color: "var(--secondary-text-color)",
          }}
        >
          Sign in to see your cost history and projections.
        </p>
      )}
    </div>
  );
}
