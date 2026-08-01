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

/** USD per 1M tokens for display next to model pickers. */
export function formatPricePerMillion(usd) {
  const n = Number(usd);
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

export function formatModelPriceSummary(entry) {
  if (!entry) return null;
  const hasInput = entry.input != null && Number.isFinite(Number(entry.input));
  const hasOutput = entry.output != null && Number.isFinite(Number(entry.output));
  if (!hasInput && !hasOutput) return null;
  return `${formatPricePerMillion(entry.input)} in · ${formatPricePerMillion(entry.output)} out / 1M`;
}

/** Sum of input + output $/1M — used to compare selected vs config default. */
export function modelPriceTotal(entry) {
  if (!entry) return null;
  const inp = Number(entry.input);
  const out = Number(entry.output);
  if (!Number.isFinite(inp) || !Number.isFinite(out)) return null;
  return inp + out;
}

/**
 * Color for parenthetical default price vs selected.
 * Red when default was cheaper (selected costs more); green when default was pricier.
 */
export function defaultPriceComparisonColor(selectedEntry, defaultEntry) {
  const selectedTotal = modelPriceTotal(selectedEntry);
  const defaultTotal = modelPriceTotal(defaultEntry);
  if (selectedTotal == null || defaultTotal == null || selectedTotal === defaultTotal) {
    return "var(--secondary-text-color)";
  }
  if (defaultTotal < selectedTotal) return "#dc2626";
  return "#16a34a";
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
