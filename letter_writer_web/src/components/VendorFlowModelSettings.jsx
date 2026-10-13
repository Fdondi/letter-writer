import React, { useMemo, useState } from "react";
import ModelPickSelector from "./ModelPickSelector";
import { formatModelKey, parseModelKey } from "../utils/autocompleteEditor";

function normalizeCompositeKey(key) {
  const { vendor, modelId, reasoningEffort } = parseModelKey(key);
  return formatModelKey(vendor, modelId, reasoningEffort);
}

export function mergeVendorRoleModelsFromDefaults(models, roleDefaultsByRole) {
  const merged = {};
  const vendors = new Set();
  Object.values(roleDefaultsByRole || {}).forEach((vendorMap) => {
    Object.keys(vendorMap || {}).forEach((v) => vendors.add(v));
  });
  Object.keys(models || {}).forEach((v) => vendors.add(v));
  vendors.forEach((vendor) => {
    merged[vendor] = {};
    Object.entries(roleDefaultsByRole || {}).forEach(([role, vendorMap]) => {
      merged[vendor][role] = models?.[vendor]?.[role] || vendorMap?.[vendor] || "";
    });
  });
  return merged;
}

export function flattenFlowRoleDefaults(flows) {
  const out = {};
  (flows || []).forEach((flow) => {
    Object.entries(flow.role_defaults || {}).forEach(([role, vendorMap]) => {
      out[role] = vendorMap;
    });
  });
  return out;
}

export function buildVendorRoleOverridesFromModels(models, roleDefaultsByRole) {
  const out = {};
  Object.entries(models || {}).forEach(([vendor, roles]) => {
    Object.entries(roles || {}).forEach(([role, value]) => {
      const defaultVal = roleDefaultsByRole?.[role]?.[vendor];
      if (value && value !== defaultVal && normalizeCompositeKey(value) !== normalizeCompositeKey(defaultVal || "")) {
        if (!out[vendor]) out[vendor] = {};
        out[vendor][role] = value;
      }
    });
  });
  return out;
}

function isAtConfigDefault(vendor, role, value, roleDefaultsByRole) {
  const configDefault = roleDefaultsByRole?.[role]?.[vendor];
  if (!configDefault) return !value;
  const current = value || configDefault;
  return normalizeCompositeKey(current) === normalizeCompositeKey(configDefault);
}

function VendorRoleRow({ vendorKey, roleKey, roleLabel, currentVal, configDefault, roleDefaults, grouped, onChange }) {
  const isDefault = isAtConfigDefault(vendorKey, roleKey, currentVal, { [roleKey]: roleDefaults });
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(96px, auto) minmax(0, 1fr)",
        gap: "12px 16px",
        alignItems: "start",
        width: "100%",
      }}
    >
      <span
        style={{
          paddingTop: 8,
          fontSize: 13,
          color: "var(--secondary-text-color)",
          whiteSpace: "nowrap",
        }}
      >
        {roleLabel}
      </span>
      <ModelPickSelector
        fixedVendor={vendorKey}
        wideLayout
        value={currentVal}
        defaultComposite={configDefault}
        grouped={grouped}
        roleDefaults={roleDefaults}
        onChange={(_v, _m, _e, composite) => onChange(vendorKey, roleKey, composite)}
        selectStyle={{ fontSize: 13, padding: "6px 10px" }}
        style={{ width: "100%" }}
        trailing={
          !isDefault ? (
            <button
              type="button"
              onClick={() => onChange(vendorKey, roleKey, configDefault)}
              style={{
                padding: "6px 10px",
                fontSize: 12,
                border: "1px solid var(--border-color)",
                borderRadius: 4,
                background: "transparent",
                color: "var(--secondary-text-color)",
                cursor: "pointer",
                flexShrink: 0,
                whiteSpace: "nowrap",
              }}
            >
              Reset to default
            </button>
          ) : null
        }
      />
      {!isDefault && configDefault ? (
        <p
          style={{
            gridColumn: 2,
            margin: 0,
            fontSize: 12,
            color: "var(--secondary-text-color)",
          }}
        >
          Config default: <code>{configDefault}</code>
        </p>
      ) : null}
    </div>
  );
}

/**
 * Per-flow vendor model settings. Defaults come from clients/&lt;vendor&gt;.json via API.
 */
export default function VendorFlowModelSettings({
  flows = [],
  vendorRoleModels = {},
  onVendorRoleModelsChange,
  grouped = {},
  vendors = [],
  onSave,
  saving = false,
  /** Render one flow inline (popover), without the accordion chrome. */
  embeddedFlowId = null,
  /** When set, only these vendor keys are listed. Empty array shows a hint. */
  vendorKeys = null,
  extractionVendor = "",
  onExtractionVendorChange = null,
  hideSaveButton = false,
  saveError = null,
}) {
  const [expandedFlowId, setExpandedFlowId] = useState(null);
  const roleDefaultsByRole = useMemo(() => flattenFlowRoleDefaults(flows), [flows]);

  const flowVendors = useMemo(() => {
    const keys = new Set(vendors);
    Object.values(roleDefaultsByRole).forEach((vendorMap) => {
      Object.keys(vendorMap || {}).forEach((v) => keys.add(v));
    });
    return [...keys].sort();
  }, [vendors, roleDefaultsByRole]);

  const updateRole = (vendor, role, composite) => {
    onVendorRoleModelsChange?.((prev) => ({
      ...prev,
      [vendor]: {
        ...(prev[vendor] || {}),
        [role]: composite,
      },
    }));
  };

  const toggleFlow = (flowId) => {
    setExpandedFlowId((prev) => (prev === flowId ? null : flowId));
  };

  const shownFlows = embeddedFlowId ? flows.filter((flow) => flow.id === embeddedFlowId) : flows;

  if (!flows.length) {
    return (
      <p style={{ color: "var(--secondary-text-color)", fontStyle: "italic", margin: 0 }}>
        Loading model flows…
      </p>
    );
  }

  if (embeddedFlowId && shownFlows.length === 0) {
    return (
      <p style={{ color: "var(--secondary-text-color)", fontStyle: "italic", margin: 0 }}>
        No models for this step.
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: embeddedFlowId ? 16 : 12 }}>
      {shownFlows.map((flow) => {
        const isEmbedded = embeddedFlowId === flow.id;
        const isExpanded = isEmbedded || expandedFlowId === flow.id;
        const vendorsForFlow = Array.isArray(vendorKeys)
          ? flowVendors.filter((vendorKey) => vendorKeys.includes(vendorKey))
          : flowVendors;
        return (
          <div
            key={flow.id}
            style={
              isEmbedded
                ? undefined
                : {
                    border: "1px solid var(--border-color)",
                    borderRadius: 6,
                    overflow: "hidden",
                  }
            }
          >
            {isEmbedded ? null : (
            <button
              type="button"
              onClick={() => toggleFlow(flow.id)}
              aria-expanded={isExpanded}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "14px 16px",
                border: "none",
                background: "var(--header-bg)",
                color: "var(--text-color)",
                cursor: "pointer",
                textAlign: "left",
              }}
            >
              <span style={{ fontSize: 10, marginTop: 4, flexShrink: 0 }}>
                {isExpanded ? "▼" : "▶"}
              </span>
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: "block", fontSize: 15, fontWeight: 600 }}>{flow.title}</span>
                <span
                  style={{
                    display: "block",
                    marginTop: 4,
                    fontSize: 13,
                    fontWeight: 400,
                    color: "var(--secondary-text-color)",
                  }}
                >
                  {flow.description}
                </span>
              </span>
            </button>
            )}
            {isExpanded ? (
              <div style={{ padding: isEmbedded ? 0 : "16px 20px 20px", display: "flex", flexDirection: "column", gap: 24 }}>
                {flow.id === "initial" && onExtractionVendorChange ? (
                  <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, color: "var(--text-color)" }}>
                    <span style={{ fontWeight: 600 }}>Extract uses</span>
                    <select
                      aria-label="Vendor that runs extract"
                      value={extractionVendor || vendorsForFlow[0] || ""}
                      onChange={(e) => onExtractionVendorChange(e.target.value)}
                      style={{ fontSize: 13, padding: "6px 8px", maxWidth: 240 }}
                    >
                      {vendorsForFlow.map((vendorKey) => (
                        <option key={vendorKey} value={vendorKey}>
                          {vendorKey}
                        </option>
                      ))}
                    </select>
                    <span style={{ color: "var(--secondary-text-color)", fontSize: 12 }}>
                      Competences, company fields, and similar-offer ranking use this vendor&apos;s models below.
                    </span>
                  </label>
                ) : null}
                {Array.isArray(vendorKeys) && vendorsForFlow.length === 0 ? (
                  <p style={{ margin: 0, fontSize: 13, color: "var(--secondary-text-color)" }}>
                    Select at least one vendor above. These models are the ones that button will call.
                  </p>
                ) : null}
                {vendorsForFlow.map((vendorKey) => {
                  const rolesForVendor = (flow.roles || []).filter(
                    (r) => roleDefaultsByRole[r.key]?.[vendorKey]
                  );
                  if (rolesForVendor.length === 0) return null;
                  return (
                    <div key={`${flow.id}-${vendorKey}`}>
                      <strong
                        style={{
                          display: "block",
                          marginBottom: 12,
                          textTransform: "capitalize",
                          color: "var(--text-color)",
                          fontSize: 14,
                        }}
                      >
                        {vendorKey}
                        {flow.id === "initial" && vendorKey === extractionVendor ? (
                          <span style={{ marginLeft: 8, fontWeight: 600, fontSize: 12, color: "var(--text-color)" }}>
                            used for Extract
                          </span>
                        ) : null}
                        <span
                          style={{
                            marginLeft: 8,
                            fontWeight: 400,
                            fontSize: 12,
                            color: "var(--secondary-text-color)",
                          }}
                        >
                          clients/{vendorKey}.json
                        </span>
                      </strong>
                      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                        {rolesForVendor.map(({ key, label }) => {
                          const configDefault = roleDefaultsByRole[key]?.[vendorKey] || "";
                          const currentVal = vendorRoleModels?.[vendorKey]?.[key] || configDefault;
                          return (
                            <VendorRoleRow
                              key={`${flow.id}-${vendorKey}-${key}`}
                              vendorKey={vendorKey}
                              roleKey={key}
                              roleLabel={label}
                              currentVal={currentVal}
                              configDefault={configDefault}
                              roleDefaults={roleDefaultsByRole[key] || {}}
                              grouped={grouped}
                              onChange={updateRole}
                            />
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
      {hideSaveButton ? (
        saveError ? (
          <p style={{ margin: 0, fontSize: 12, color: "var(--error-text)" }}>{saveError}</p>
        ) : saving ? (
          <p style={{ margin: 0, fontSize: 12, color: "var(--secondary-text-color)" }}>Saving…</p>
        ) : null
      ) : (
      <div>
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          style={{
            padding: "6px 12px",
            backgroundColor: "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: saving ? "not-allowed" : "pointer",
            opacity: saving ? 0.7 : 1,
            fontSize: "14px",
          }}
        >
          {saving ? "Saving…" : "Save model overrides"}
        </button>
      </div>
      )}
    </div>
  );
}
