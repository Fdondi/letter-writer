import React, { useMemo } from "react";
import {
  MODEL_PICK_SELECT_STYLE,
  formatModelPickKey,
  formatModelPriceSummary,
  defaultPriceComparisonColor,
  getModelEntry,
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
  /** When set, vendor is fixed (no vendor dropdown) — use in per-vendor settings rows. */
  fixedVendor = null,
  /** Config default composite — matching model/effort options show "(default)" in the label. */
  defaultComposite = null,
  /** Show input/output $/1M next to the selects (requires pricing on grouped entries). */
  showPricing = true,
  /** Settings rows: full-width model select, pricing on a second line. */
  wideLayout = false,
}) {
  const parsed = useMemo(() => parseModelPickKey(value), [value]);
  const defaultParsed = useMemo(
    () => parseModelPickKey(defaultComposite || ""),
    [defaultComposite]
  );
  const vendors = useMemo(() => {
    const keys = new Set(Object.keys(grouped || {}));
    Object.keys(roleDefaults || {}).forEach((v) => keys.add(v));
    if (fixedVendor) keys.add(fixedVendor);
    return [...keys].sort();
  }, [grouped, roleDefaults, fixedVendor]);

  const vendor =
    fixedVendor ||
    parsed.vendor ||
    (roleDefaults && Object.keys(roleDefaults).length === 1
      ? Object.keys(roleDefaults)[0]
      : "") ||
    vendors[0] ||
    "";
  const modelsForVendor = grouped?.[vendor] || [];
  const modelId =
    (parsed.vendor === vendor || !parsed.vendor ? parsed.modelId : "") ||
    resolveModelIdFromDefaults(vendor, roleDefaults, grouped);
  const reasoningEfforts = getReasoningEffortsForModel(grouped, vendor, modelId);
  const showEffortSelect =
    showReasoning && reasoningEfforts.length > 0;
  const reasoningEffort = showEffortSelect
    ? parsed.reasoningEffort ||
      resolveReasoningEffortFromDefaults(vendor, roleDefaults, grouped, modelId)
    : "";

  const selectedEntry = getModelEntry(grouped, vendor, modelId);
  const defaultEntry = defaultParsed.modelId
    ? getModelEntry(grouped, defaultParsed.vendor || vendor, defaultParsed.modelId)
    : null;
  const priceSummary = showPricing ? formatModelPriceSummary(selectedEntry) : null;
  const defaultPriceSummary =
    showPricing && defaultComposite ? formatModelPriceSummary(defaultEntry) : null;
  const defaultPriceColor = defaultPriceComparisonColor(selectedEntry, defaultEntry);

  const emit = (v, m, effort) => {
    onChange?.(v, m, effort, formatModelPickKey(v, m, effort));
  };

  const isDefaultModelId = (id) =>
    Boolean(defaultParsed.modelId) && id === defaultParsed.modelId;

  const modelOptionLabel = (m) => {
    const name = m.name || m.id;
    return isDefaultModelId(m.id) ? `${name} (default)` : name;
  };

  const effortOptionLabel = (effort) => {
    const label = reasoningEffortLabel(effort);
    if (
      isDefaultModelId(modelId) &&
      defaultParsed.reasoningEffort &&
      effort === defaultParsed.reasoningEffort
    ) {
      return `${label} (default)`;
    }
    return label;
  };

  const rowStyle = wideLayout
    ? {
        display: "flex",
        flexDirection: "column",
        alignItems: "stretch",
        gap: 4,
        width: "100%",
        minWidth: 0,
        ...style,
      }
    : {
        display: "flex",
        gap: 6,
        alignItems: "center",
        ...style,
      };
  const sel = { ...MODEL_PICK_SELECT_STYLE, ...selectStyle };
  const modelSelectStyle = wideLayout
    ? { ...sel, flex: "1 1 auto", minWidth: 360, maxWidth: "none", width: "100%" }
    : sel;
  const effortSelectStyle = wideLayout
    ? { ...sel, flex: "0 0 auto", minWidth: 96, maxWidth: "none" }
    : { ...sel, flex: "0 1 auto", minWidth: 72 };

  const controlsRow = (
    <>
      {leading}
      {!fixedVendor ? (
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
      ) : null}
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
        style={modelSelectStyle}
      >
        {modelsForVendor.length === 0 ? (
          <option value={modelId}>
            {modelId ? modelOptionLabel({ id: modelId, name: modelId }) : "—"}
          </option>
        ) : (
          modelsForVendor.map((m) => (
            <option key={m.composite || `${vendor}/${m.id}`} value={m.id}>
              {modelOptionLabel(m)}
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
          style={effortSelectStyle}
        >
          {reasoningEfforts.map((effort) => (
            <option key={effort} value={effort}>
              {effortOptionLabel(effort)}
            </option>
          ))}
        </select>
      ) : null}
      {!wideLayout && trailing}
    </>
  );

  const priceBlock = priceSummary ? (
    <span
      aria-label="Model pricing"
      style={{
        fontSize: 12,
        color: "var(--secondary-text-color)",
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      {priceSummary}
      {defaultPriceSummary ? (
        <>
          {" ("}
          <span style={{ color: defaultPriceColor }}>{defaultPriceSummary}</span>
          {")"}
        </>
      ) : null}
    </span>
  ) : null;

  return (
    <div style={rowStyle}>
      {wideLayout ? (
        <>
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              flexWrap: "nowrap",
              width: "100%",
              minWidth: 0,
            }}
          >
            {controlsRow}
            {trailing}
          </div>
          {priceBlock}
        </>
      ) : (
        <>
          {controlsRow}
          {priceBlock}
        </>
      )}
    </div>
  );
}
