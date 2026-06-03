import React, { useEffect, useMemo, useState } from "react";
import ModelPickSelector from "./ModelPickSelector";
import {
  buildGroupedModels,
  normalizeStoredModels,
  parseModelKey,
  readSessionPlanModel,
  writeSessionPlanModel,
} from "../utils/autocompleteEditor";

/**
 * Plan-model picker for autocomplete (section plans). Persists to session storage
 * so AutocompleteFlow uses the same choice on entry.
 */
export default function AutocompletePlanModelSelect({
  selectStyle,
  style,
  label = "Plan model",
}) {
  const [availableModels, setAvailableModels] = useState({});
  const [planRoleDefaults, setPlanRoleDefaults] = useState({});
  const [planModel, setPlanModel] = useState("");
  const [ready, setReady] = useState(false);

  const { grouped } = useMemo(() => buildGroupedModels(availableModels), [availableModels]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [modelsRes, settingsRes] = await Promise.all([
          fetch("/api/costs/models/"),
          fetch("/api/personal-data/", { credentials: "include" }),
        ]);
        if (cancelled) return;
        if (modelsRes.ok) {
          const data = await modelsRes.json();
          setAvailableModels(data || {});
        }
        let defaults = {};
        let persisted = "";
        if (settingsRes.ok) {
          const data = await settingsRes.json();
          defaults = data.autocomplete_plan_role_defaults || {};
          persisted = data.autocomplete_plan_model || "";
          setPlanRoleDefaults(defaults);
        }
        const parsed = parseModelKey(
          persisted.includes("/") ? persisted : defaults[persisted] || persisted
        );
        const baseline = parsed.modelId ? parsed.composite : Object.values(defaults)[0] || "";
        const fromSession = readSessionPlanModel();
        const sessionNorm = fromSession
          ? normalizeStoredModels([fromSession], defaults)[0]
          : null;
        const next = sessionNorm || baseline;
        setPlanModel(next);
        if (next) writeSessionPlanModel(next);
        setReady(true);
      } catch (e) {
        console.warn("Failed to load autocomplete plan model options", e);
        setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (_v, _m, _e, composite) => {
    setPlanModel(composite);
    writeSessionPlanModel(composite);
  };

  if (!ready || !planModel) {
    return null;
  }

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 8,
        ...style,
      }}
    >
      <span
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: "var(--text-color)",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      <ModelPickSelector
        value={planModel}
        grouped={grouped}
        roleDefaults={planRoleDefaults}
        onChange={handleChange}
        selectStyle={{ fontSize: 13, padding: "6px 8px", ...selectStyle }}
        style={{ flex: "1 1 200px", minWidth: 0, maxWidth: 480 }}
      />
    </div>
  );
}
