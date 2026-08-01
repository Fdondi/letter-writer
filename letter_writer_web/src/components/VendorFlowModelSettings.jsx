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

  if (!flows.length) {
    return (
      <p style={{ color: "var(--secondary-text-color)", fontStyle: "italic", margin: 0 }}>
        Loading model flows…
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {flows.map((flow) => {
        const isExpanded = expandedFlowId === flow.id;
        return (
          <div
            key={flow.id}
            style={{
              border: "1px solid var(--border-color)",
              borderRadius: 6,
              overflow: "hidden",
            }}
          >
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
            {isExpanded ? (
              <div style={{ padding: "16px 20px 20px", display: "flex", flexDirection: "column", gap: 24 }}>
                {flowVendors.map((vendorKey) => {
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
    </div>
  );
}
