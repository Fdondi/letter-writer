import React, { useMemo } from "react";
import {
  MODEL_PICK_SELECT_STYLE,
  formatModelPickKey,
  getReasoningEffortsForModel,
  parseModelPickKey,
  reasoningEffortLabel,
  resolveModelIdFromDefaults,
  resolveReasoningEffortFromDefaults,
  defaultReasoningEffort,
} from "../utils/modelPicker";

/**
 * Vendor + model + optional reasoning-effort picker.
 *
 * @param {object} props
 * @param {string} [props.value] - Composite model key (vendor/model or vendor/model@effort)
 * @param {function} props.onChange - (vendor, modelId, reasoningEffort, composite) => void
 * @param {object} props.grouped - From buildGroupedModels().grouped
 * @param {object} [props.roleDefaults] - vendor -> default composite key
 * @param {boolean} [props.showReasoning=true]
 * @param {object} [props.selectStyle]
 * @param {object} [props.style] - Row container style
 * @param {React.ReactNode} [props.leading] - e.g. radio button
 * @param {React.ReactNode} [props.trailing] - e.g. remove button
 */
export default function ModelPickSelector({
  value = "",
  onChange,
  grouped = {},
  roleDefaults = {},
  showReasoning = true,
  selectStyle,
  style,
  leading = null,
  trailing = null,
}) {
  const parsed = useMemo(() => parseModelPickKey(value), [value]);
  const vendors = useMemo(() => {
    const keys = new Set(Object.keys(grouped || {}));
    Object.keys(roleDefaults || {}).forEach((v) => keys.add(v));
    return [...keys].sort();
  }, [grouped, roleDefaults]);

  const vendor = parsed.vendor || vendors[0] || "";
  const modelsForVendor = grouped?.[vendor] || [];
  const modelId =
    parsed.modelId || resolveModelIdFromDefaults(vendor, roleDefaults, grouped);
  const reasoningEfforts = getReasoningEffortsForModel(grouped, vendor, modelId);
  const showEffortSelect =
    showReasoning && reasoningEfforts.length > 0;
  const reasoningEffort = showEffortSelect
    ? parsed.reasoningEffort ||
      resolveReasoningEffortFromDefaults(vendor, roleDefaults, grouped, modelId)
    : "";

  const rowStyle = {
    display: "flex",
    gap: 6,
    alignItems: "center",
    ...style,
  };
  const sel = { ...MODEL_PICK_SELECT_STYLE, ...selectStyle };

  const emit = (v, m, effort) => {
    onChange?.(v, m, effort, formatModelPickKey(v, m, effort));
  };

  return (
    <div style={rowStyle}>
      {leading}
      <select
        aria-label="Vendor"
        value={vendor}
        onChange={(e) => {
          const nextVendor = e.target.value;
          const nextModelId = resolveModelIdFromDefaults(
            nextVendor,
            roleDefaults,
            grouped
          );
          const nextEffort = resolveReasoningEffortFromDefaults(
            nextVendor,
            roleDefaults,
            grouped,
            nextModelId
          );
          emit(nextVendor, nextModelId, nextEffort);
        }}
        style={sel}
      >
        {vendors.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
      <select
        aria-label="Model"
        value={modelId}
        onChange={(e) => {
          const nextModelId = e.target.value;
          const nextEffort = resolveReasoningEffortFromDefaults(
            vendor,
            roleDefaults,
            grouped,
            nextModelId
          );
          emit(vendor, nextModelId, nextEffort);
        }}
        style={sel}
      >
        {modelsForVendor.length === 0 ? (
          <option value={modelId}>{modelId || "—"}</option>
        ) : (
          modelsForVendor.map((m) => (
            <option key={m.composite || `${vendor}/${m.id}`} value={m.id}>
              {m.name}
            </option>
          ))
        )}
      </select>
      {showEffortSelect ? (
        <select
          aria-label="Reasoning effort"
          value={
            reasoningEfforts.includes(reasoningEffort)
              ? reasoningEffort
              : defaultReasoningEffort(reasoningEfforts)
          }
          onChange={(e) => emit(vendor, modelId, e.target.value)}
          style={{ ...sel, flex: "0 1 auto", minWidth: 72 }}
        >
          {reasoningEfforts.map((effort) => (
            <option key={effort} value={effort}>
              {reasoningEffortLabel(effort)}
            </option>
          ))}
        </select>
      ) : null}
      {trailing}
    </div>
  );
}
