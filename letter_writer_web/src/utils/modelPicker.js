/**
 * Shared vendor / model / reasoning-effort helpers for ModelPickSelector.
 */

import {
  buildGroupedModels,
  formatModelKey,
  parseModelKey,
} from "./autocompleteEditor";

export { buildGroupedModels, formatModelKey, parseModelKey };

export const MODEL_PICK_SELECT_STYLE = {
  padding: "4px 6px",
  fontSize: 12,
  border: "1px solid var(--border-color)",
  borderRadius: 4,
  background: "var(--input-bg)",
  color: "var(--text-color)",
  minWidth: 0,
  flex: 1,
};

export const parseModelPickKey = parseModelKey;
export const formatModelPickKey = formatModelKey;

export function reasoningEffortLabel(effort) {
  const e = String(effort || "").trim();
  if (!e || e.toLowerCase() === "none") return "None";
  if (e.toLowerCase() === "off") return "Off";
  return e.charAt(0).toUpperCase() + e.slice(1);
}

export function getModelEntry(grouped, vendor, modelId) {
  const list = grouped?.[vendor] || [];
  return list.find((m) => m.id === modelId) || null;
}

export function getReasoningEffortsForModel(grouped, vendor, modelId) {
  const entry = getModelEntry(grouped, vendor, modelId);
  return Array.isArray(entry?.reasoningEfforts) ? entry.reasoningEfforts : [];
}

export function defaultReasoningEffort(efforts) {
  if (!efforts?.length) return "";
  const none = efforts.find((e) => String(e).toLowerCase() === "none");
  if (none !== undefined) return none;
  const off = efforts.find((e) => String(e).toLowerCase() === "off");
  if (off !== undefined) return off;
  return efforts[0];
}

export function resolveModelIdFromDefaults(vendor, roleDefaults, grouped) {
  const parsed = parseModelKey(roleDefaults?.[vendor] || "");
  if (parsed.modelId) return parsed.modelId;
  const models = grouped?.[vendor] || [];
  return models[0]?.id || "";
}

export function resolveReasoningEffortFromDefaults(vendor, roleDefaults, grouped, modelId) {
  const parsed = parseModelKey(roleDefaults?.[vendor] || "");
  const efforts = getReasoningEffortsForModel(grouped, vendor, modelId);
  if (parsed.modelId === modelId && parsed.reasoningEffort && efforts.includes(parsed.reasoningEffort)) {
    return parsed.reasoningEffort;
  }
  return defaultReasoningEffort(efforts);
}
