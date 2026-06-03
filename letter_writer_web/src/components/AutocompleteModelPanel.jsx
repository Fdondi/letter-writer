import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  buildGroupedModels,
  cycleModelsEqual,
  parseModelKey,
  writeSessionCycleModels,
} from "../utils/autocompleteEditor";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import ModelPickSelector from "./ModelPickSelector";

const panelStyle = {
  width: 300,
  flexShrink: 0,
  display: "flex",
  flexDirection: "column",
  gap: 16,
  padding: 14,
  border: "1px solid var(--border-color)",
  borderRadius: 8,
  background: "var(--panel-bg)",
  overflow: "auto",
  maxHeight: "calc(100vh - 120px)",
};

export default function AutocompleteModelPanel({
  cycleModels,
  activeCompletionModel = "",
  onActiveCompletionModelChange,
  onCycleModelsChange,
  onCycleModelActivated,
  persistedModels,
  roleDefaults = {},
  onPersisted,
  planModel = "",
  onPlanModelChange,
  persistedPlanModel = "",
  planRoleDefaults = {},
  onPlanPersisted,
  onRefreshPlans,
  plansLoading = false,
}) {
  const [availableModels, setAvailableModels] = useState({});
  const [saveError, setSaveError] = useState(null);
  const [saving, setSaving] = useState(false);

  const { grouped } = useMemo(() => buildGroupedModels(availableModels), [availableModels]);
  const modelsDirty = !cycleModelsEqual(cycleModels, persistedModels);
  const planDirty = (planModel || "") !== (persistedPlanModel || "");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/costs/models/");
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setAvailableModels(data || {});
      } catch (e) {
        console.warn("Failed to load model list for autocomplete panel", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const applyCycleChange = useCallback(
    (next) => {
      onCycleModelsChange(next);
      writeSessionCycleModels(next);
    },
    [onCycleModelsChange]
  );

  const handleMakeDefault = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    const payload = {
      autocomplete_models: cycleModels,
    };
    if (planDirty && planModel) {
      payload.autocomplete_plan_model = planModel;
    }
    try {
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      onPersisted?.({
        autocomplete_models: cycleModels,
        ...(planDirty && planModel ? { autocomplete_plan_model: planModel } : {}),
      });
      if (planDirty && planModel) {
        onPlanPersisted?.({ autocomplete_plan_model: planModel });
      }
    } catch (e) {
      setSaveError(e.message || "Failed to save default models");
    } finally {
      setSaving(false);
    }
  }, [cycleModels, planDirty, planModel, onPersisted, onPlanPersisted]);

  const updateCycle = (index, _vendor, _modelId, _effort, composite) => {
    applyCycleChange(cycleModels.map((m, i) => (i === index ? composite : m)));
    onCycleModelActivated?.(composite);
  };

  const addCycleModel = () => {
    const vendors = Object.keys(roleDefaults);
    const vendor =
      vendors.find((v) => !cycleModels.some((m) => parseModelKey(m).vendor === v)) || vendors[0];
    if (!vendor) return;
    const composite = roleDefaults[vendor] || `${vendor}`;
    applyCycleChange([...cycleModels, composite]);
  };

  const removeCycleModel = (index) => {
    applyCycleChange(cycleModels.filter((_, i) => i !== index));
  };

  return (
    <aside style={panelStyle}>
      <div>
        <h3 style={{ margin: "0 0 6px", fontSize: 15, color: "var(--text-color)" }}>Models</h3>
        <p style={{ margin: 0, fontSize: 12, color: "var(--secondary-text-color)", lineHeight: 1.4 }}>
          Session only until saved. Select the active model with a radio button; edit vendor, model, and reasoning per row.
        </p>
        {saveError && (
          <p style={{ margin: "8px 0 0", fontSize: 12, color: "#b91c1c" }}>{saveError}</p>
        )}
      </div>

      <fieldset
        style={{
          margin: 0,
          padding: 0,
          border: "none",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <legend style={{ fontSize: 12, color: "var(--secondary-text-color)", marginBottom: 4, padding: 0 }}>
          Completion models
        </legend>
        {cycleModels.map((composite, index) => (
          <ModelPickSelector
            key={`cycle-${index}`}
            value={composite}
            grouped={grouped}
            roleDefaults={roleDefaults}
            onChange={(...args) => updateCycle(index, ...args)}
            leading={
              <input
                type="radio"
                name="autocomplete-active-model"
                checked={composite === activeCompletionModel}
                onChange={() => onActiveCompletionModelChange?.(composite)}
                aria-label="Active completion model"
                style={{ flexShrink: 0, margin: 0 }}
              />
            }
            trailing={
              <button
                type="button"
                onClick={() => removeCycleModel(index)}
                aria-label="Remove model"
                style={{
                  padding: "2px 8px",
                  fontSize: 12,
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                  background: "transparent",
                  color: "var(--secondary-text-color)",
                  cursor: "pointer",
                }}
              >
                ×
              </button>
            }
          />
        ))}
      </fieldset>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <button
          type="button"
          onClick={addCycleModel}
          style={{
            padding: "4px 10px",
            fontSize: 12,
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            background: "var(--input-bg)",
            color: "var(--text-color)",
            cursor: "pointer",
          }}
        >
          + Add model
        </button>
        <button
          type="button"
          onClick={handleMakeDefault}
          disabled={(!modelsDirty && !planDirty) || saving}
          style={{
            padding: "4px 10px",
            fontSize: 12,
            border: "none",
            borderRadius: 4,
            background: (modelsDirty || planDirty) && !saving ? "#3b82f6" : "#94a3b8",
            color: "white",
            cursor: (modelsDirty || planDirty) && !saving ? "pointer" : "not-allowed",
            opacity: (modelsDirty || planDirty) && !saving ? 1 : 0.85,
          }}
        >
          {saving ? "Saving…" : "Make default"}
        </button>
      </div>

      <div style={{ borderTop: "1px solid var(--border-color)", paddingTop: 12 }}>
        <h3 style={{ margin: "0 0 6px", fontSize: 15, color: "var(--text-color)" }}>Plan model</h3>
        <p style={{ margin: "0 0 8px", fontSize: 12, color: "var(--secondary-text-color)", lineHeight: 1.4 }}>
          Plans what each section should address from job, CV, and section goals.
        </p>
        <ModelPickSelector
          value={planModel}
          grouped={grouped}
          roleDefaults={planRoleDefaults}
          onChange={(_v, _m, _e, composite) => onPlanModelChange?.(composite)}
        />
        <button
          type="button"
          onClick={onRefreshPlans}
          disabled={plansLoading || !onRefreshPlans}
          style={{
            marginTop: 8,
            padding: "4px 10px",
            fontSize: 12,
            border: "1px solid var(--border-color)",
            borderRadius: 4,
            background: "var(--input-bg)",
            color: "var(--text-color)",
            cursor: plansLoading ? "wait" : "pointer",
            width: "100%",
          }}
        >
          {plansLoading ? "Planning…" : "Refresh section plans"}
        </button>
      </div>
    </aside>
  );
}
