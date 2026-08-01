import React, { useState, useEffect, useRef, useMemo } from "react";
import { useLanguages } from "../contexts/LanguageContext";
import LanguageConfig from "./LanguageConfig";
import CompetenceScaleSettings from "./CompetenceScaleSettings";
import VendorFlowModelSettings, {
  buildVendorRoleOverridesFromModels,
  flattenFlowRoleDefaults,
  mergeVendorRoleModelsFromDefaults,
} from "./VendorFlowModelSettings";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { buildGroupedModels } from "../utils/modelPicker";

export default function SettingsPage({
  vendors = [],
  selectedVendors,
  setSelectedVendors,
  setBackgroundModels,
  onCompetenceScalesChange,
  guardBeforeEnablingLocal = (fn) => fn(),
  onSessionRestored = null,
}) {
  const { languages, saveDefaults, setLanguages, translationProvider, setTranslationProvider } = useLanguages();
  const [savingLanguages, setSavingLanguages] = useState(false);
  const [defaultModels, setDefaultModels] = useState(new Set());
  const [savingModels, setSavingModels] = useState(false);
  const [defaultBackgroundModels, setDefaultBackgroundModels] = useState(new Set()); // Loaded from backend
  const [savingBackgroundModels, setSavingBackgroundModels] = useState(false);
  const [availableModels, setAvailableModels] = useState({}); // { vendor: { model: { input: ..., output: ... } } }
  const [minColumnWidth, setMinColumnWidth] = useState(200); // pixels
  const [savingColumnWidth, setSavingColumnWidth] = useState(false);
  const [autocompleteMaxWords, setAutocompleteMaxWords] = useState(20);
  const [autocompleteStopOnPeriod, setAutocompleteStopOnPeriod] = useState(true);
  const [autocompleteModels, setAutocompleteModels] = useState(new Set());
  const [savingAutocomplete, setSavingAutocomplete] = useState(false);
  const [vendorModelFlows, setVendorModelFlows] = useState([]);
  const [vendorRoleModels, setVendorRoleModels] = useState({});
  const [savingVendorRoleModels, setSavingVendorRoleModels] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [backups, setBackups] = useState([]);
  const [backupsLoading, setBackupsLoading] = useState(false);
  const [backupsError, setBackupsError] = useState(null);
  const [restoringFilename, setRestoringFilename] = useState(null);

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
          if (data.vendor_model_flows && Array.isArray(data.vendor_model_flows)) {
            setVendorModelFlows(data.vendor_model_flows);
            const roleDefaults = flattenFlowRoleDefaults(data.vendor_model_flows);
            setVendorRoleModels(
              mergeVendorRoleModelsFromDefaults(
                data.vendor_role_models || data.phase_models || {},
                roleDefaults
              )
            );
          }
          if (data.autocomplete_max_words != null) {
            setAutocompleteMaxWords(data.autocomplete_max_words);
          }
          if (data.autocomplete_stop_on_period != null) {
            setAutocompleteStopOnPeriod(Boolean(data.autocomplete_stop_on_period));
          }
          if (Array.isArray(data.autocomplete_models) && data.autocomplete_models.length > 0) {
            setAutocompleteModels(new Set(data.autocomplete_models));
          } else if (data.default_models?.length) {
            setAutocompleteModels(new Set(data.default_models));
          }
          if (data.translation_provider === "llm" || data.translation_provider === "google") {
            setTranslationProvider(data.translation_provider);
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
      await saveDefaults(languages, translationProvider);
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
      // Keep compose state in sync so research uses the new model set immediately.
      if (setBackgroundModels) {
        setBackgroundModels(new Set(modelsArray));
      }
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

  const handleSaveAutocompleteSettings = async () => {
    try {
      setSavingAutocomplete(true);
      setError(null);
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({
          autocomplete_max_words: autocompleteMaxWords,
          autocomplete_stop_on_period: autocompleteStopOnPeriod,
          autocomplete_models: Array.from(autocompleteModels),
        }),
      });
    } catch (e) {
      setError("Failed to save autocomplete settings");
    } finally {
      setSavingAutocomplete(false);
    }
  };

  const handleSaveVendorRoleModels = async () => {
    try {
      setSavingVendorRoleModels(true);
      setError(null);
      const roleDefaults = flattenFlowRoleDefaults(vendorModelFlows);
      const overrides = buildVendorRoleOverridesFromModels(vendorRoleModels, roleDefaults);
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({
          vendor_role_model_overrides: overrides,
        }),
      });
    } catch (e) {
      setError("Failed to save vendor model overrides");
    } finally {
      setSavingVendorRoleModels(false);
    }
  };

  const loadBackups = async () => {
    try {
      setBackupsLoading(true);
      setBackupsError(null);
      const res = await fetch("/api/phases/backups/", { credentials: "include" });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Failed to list backups (${res.status})`);
      }
      const data = await res.json();
      setBackups(Array.isArray(data.backups) ? data.backups : []);
    } catch (e) {
      setBackupsError(e?.message || "Failed to list session backups");
      setBackups([]);
    } finally {
      setBackupsLoading(false);
    }
  };

  useEffect(() => {
    loadBackups();
  }, []);

  const handleRestoreBackup = async (filename) => {
    if (!filename) return;
    const confirmed = window.confirm(
      `Restore session from backup?\n\n${filename}\n\nThis replaces the current working session on the server with the backup contents.`
    );
    if (!confirmed) return;
    try {
      setRestoringFilename(filename);
      setBackupsError(null);
      const result = await fetchWithHeartbeat("/api/phases/restore-from-backup/", {
        method: "POST",
        body: JSON.stringify({ filename }),
      });
      const payload = result?.data || result;
      if (typeof onSessionRestored === "function") {
        onSessionRestored(payload.session_state || {}, payload.session_id || null);
      }
    } catch (e) {
      setBackupsError(e?.message || "Failed to restore session backup");
    } finally {
      setRestoringFilename(null);
    }
  };

  const formatBackupTime = (backup) => {
    const raw = backup?.saved_at || (backup?.mtime ? new Date(backup.mtime * 1000).toISOString() : null);
    if (!raw) return "—";
    try {
      return new Date(raw).toLocaleString();
    } catch {
      return String(raw);
    }
  };

  const toggleModel = (vendor) => {
    if (!defaultModels.has(vendor) && vendor === "local") {
      guardBeforeEnablingLocal(() => {
        setDefaultModels((prev) => {
          const next = new Set(prev);
          next.add("local");
          return next;
        });
      });
      return;
    }
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
    if (!checked) {
      setDefaultModels(new Set());
      return;
    }
    if (vendors.includes("local") && !defaultModels.has("local")) {
      guardBeforeEnablingLocal(() => {
        setDefaultModels(new Set(vendors));
      });
      return;
    }
    setDefaultModels(new Set(vendors));
  };

  const { grouped, groupedModels, validModelIds } = useMemo(() => {
    const { grouped: allGrouped } = buildGroupedModels(availableModels);
    const grouped = {};
    const valid = new Set();
    if (availableModels) {
      Object.entries(availableModels).forEach(([vendorLabel, models]) => {
        if (!Array.isArray(models) || models.length === 0) return;
        const searchable = models.filter((m) => m.supports_search);
        if (searchable.length === 0) return;
        const vendorKey = searchable[0].vendor_key || vendorLabel.toLowerCase().replace(/\s+/g, "");
        grouped[vendorLabel] = searchable.map((m) => {
          const compositeId = `${m.vendor_key || vendorKey}/${m.id}`;
          valid.add(compositeId);
          return { id: compositeId, name: m.name, vendorLabel };
        });
      });
    }
    return { grouped: allGrouped, groupedModels: grouped, validModelIds: valid };
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
          Configure translation languages, CEFR levels, and language-specific instructions for generation and translation.
          German defaults include umlaut rules. Levels apply to cover letter generation (job language) and LLM translation.
        </p>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Translation provider</div>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, marginBottom: 6, cursor: "pointer" }}>
            <input
              type="radio"
              name="translation_provider"
              value="google"
              checked={translationProvider === "google"}
              onChange={() => setTranslationProvider("google")}
            />
            Google Translate (fast; no CEFR level control)
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
            <input
              type="radio"
              name="translation_provider"
              value="llm"
              checked={translationProvider === "llm"}
              onChange={() => setTranslationProvider("llm")}
            />
            LLM (uses level &amp; language instructions; Gemini flash-lite)
          </label>
        </div>
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

      {/* Vendor models by flow (defaults from clients/<vendor>.json) */}
      <div
        style={{
          marginBottom: 30,
          padding: 20,
          backgroundColor: "var(--bg-color)",
          border: "1px solid var(--border-color)",
          borderRadius: "4px",
        }}
      >
        <h3 style={{ margin: "0 0 8px", color: "var(--text-color)" }}>Vendor models by flow</h3>
        <p
          style={{
            marginTop: 0,
            marginBottom: 8,
            fontSize: "14px",
            color: "var(--secondary-text-color)",
          }}
        >
          Each value is pre-filled from that vendor&apos;s <code>clients/&lt;vendor&gt;.json</code> roles.
          The config default is labeled <strong>(default)</strong> in the model picker.
        </p>
        <VendorFlowModelSettings
          flows={vendorModelFlows}
          vendorRoleModels={vendorRoleModels}
          onVendorRoleModelsChange={setVendorRoleModels}
          grouped={grouped}
          vendors={vendors}
          onSave={handleSaveVendorRoleModels}
          saving={savingVendorRoleModels}
        />
      </div>

      {/* Autocomplete flow */}
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
          <h3 style={{ margin: 0, color: "var(--text-color)" }}>Autocomplete flow</h3>
          <button
            onClick={handleSaveAutocompleteSettings}
            disabled={savingAutocomplete}
            style={{
              padding: "6px 12px",
              backgroundColor: "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: savingAutocomplete ? "not-allowed" : "pointer",
              opacity: savingAutocomplete ? 0.7 : 1,
              fontSize: "14px",
            }}
          >
            {savingAutocomplete ? "Saving..." : "Save"}
          </button>
        </div>
        <p style={{ marginTop: 0, marginBottom: 15, fontSize: 14, color: "var(--secondary-text-color)" }}>
          Tab completion uses job + CV context. Choose which vendors appear in the autocomplete model list.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginBottom: 16, alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, color: "var(--text-color)" }}>
            Max words
            <input
              type="number"
              min={1}
              max={100}
              value={autocompleteMaxWords}
              onChange={(e) => setAutocompleteMaxWords(parseInt(e.target.value, 10) || 20)}
              style={{ width: 56, padding: "4px 6px", borderRadius: 4, border: "1px solid var(--border-color)" }}
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, color: "var(--text-color)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={autocompleteStopOnPeriod}
              onChange={(e) => setAutocompleteStopOnPeriod(e.target.checked)}
            />
            Stop at first period
          </label>
        </div>
        <div style={{ marginBottom: 12, fontSize: 13, fontWeight: 600, color: "var(--text-color)" }}>
          Autocomplete vendors
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
          {vendors.map((v) => (
            <label key={v} style={{ display: "flex", alignItems: "center", gap: 4, textTransform: "capitalize", fontSize: 13 }}>
              <input
                type="checkbox"
                checked={autocompleteModels.has(v)}
                onChange={() => {
                  setAutocompleteModels((prev) => {
                    const next = new Set(prev);
                    if (next.has(v)) next.delete(v);
                    else next.add(v);
                    return next;
                  });
                }}
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

      <div
        style={{
          marginBottom: 30,
          padding: 20,
          border: "1px solid var(--border-color)",
          borderRadius: "8px",
          backgroundColor: "var(--card-bg)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 15,
            gap: 12,
          }}
        >
          <h3 style={{ margin: 0, color: "var(--text-color)" }}>Session backups</h3>
          <button
            type="button"
            onClick={loadBackups}
            disabled={backupsLoading}
            style={{
              padding: "6px 12px",
              backgroundColor: "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: backupsLoading ? "not-allowed" : "pointer",
              opacity: backupsLoading ? 0.7 : 1,
              fontSize: "14px",
            }}
          >
            {backupsLoading ? "Refreshing…" : "Refresh"}
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
          Automatic silent copies of your working session are written to the host
          folder <code>session_backups/</code>. Restore replaces the current
          server session with a chosen backup so you can continue where you left
          off.
        </p>
        {backupsError && (
          <div
            style={{
              marginBottom: 12,
              padding: "8px 12px",
              backgroundColor: "#fef2f2",
              color: "#b91c1c",
              borderRadius: "4px",
              fontSize: "14px",
            }}
          >
            {backupsError}
          </div>
        )}
        {backupsLoading && backups.length === 0 ? (
          <p style={{ color: "var(--secondary-text-color)", fontSize: "14px" }}>
            Loading backups…
          </p>
        ) : backups.length === 0 ? (
          <p style={{ color: "var(--secondary-text-color)", fontSize: "14px" }}>
            No session backups found yet.
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {backups.map((backup) => (
              <div
                key={backup.filename}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                  padding: "10px 12px",
                  border: "1px solid var(--border-color)",
                  borderRadius: "6px",
                  backgroundColor: "var(--input-bg)",
                }}
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      fontSize: "13px",
                      fontWeight: 600,
                      color: "var(--text-color)",
                      wordBreak: "break-all",
                    }}
                  >
                    {backup.company_name || "Unknown company"}
                    {backup.is_latest ? " (latest)" : ""}
                  </div>
                  <div
                    style={{
                      fontSize: "12px",
                      color: "var(--secondary-text-color)",
                      marginTop: 2,
                    }}
                  >
                    {formatBackupTime(backup)}
                    {backup.size != null ? ` · ${Math.round(backup.size / 1024)} KB` : ""}
                  </div>
                  <div
                    style={{
                      fontSize: "11px",
                      color: "var(--secondary-text-color)",
                      marginTop: 2,
                      wordBreak: "break-all",
                    }}
                  >
                    {backup.filename}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleRestoreBackup(backup.filename)}
                  disabled={!!restoringFilename}
                  style={{
                    padding: "6px 12px",
                    backgroundColor: restoringFilename === backup.filename ? "#9ca3af" : "#059669",
                    color: "white",
                    border: "none",
                    borderRadius: "4px",
                    cursor: restoringFilename ? "not-allowed" : "pointer",
                    fontSize: "13px",
                    whiteSpace: "nowrap",
                  }}
                >
                  {restoringFilename === backup.filename ? "Restoring…" : "Restore"}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
