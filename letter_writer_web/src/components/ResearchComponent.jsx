import React, { useState, useEffect, useMemo } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import ModelPickSelector from "./ModelPickSelector";
import { buildGroupedModels } from "../utils/modelPicker";

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
  const [allModels, setAllModels] = useState(null);
  const [retryModel, setRetryModel] = useState("");

  // Fetch available models on mount
  useEffect(() => {
    fetch("/api/costs/models/?supports_search=true")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data) setAllModels(data); })
      .catch(() => {});
  }, []);

  const { grouped: groupedModels } = useMemo(
    () => buildGroupedModels(allModels || {}),
    [allModels]
  );

  // Trigger effect — only fire when externalTrigger changes (not on every query keystroke)
  useEffect(() => {
    if (externalTrigger && (query || "").trim()) {
      runResearch(Array.from(vendors));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalTrigger]);

  const buildPayload = (models) => {
    const payload = {
      models,
      job_text: context.job_text,
    };
    if (type === "company") {
      payload.company_name = query || "";
      payload.additional_company_info = context.additional_company_info;
    } else {
      payload.poc_name = query;
      payload.company_name = context.company_name;
    }
    return payload;
  };

  // Run research for given model IDs; merges into existing results
  const runResearch = async (models, { merge = false } = {}) => {
    if (!(query || "").trim() || models.length === 0) return;
    setLoading(true);
    setLoadingModel(models.length === 1 ? models[0] : null);
    setError(null);
    if (!merge) setResults(null);
    setIsOpen(true);

    try {
      const endpoint = type === "company" ? "/api/research/company/" : "/api/research/poc/";
      let selectedAny = false;
      const errors = [];

      const runOneModel = async (modelId) => {
        const payload = buildPayload([modelId]);
        const response = await fetchWithHeartbeat(endpoint, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        const data = response.data || {};
        const entry = data.results?.[modelId] || data.results?.[Object.keys(data.results || {})[0]];
        if (!entry) return;

        setResults((prev) => ({ ...(prev || {}), [modelId]: entry }));
        if (!selectedAny) {
          selectedAny = true;
          setSelectedVendor(modelId);
          onResultSelected?.(entry.report, entry.top_docs, data.source || null, data.resolved_name || null);
        }
      };

      if (models.length === 1) {
        await runOneModel(models[0]);
      } else {
        const settled = await Promise.allSettled(models.map((m) => runOneModel(m)));
        settled.forEach((res, idx) => {
          if (res.status === "rejected") {
            errors.push(`${models[idx]}: ${res.reason?.message || String(res.reason)}`);
          }
        });
      }

      if (errors.length > 0) {
        setError(`Some models failed: ${errors.join(" | ")}`);
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
            disabled={loading || !(query || "").trim()}
            style={{
              padding: "4px 12px",
              fontSize: "12px",
              backgroundColor: loading ? "var(--disabled-bg)" : "var(--button-bg)",
              color: "var(--button-text)",
              border: "1px solid var(--border-color)",
              borderRadius: 4,
              cursor: loading || !(query || "").trim() ? "default" : "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {loading ? "Researching..." : "Start Research"}
          </button>
        ) : (
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <ModelPickSelector
              value={retryModel}
              grouped={groupedModels}
              onChange={(_v, _m, _e, composite) => setRetryModel(composite)}
              selectStyle={{ fontSize: 12, padding: "2px 6px", flex: "1 1 140px" }}
              style={{ flex: "1 1 auto", minWidth: 0 }}
            />
            <button
              type="button"
              disabled={loading || !(query || "").trim() || !retryModel}
              onClick={() => handleRetryWithModel(retryModel)}
              style={{
                padding: "4px 10px",
                fontSize: 12,
                backgroundColor: loading ? "var(--disabled-bg)" : "var(--button-bg)",
                color: "var(--button-text)",
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                cursor: loading || !retryModel ? "default" : "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {loading ? `Running ${loadingModel || "..."}` : "Run"}
            </button>
          </div>
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
