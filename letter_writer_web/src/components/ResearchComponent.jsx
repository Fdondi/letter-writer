import React, { useState, useEffect } from "react";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

export default function ResearchComponent({
  type, // "company" or "poc"
  query, // company name or poc name
  context, // job text, etc.
  vendors, // list of active vendors
  onResultSelected, // callback(report, topDocs)
  label,
  externalTrigger, // timestamp or boolean to trigger research
}) {
  const [results, setResults] = useState(null); // { vendor: { report, top_docs } }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedVendor, setSelectedVendor] = useState(null);
  const [isOpen, setIsOpen] = useState(false);

  // Trigger effect
  useEffect(() => {
    if (externalTrigger && query) {
      handleResearch();
    }
  }, [externalTrigger]);

  const handleResearch = async () => {
    if (!query) return;
    setLoading(true);
    setError(null);
    setResults(null);
    setIsOpen(true);

    try {
      const endpoint = type === "company" ? "/api/research/company/" : "/api/research/poc/";
      const payload = {
        models: Array.from(vendors),
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

      const response = await fetchWithHeartbeat(endpoint, {
        method: "POST",
        body: JSON.stringify(payload),
      });

      const data = response.data;
      if (data.results) {
        setResults(data.results);
        // Default select the first one
        const firstVendor = Object.keys(data.results)[0];
        if (firstVendor) {
          setSelectedVendor(firstVendor);
          const res = data.results[firstVendor];
          if (onResultSelected) {
            onResultSelected(res.report, res.top_docs);
          }
        }
      }
    } catch (e) {
      console.error("Research error:", e);
      setError(e.message || "Research failed");
    } finally {
      setLoading(false);
    }
  };

  // Auto-trigger if query changes? Maybe not, user might be typing.
  // User said: "immediately start a background search" when extracted or supplied.
  // We'll leave it to the parent to trigger or just use the button.

  return (
    <div style={{ marginTop: 10, padding: 10, border: "1px solid var(--border-color)", borderRadius: 4, backgroundColor: "var(--panel-bg)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontWeight: 600, fontSize: "14px" }}>{label}</span>
        <button
          onClick={handleResearch}
          disabled={loading || !query}
          style={{
            padding: "4px 12px",
            fontSize: "12px",
            backgroundColor: loading ? "var(--disabled-bg)" : "var(--button-bg)",
            color: "var(--button-text)",
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            cursor: loading || !query ? "default" : "pointer",
          }}
        >
          {loading ? "Researching..." : results ? "Restart Research" : "Start Research"}
        </button>
      </div>

      {error && <div style={{ color: "var(--error-text)", fontSize: "12px", marginTop: 5 }}>{error}</div>}

      {isOpen && results && (
        <div style={{ marginTop: 10 }}>
          {/* Tabs for multiple results */}
          {Object.keys(results).length > 1 && (
            <div style={{ display: "flex", gap: 2, marginBottom: 8, borderBottom: "1px solid var(--border-color)", overflowX: "auto" }}>
              {Object.keys(results).map((v) => (
                <div
                  key={v}
                  onClick={() => {
                    setSelectedVendor(v);
                    if (results[v]) {
                        onResultSelected?.(results[v].report, results[v].top_docs);
                    }
                  }}
                  style={{
                    padding: "6px 12px",
                    cursor: "pointer",
                    borderBottom: selectedVendor === v ? "2px solid #3b82f6" : "2px solid transparent",
                    color: selectedVendor === v ? "var(--text-color)" : "var(--secondary-text-color)",
                    fontWeight: selectedVendor === v ? 600 : 400,
                    fontSize: "12px",
                    whiteSpace: "nowrap"
                  }}
                >
                  {v}
                </div>
              ))}
            </div>
          )}

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
                lineHeight: 1.5
              }}>
                {results[selectedVendor].report || "No report generated."}
              </div>
              {results[selectedVendor].error && (
                <div style={{ color: "var(--error-text)", fontSize: "12px", marginTop: 4 }}>
                  Error: {results[selectedVendor].error}
                </div>
              )}
              {/* Explicit select button if needed, but tabs handle selection for now */}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
