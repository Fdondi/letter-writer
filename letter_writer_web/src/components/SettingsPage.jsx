import React, { useState, useEffect, useRef, useMemo } from "react";
import { useLanguages } from "../contexts/LanguageContext";
import LanguageConfig from "./LanguageConfig";
import CompetenceScaleSettings from "./CompetenceScaleSettings";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

export default function SettingsPage({ vendors = [], selectedVendors, setSelectedVendors, onCompetenceScalesChange }) {
  const { languages, saveDefaults, setLanguages } = useLanguages();
  const [savingLanguages, setSavingLanguages] = useState(false);
  const [defaultModels, setDefaultModels] = useState(new Set());
  const [savingModels, setSavingModels] = useState(false);
  const [defaultBackgroundModels, setDefaultBackgroundModels] = useState(new Set()); // Loaded from backend
  const [savingBackgroundModels, setSavingBackgroundModels] = useState(false);
  const [availableModels, setAvailableModels] = useState({}); // { vendor: { model: { input: ..., output: ... } } }
  const [minColumnWidth, setMinColumnWidth] = useState(200); // pixels
  const [savingColumnWidth, setSavingColumnWidth] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Load settings from backend (only on mount or when vendors list changes)
  useEffect(() => {
    const loadSettings = async () => {
      try {
        setLoading(true);
        
        // Fetch available models
        try {
            const modelsRes = await fetch("/api/costs/models/");
            if (modelsRes.ok) {
                const modelsData = await modelsRes.json();
                setAvailableModels(modelsData || {});
            }
        } catch (e) {
            console.error("Failed to load models:", e);
        }

        const res = await fetch("/api/personal-data/");
        if (res.ok) {
          const data = await res.json();
          
          // Load default models - prefer saved defaults from backend
          if (data.default_models && Array.isArray(data.default_models) && data.default_models.length > 0) {
            setDefaultModels(new Set(data.default_models));
            setHasLoadedFromBackend(true);
          } else if (selectedVendors && selectedVendors.size > 0) {
            // Use current selected vendors from Compose tab if no saved defaults
            setDefaultModels(new Set(selectedVendors));
            setHasLoadedFromBackend(false);
          } else if (vendors.length > 0) {
            // If no defaults saved and no current selection, use all vendors
            setDefaultModels(new Set(vendors));
            setHasLoadedFromBackend(false);
          }
          
          // Load default background models (backend always returns a non-empty list with defaults applied)
          if (data.default_background_models && Array.isArray(data.default_background_models)) {
            setDefaultBackgroundModels(new Set(data.default_background_models));
          }
          
          // Load minimum column width (default to 200px if not set)
          if (data.min_column_width !== undefined) {
            setMinColumnWidth(data.min_column_width);
          } else {
            setMinColumnWidth(200); // Default value shown in UI
          }
        }
      } catch (e) {
        console.error("Failed to load settings:", e);
        setError("Failed to load settings");
        // Set defaults if loading fails - prefer current selection
        if (selectedVendors && selectedVendors.size > 0) {
          setDefaultModels(new Set(selectedVendors));
        } else if (vendors.length > 0) {
          setDefaultModels(new Set(vendors));
        }
        setHasLoadedFromBackend(false);
      } finally {
        setLoading(false);
      }
    };
    
    loadSettings();
  }, [vendors]); // Only reload when vendors list changes, not when selectedVendors changes

  // Track if we've loaded settings from backend to avoid overwriting with selectedVendors
  const [hasLoadedFromBackend, setHasLoadedFromBackend] = useState(false);

  const handleSaveLanguages = async () => {
    try {
      setSavingLanguages(true);
      setError(null);
      await saveDefaults();
    } catch (e) {
      setError("Failed to save language defaults");
    } finally {
      setSavingLanguages(false);
    }
  };

  const handleSaveModels = async () => {
    try {
      setSavingModels(true);
      setError(null);
      const modelsArray = Array.from(defaultModels);
      
      // Update shared state immediately (as if user modified in compose tab)
      // Do this BEFORE saving to backend to avoid race conditions
      if (setSelectedVendors) {
        setSelectedVendors(new Set(modelsArray));
      }
      
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({
          default_models: modelsArray,
        }),
      });
    } catch (e) {
      setError("Failed to save default models");
      // Revert the change if save failed
      // Note: We could restore previous state here, but for now just show error
    } finally {
      setSavingModels(false);
    }
  };

  const handleSaveBackgroundModels = async () => {
    try {
      setSavingBackgroundModels(true);
      setError(null);
      const modelsArray = Array.from(defaultBackgroundModels);
      
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({
          default_background_models: modelsArray,
        }),
      });
    } catch (e) {
      setError("Failed to save background research models");
    } finally {
      setSavingBackgroundModels(false);
    }
  };

  const handleSaveColumnWidth = async () => {
    try {
      setSavingColumnWidth(true);
      setError(null);
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({
          min_column_width: minColumnWidth,
        }),
      });
      // Also save to localStorage for immediate use
      localStorage.setItem("minColumnWidth", minColumnWidth.toString());
    } catch (e) {
      setError("Failed to save minimum column width");
    } finally {
      setSavingColumnWidth(false);
    }
  };

  const toggleModel = (vendor) => {
    setDefaultModels((prev) => {
      const next = new Set(prev);
      if (next.has(vendor)) {
        next.delete(vendor);
      } else {
        next.add(vendor);
      }
      return next;
    });
  };

  const toggleBackgroundModel = (modelId) => {
    setDefaultBackgroundModels((prev) => {
      const next = new Set(prev);
      if (next.has(modelId)) {
        // Don't allow deselecting the last model
        if (next.size <= 1) return prev;
        next.delete(modelId);
      } else {
        if (next.size >= 3) return prev; // Limit to 3
        next.add(modelId);
      }
      return next;
    });
  };

  const selectAllModels = (checked) => {
    setDefaultModels(checked ? new Set(vendors) : new Set());
  };

  // Group available models for display, building correct composite IDs using vendor_key from API
  const { groupedModels, validModelIds } = useMemo(() => {
    const grouped = {};
    const valid = new Set();
    if (availableModels) {
      Object.entries(availableModels).forEach(([vendorLabel, models]) => {
        if (Array.isArray(models) && models.length > 0) {
          const vendorKey = models[0].vendor_key || vendorLabel.toLowerCase().replace(/\s+/g, '');
          grouped[vendorLabel] = models.map(m => {
            const compositeId = `${m.vendor_key || vendorKey}/${m.id}`;
            valid.add(compositeId);
            return { id: compositeId, name: m.name, vendorLabel };
          });
        }
      });
    }
    return { groupedModels: grouped, validModelIds: valid };
  }, [availableModels]);

  // Clean up stale/broken background model IDs (e.g. "google/..." instead of "gemini/...")
  // once we know which IDs are actually valid from the model pricing API
  useEffect(() => {
    if (validModelIds.size === 0) return; // models not loaded yet
    setDefaultBackgroundModels(prev => {
      const cleaned = new Set([...prev].filter(id => validModelIds.has(id)));
      if (cleaned.size === prev.size) return prev; // no change
      console.log("Cleaned stale background model IDs:", [...prev].filter(id => !validModelIds.has(id)));
      return cleaned;
    });
  }, [validModelIds]);

  if (loading) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <p>Loading settings...</p>
      </div>
    );
  }

  return (
    <div style={{ padding: 20 }}>
      <h2 style={{ margin: "0 0 20px 0", color: "var(--text-color)" }}>Settings</h2>

      {error && (
        <div
          style={{
            padding: 12,
            marginBottom: 20,
            backgroundColor: "#fee",
            color: "#c33",
            borderRadius: "4px",
            border: "1px solid #fcc",
          }}
        >
          {error}
        </div>
      )}

      {/* Default Languages Section */}
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
            Default Translation Languages
          </h3>
          <button
            onClick={handleSaveLanguages}
            disabled={savingLanguages}
            style={{
              padding: "6px 12px",
              backgroundColor: "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: savingLanguages ? "not-allowed" : "pointer",
              opacity: savingLanguages ? 0.7 : 1,
              fontSize: "14px",
            }}
          >
            {savingLanguages ? "Saving..." : "Save Defaults"}
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
          Configure the languages available for translation. These defaults will
          be loaded when you start a new session.
        </p>
        <LanguageConfig />
      </div>

      {/* Default Models Section */}
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
            Default Models to Activate
          </h3>
          <button
            onClick={handleSaveModels}
            disabled={savingModels}
            style={{
              padding: "6px 12px",
              backgroundColor: "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: savingModels ? "not-allowed" : "pointer",
              opacity: savingModels ? 0.7 : 1,
              fontSize: "14px",
            }}
          >
            {savingModels ? "Saving..." : "Save Defaults"}
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
          Select which models should be activated by default when you start a
          new session.
        </p>
        <div
          style={{
            display: "flex",
            gap: 10,
            flexWrap: "wrap",
            color: "var(--text-color)",
          }}
        >
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={defaultModels.size === vendors.length && vendors.length > 0}
              onChange={(e) => selectAllModels(e.target.checked)}
            />
            <strong>Select All</strong>
          </label>
          {vendors.map((v) => (
            <label
              key={v}
              style={{
                textTransform: "capitalize",
                display: "flex",
                alignItems: "center",
                gap: 4,
                cursor: "pointer",
              }}
            >
              <input
                type="checkbox"
                checked={defaultModels.has(v)}
                onChange={() => toggleModel(v)}
              />
              {v}
            </label>
          ))}
        </div>
      </div>

      {/* Background Research Models Section */}
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
            Background Research Models
          </h3>
          <button
            onClick={handleSaveBackgroundModels}
            disabled={savingBackgroundModels || defaultBackgroundModels.size === 0}
            style={{
              padding: "6px 12px",
              backgroundColor: (savingBackgroundModels || defaultBackgroundModels.size === 0) ? "#94a3b8" : "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: (savingBackgroundModels || defaultBackgroundModels.size === 0) ? "not-allowed" : "pointer",
              opacity: (savingBackgroundModels || defaultBackgroundModels.size === 0) ? 0.7 : 1,
              fontSize: "14px",
            }}
          >
            {savingBackgroundModels ? "Saving..." : defaultBackgroundModels.size === 0 ? "Select at least one" : "Save Defaults"}
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
          Select up to 3 models to perform parallel background research on companies and contacts.
          Results will be aggregated.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 15 }}>
          {Object.entries(groupedModels).map(([vendorLabel, models]) => (
            <div key={vendorLabel}>
              <strong style={{ display: "block", marginBottom: 5, color: "var(--text-color)" }}>
                {vendorLabel}
              </strong>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {models.map((model) => (
                  <label
                    key={model.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      cursor: "pointer",
                      color: "var(--text-color)",
                      fontSize: "14px",
                      backgroundColor: "var(--input-bg)",
                      padding: "4px 8px",
                      borderRadius: "4px",
                      border: "1px solid var(--border-color)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={defaultBackgroundModels.has(model.id)}
                      onChange={() => toggleBackgroundModel(model.id)}
                      disabled={!defaultBackgroundModels.has(model.id) && defaultBackgroundModels.size >= 3}
                    />
                    {model.name}
                  </label>
                ))}
              </div>
            </div>
          ))}
          {Object.keys(groupedModels).length === 0 && (
            <p style={{ color: "var(--secondary-text-color)", fontStyle: "italic" }}>
              Loading models or none available...
            </p>
          )}
        </div>
      </div>

      {/* Minimum Column Width Section */}
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
            Minimum Column Width
          </h3>
          <button
            onClick={handleSaveColumnWidth}
            disabled={savingColumnWidth}
            style={{
              padding: "6px 12px",
              backgroundColor: "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: savingColumnWidth ? "not-allowed" : "pointer",
              opacity: savingColumnWidth ? 0.7 : 1,
              fontSize: "14px",
            }}
          >
            {savingColumnWidth ? "Saving..." : "Save"}
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
          Set the minimum width (in pixels) for columns in the letter assembly
          view. Columns will not shrink below this width. Default: 200px.
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <input
            type="number"
            value={minColumnWidth}
            onChange={(e) => {
              const value = parseInt(e.target.value, 10);
              if (!isNaN(value) && value > 0) {
                setMinColumnWidth(value);
              }
            }}
            min="100"
            max="1000"
            step="10"
            placeholder="200"
            style={{
              padding: "8px",
              fontSize: "14px",
              border: "1px solid var(--border-color)",
              borderRadius: "4px",
              backgroundColor: "var(--input-bg)",
              color: "var(--text-color)",
              width: "120px",
            }}
          />
          <span style={{ color: "var(--text-color)" }}>pixels (default: 200)</span>
        </div>
      </div>

      <CompetenceScaleSettings
        onSaved={() => {
          onCompetenceScalesChange?.();
        }}
      />
    </div>
  );
}
