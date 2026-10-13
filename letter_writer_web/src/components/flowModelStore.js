import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { buildGroupedModels } from "../utils/modelPicker";
import { readSessionPlanModel, writeSessionPlanModel } from "../utils/autocompleteEditor";
import {
  buildVendorRoleOverridesFromModels,
  flattenFlowRoleDefaults,
  mergeVendorRoleModelsFromDefaults,
} from "./VendorFlowModelSettings";

let state = {
  ready: false,
  flows: [],
  grouped: {},
  vendorRoleModels: {},
  extractionVendor: "openai",
  autocompleteModels: [],
  planModel: "",
  error: null,
  saving: false,
};

const listeners = new Set();
let loadPromise = null;
let saveChain = Promise.resolve();
let pendingSaves = 0;

function emit() {
  listeners.forEach((listener) => listener());
}

export function subscribeFlowModels(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getFlowModelState() {
  return state;
}

function replaceAutocompleteModel(models, vendor, composite) {
  let found = false;
  const next = (models || []).map((entry) => {
    if (String(entry).split("/")[0] === vendor) {
      found = true;
      return composite;
    }
    return entry;
  });
  if (!found) next.push(composite);
  return next;
}

export function ensureFlowModelsLoaded() {
  if (state.ready) return Promise.resolve(state);
  if (!loadPromise) {
    loadPromise = (async () => {
      const [modelsRes, settingsRes] = await Promise.all([
        fetch("/api/costs/models/"),
        fetch("/api/personal-data/", { credentials: "include" }),
      ]);
      let grouped = {};
      if (modelsRes.ok) {
        const modelsData = await modelsRes.json();
        grouped = buildGroupedModels(modelsData || {}).grouped;
      }
      let flows = [];
      let vendorRoleModels = {};
      let extractionVendor = "openai";
      let autocompleteModels = [];
      let planModel = "";
      if (settingsRes.ok) {
        const data = await settingsRes.json();
        flows = Array.isArray(data.vendor_model_flows) ? data.vendor_model_flows : [];
        const roleDefaults = flattenFlowRoleDefaults(flows);
        vendorRoleModels = mergeVendorRoleModelsFromDefaults(
          data.vendor_role_models || data.phase_models || {},
          roleDefaults
        );
        extractionVendor = data.extraction_vendor || "openai";
        autocompleteModels = Array.isArray(data.autocomplete_models) ? data.autocomplete_models : [];
        planModel = data.autocomplete_plan_model || "";
      }
      state = {
        ...state,
        ready: true,
        flows,
        grouped,
        vendorRoleModels,
        extractionVendor,
        autocompleteModels,
        planModel,
      };
      emit();
      return state;
    })().catch((err) => {
      console.warn("Failed to load flow model settings", err);
      state = { ...state, ready: true, error: "Could not load model choices" };
      emit();
      loadPromise = null;
      return state;
    });
  }
  return loadPromise;
}

function enqueueSave(extras) {
  pendingSaves += 1;
  state = { ...state, saving: true, error: null };
  emit();
  saveChain = saveChain
    .catch(() => {})
    .then(async () => {
      const roleDefaults = flattenFlowRoleDefaults(state.flows);
      const overrides = buildVendorRoleOverridesFromModels(state.vendorRoleModels, roleDefaults);
      const body = {
        vendor_role_model_overrides: overrides,
        extraction_vendor: state.extractionVendor,
        ...extras,
      };
      await fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify(body),
      });
      state = { ...state, error: null };
    })
    .catch((err) => {
      console.warn("Failed to save model choice", err);
      state = { ...state, error: "Could not save model choice" };
    })
    .finally(() => {
      pendingSaves = Math.max(0, pendingSaves - 1);
      if (pendingSaves === 0) state = { ...state, saving: false };
      emit();
    });
}

export function updateFlowRole(vendor, role, composite) {
  const vendorRoleModels = {
    ...state.vendorRoleModels,
    [vendor]: {
      ...(state.vendorRoleModels[vendor] || {}),
      [role]: composite,
    },
  };
  let autocompleteModels = state.autocompleteModels;
  let planModel = state.planModel;
  const extras = {};
  if (role === "autocomplete" && autocompleteModels.length > 0) {
    autocompleteModels = replaceAutocompleteModel(autocompleteModels, vendor, composite);
    extras.autocomplete_models = autocompleteModels;
  }
  if (role === "autocomplete_plan") {
    const current = readSessionPlanModel() || planModel || "";
    const currentVendor = current.includes("/") ? current.split("/")[0] : current;
    if (!current || currentVendor === vendor) {
      planModel = composite;
      writeSessionPlanModel(composite);
      extras.autocomplete_plan_model = composite;
    }
  }
  state = { ...state, vendorRoleModels, autocompleteModels, planModel };
  emit();
  enqueueSave(extras);
}

export function updateExtractionVendor(vendor) {
  if (!vendor || vendor === state.extractionVendor) return;
  state = { ...state, extractionVendor: vendor };
  emit();
  enqueueSave({});
}
