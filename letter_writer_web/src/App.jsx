import React, { useState } from "react";
import ModelSelector from "./components/ModelSelector";
import LetterTabs from "./components/LetterTabs";

const VENDORS = [
  "openai",
  "anthropic",
  "gemini",
  "mistral",
  "grok",
];

export default function App() {
  const [jobText, setJobText] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [selectedVendors, setSelectedVendors] = useState(() => new Set(VENDORS));
  const [letters, setLetters] = useState({}); // vendor -> text
  const [failedVendors, setFailedVendors] = useState({}); // vendor -> error message
  const [loading, setLoading] = useState(false);
  const [loadingVendors, setLoadingVendors] = useState(new Set()); // vendors currently loading
  const [error, setError] = useState(null);
  const [showInput, setShowInput] = useState(true);

  const toggleVendor = (vendor, checked) => {
    setSelectedVendors((prev) => {
      const next = new Set(prev);
      checked ? next.add(vendor) : next.delete(vendor);
      return next;
    });
  };

  const selectAll = (checked) => {
    setSelectedVendors(checked ? new Set(VENDORS) : new Set());
  };

  const retryVendor = async (vendor) => {
    setLoadingVendors(prev => new Set(prev).add(vendor));
    setFailedVendors(prev => {
      const next = { ...prev };
      delete next[vendor];
      return next;
    });
    try {
      const res = await fetch("/api/process-job/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          job_text: jobText, 
          company_name: companyName,
          model_vendor: vendor 
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setLetters(prev => ({
        ...prev,
        [vendor]: data.letters[vendor] || Object.values(data.letters)[0]
      }));
    } catch (e) {
      setFailedVendors(prev => ({
        ...prev,
        [vendor]: String(e)
      }));
    } finally {
      setLoadingVendors(prev => {
        const next = new Set(prev);
        next.delete(vendor);
        return next;
      });
    }
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setLetters({});
    setFailedVendors({});
    setLoadingVendors(new Set(selectedVendors));
    setShowInput(false);
    try {
      const requests = Array.from(selectedVendors).map(async (vendor) => {
        const res = await fetch("/api/process-job/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ 
            job_text: jobText, 
            company_name: companyName,
            model_vendor: vendor 
          }),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        setLetters(prev => ({
          ...prev,
          [vendor]: data.letters[vendor] || Object.values(data.letters)[0]
        }));
      });
      await Promise.allSettled(requests);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setLoadingVendors(new Set());
    }
  };

  const resetForm = () => {
    setShowInput(true);
    setLetters({});
    setFailedVendors({});
    setError(null);
  };

  return (
    <div style={{ padding: 20 }}>
      <h1>Letter Writer</h1>
      {showInput ? (
        <>
          <ModelSelector
            vendors={VENDORS}
            selected={selectedVendors}
            onToggle={toggleVendor}
            onSelectAll={selectAll}
          />
          <input
            type="text"
            placeholder="Company name"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            style={{ width: "100%", marginTop: 10, padding: 8 }}
          />
          <textarea
            style={{ width: "100%", height: 150, marginTop: 10 }}
            placeholder="Paste job description here"
            value={jobText}
            onChange={(e) => setJobText(e.target.value)}
          />
          <button
            onClick={handleSubmit}
            disabled={loading || !jobText || !companyName || selectedVendors.size === 0}
            style={{ marginTop: 10 }}
          >
            {loading ? "Generating..." : "Generate Letters"}
          </button>
        </>
      ) : (
        <button onClick={resetForm} style={{ marginBottom: 10 }}>
          ← Back to Input
        </button>
      )}
      {error && <p style={{ color: "red" }}>{error}</p>}
      {Object.keys(failedVendors).length > 0 && (
        <div style={{ marginTop: 10, padding: 10, background: "#fff3cd", border: "1px solid #ffeaa7" }}>
          <h3>Failed Vendors:</h3>
          {Object.entries(failedVendors).map(([vendor, errorMsg]) => (
            <div key={vendor} style={{ marginBottom: 10 }}>
              <strong>{vendor}:</strong> {errorMsg}
              <button
                onClick={() => retryVendor(vendor)}
                disabled={loadingVendors.has(vendor)}
                style={{ marginLeft: 10 }}
              >
                {loadingVendors.has(vendor) ? "Retrying..." : "Retry"}
              </button>
            </div>
          ))}
        </div>
      )}
      {(Object.keys(letters).length > 0 || Object.keys(failedVendors).length > 0) && (
        <LetterTabs letters={letters} originalText={jobText} />
      )}
    </div>
  );
} 