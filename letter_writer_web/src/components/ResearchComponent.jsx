import React, { useState, useEffect, useMemo } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

export default function ResearchComponent({
  type, // "company" or "poc"
  query, // company name or poc name
  context, // job text, etc.
  vendors, // list of active background models (Set)
  onResultSelected, // callback(report, topDocs)
  label,
  externalTrigger, // timestamp or boolean to trigger research
}) {
  const [results, setResults] = useState(null); // { modelId: { report, top_docs } }
  const [loading, setLoading] = useState(false);
  const [loadingModel, setLoadingModel] = useState(null); // which model is currently running
  const [error, setError] = useState(null);
  const [selectedVendor, setSelectedVendor] = useState(null);
  const [isOpen, setIsOpen] = useState(false);
  const [allModels, setAllModels] = useState(null); // { vendorLabel: [{ id, name, vendor_key }] }

  // Fetch available models on mount
  useEffect(() => {
    fetch("/api/costs/models/")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data) setAllModels(data); })
      .catch(() => {});
  }, []);

  // Build flat list of all models with composite IDs
  const modelOptions = useMemo(() => {
    if (!allModels) return [];
    const options = [];
    Object.entries(allModels).forEach(([vendorLabel, models]) => {
      if (!Array.isArray(models)) return;
      models.forEach((m) => {
        const vendorKey = m.vendor_key || vendorLabel.toLowerCase().replace(/\s+/g, "");
        options.push({
          id: `${vendorKey}/${m.id}`,
          name: m.name,
          vendorLabel,
        });
      });
    });
    return options;
  }, [allModels]);

  // Group model options by vendor for the optgroup dropdown
  const groupedOptions = useMemo(() => {
    const groups = {};
    modelOptions.forEach((m) => {
      if (!groups[m.vendorLabel]) groups[m.vendorLabel] = [];
      groups[m.vendorLabel].push(m);
    });
    return groups;
  }, [modelOptions]);

  // Trigger effect
  useEffect(() => {
    if (externalTrigger && query) {
      runResearch(Array.from(vendors));
    }
  }, [externalTrigger]);

  const buildPayload = (models) => {
    const payload = {
      models,
      job_text: context.job_text,
    };
    if (type === "company") {
      payload.company_name = query;
      payload.additional_company_info = context.additional_company_info;
      payload.point_of_contact = context.point_of_contact;
    } else {
      payload.poc_name = query;
      payload.company_name = context.company_name;
    }
    return payload;
  };

  // Run research for given model IDs; merges into existing results
  const runResearch = async (models, { merge = false } = {}) => {
    if (!query || models.length === 0) return;
    setLoading(true);
    setLoadingModel(models.length === 1 ? models[0] : null);
    setError(null);
    if (!merge) setResults(null);
    setIsOpen(true);

    try {
      const endpoint = type === "company" ? "/api/research/company/" : "/api/research/poc/";
      const payload = buildPayload(models);

      const response = await fetchWithHeartbeat(endpoint, {
        method: "POST",
        body: JSON.stringify(payload),
      });

      const data = response.data;
      if (data.results) {
        const newResults = merge ? { ...results, ...data.results } : data.results;
        setResults(newResults);
        // Auto-select the first new result
        const newKey = Object.keys(data.results)[0];
        if (newKey) {
          setSelectedVendor(newKey);
          const res = data.results[newKey];
          onResultSelected?.(res.report, res.top_docs);
        }
      }
    } catch (e) {
      console.error("Research error:", e);
      setError(e.message || "Research failed");
    } finally {
      setLoading(false);
      setLoadingModel(null);
    }
  };

  const handleRetryWithModel = (modelId) => {
    if (!modelId || loading) return;
    runResearch([modelId], { merge: true });
  };

  const resultKeys = results ? Object.keys(results) : [];

  return (
    <div style={{ marginTop: 10, padding: 10, border: "1px solid var(--border-color)", borderRadius: 4, backgroundColor: "var(--panel-bg)" }}>
      {/* Header row: label, result selector, and action */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ fontWeight: 600, fontSize: "14px", whiteSpace: "nowrap" }}>{label}</span>
          {/* Result selector — shown when multiple results exist */}
          {resultKeys.length > 1 && (
            <select
              value={selectedVendor || ""}
              onChange={(e) => {
                const v = e.target.value;
                setSelectedVendor(v);
                if (results[v]) {
                  onResultSelected?.(results[v].report, results[v].top_docs);
                }
              }}
              style={{
                fontSize: "12px",
                padding: "2px 6px",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                backgroundColor: "var(--input-bg)",
                color: "var(--text-color)",
                cursor: "pointer",
                minWidth: 0,
              }}
            >
              {resultKeys.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          )}
        </div>

        {/* Before results: Start Research button. After results: model picker dropdown to retry */}
        {!results ? (
          <button
            onClick={() => runResearch(Array.from(vendors))}
            disabled={loading || !query}
            style={{
              padding: "4px 12px",
              fontSize: "12px",
              backgroundColor: loading ? "var(--disabled-bg)" : "var(--button-bg)",
              color: "var(--button-text)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: loading || !query ? "default" : "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {loading ? "Researching..." : "Start Research"}
          </button>
        ) : (
          <select
            value=""
            disabled={loading || !query}
            onChange={(e) => {
              const modelId = e.target.value;
              if (modelId) handleRetryWithModel(modelId);
            }}
            style={{
              fontSize: "12px",
              padding: "2px 6px",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              backgroundColor: loading ? "var(--disabled-bg)" : "var(--input-bg)",
              color: "var(--text-color)",
              cursor: loading ? "default" : "pointer",
            }}
          >
            <option value="">{loading ? `Running ${loadingModel || "..."}` : "Run with model..."}</option>
            {Object.entries(groupedOptions).map(([vendorLabel, models]) => (
              <optgroup key={vendorLabel} label={vendorLabel}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
      </div>

      {error && <div style={{ color: "var(--error-text)", fontSize: "12px", marginTop: 5 }}>{error}</div>}

      {isOpen && results && (
        <div style={{ marginTop: 10 }}>
          {selectedVendor && results[selectedVendor] && (
            <div>
              <div style={{
                fontSize: "12px",
                maxHeight: "300px",
                overflowY: "auto",
                whiteSpace: "pre-wrap",
                padding: 12,
                backgroundColor: "var(--bg-color)",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                lineHeight: 1.5,
              }}>
                {results[selectedVendor].report || "No report generated."}
              </div>
              {results[selectedVendor].error && (
                <div style={{ color: "var(--error-text)", fontSize: "12px", marginTop: 4 }}>
                  Error: {results[selectedVendor].error}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
