import React, { useState, useEffect } from "react";
import ModelSelector from "./components/ModelSelector";
import LetterTabs from "./components/LetterTabs";
import { v4 as uuidv4 } from "uuid";
import { splitIntoParagraphs } from "./utils/split";

function generateColors(vendors) {
  const step = 360 / vendors.length;
  return vendors.reduce((acc, v, idx) => {
    const hue = Math.round(idx * step);
    acc[v] = `hsl(${hue}, 70%, 85%)`;
    return acc;
  }, {});
}

export default function App() {
  const [vendors, setVendors] = useState([]);
  const [vendorColors, setVendorColors] = useState({});
  const [vendorParagraphs, setVendorParagraphs] = useState({});
  const [finalParagraphs, setFinalParagraphs] = useState([]);
  const [jobText, setJobText] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [selectedVendors, setSelectedVendors] = useState(new Set());
  const [letters, setLetters] = useState({}); // vendor -> text
  const [failedVendors, setFailedVendors] = useState({}); // vendor -> error message
  const [loading, setLoading] = useState(false);
  const [loadingVendors, setLoadingVendors] = useState(new Set()); // vendors currently loading
  const [error, setError] = useState(null);
  const [showInput, setShowInput] = useState(true);

  // Fetch vendors on mount
  useEffect(() => {
    fetch("/api/vendors/")
      .then((res) => res.json())
      .then((data) => {
        setVendors(data.vendors || []);
        setSelectedVendors(new Set(data.vendors || []));
        setVendorColors(generateColors(data.vendors || []));
      })
      .catch((e) => setError(String(e)));
  }, []);

  const toggleVendor = (vendor, checked) => {
    setSelectedVendors((prev) => {
      const next = new Set(prev);
      checked ? next.add(vendor) : next.delete(vendor);
      return next;
    });
  };

  const selectAll = (checked) => {
    setSelectedVendors(checked ? new Set(vendors) : new Set());
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
      const collected = {};
      const requests = Array.from(selectedVendors).map(async (vendor) => {
        const res = await fetch("/api/process-job/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_text: jobText,
            company_name: companyName,
            model_vendor: vendor,
          }),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        collected[vendor] = data.letters[vendor] || Object.values(data.letters)[0];
      });
      await Promise.allSettled(requests);

      setLetters(collected);

      // Build paragraphs
      const paragraphsMap = {};
      Object.entries(collected).forEach(([v, text]) => {
        paragraphsMap[v] = splitIntoParagraphs(text, v);
      });
      setVendorParagraphs(paragraphsMap);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setLoadingVendors(new Set());
    }
  };

  const onAddParagraph = (paraObj) => {
    setFinalParagraphs((prev) => [...prev, { ...paraObj }]);
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
            vendors={vendors}
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
      {(Object.keys(letters).length > 0 || loading) && (
        <LetterTabs 
          vendorsList={Array.from(selectedVendors)}
          vendorParagraphs={vendorParagraphs}
          finalParagraphs={finalParagraphs}
          setFinalParagraphs={setFinalParagraphs}
          originalText={jobText}
          vendorColors={vendorColors}
          failedVendors={failedVendors}
          loadingVendors={loadingVendors}
          onRetry={retryVendor}
          onAddParagraph={onAddParagraph}
        />
      )}
    </div>
  );
} 