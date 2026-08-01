/**
 * Helpers to rehydrate Compose UI from a server session_state snapshot
 * (reload recovery or restore-from-backup).
 */

function safeString(value) {
  return value == null ? "" : String(value);
}

function normalizeRequirements(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

/**
 * Build form field updates from session_state.metadata.common + job_text.
 * Returns a plain object of field values (caller applies setters).
 */
export function extractFormFieldsFromSessionState(state) {
  if (!state || typeof state !== "object") return null;
  const common = state.metadata?.common || {};
  const fields = {};

  if (state.job_text != null) fields.jobText = safeString(state.job_text);
  if (common.company_name != null) fields.companyName = safeString(common.company_name);
  if (common.job_title != null) fields.jobTitle = safeString(common.job_title);
  if (common.location != null) fields.location = safeString(common.location);
  if (common.language != null) fields.language = safeString(common.language);
  if (common.salary != null) fields.salary = safeString(common.salary);
  if (common.additional_user_info != null) {
    fields.additionalUserInfo = safeString(common.additional_user_info);
  }
  if (common.additional_company_info != null) {
    fields.additionalCompanyInfo = safeString(common.additional_company_info);
  }
  if (common.hire_problem != null) fields.hireProblem = safeString(common.hire_problem);
  if (common.requirements != null) {
    fields.requirements = normalizeRequirements(common.requirements);
  }
  if (common.competences && typeof common.competences === "object") {
    fields.competences = common.competences;
  }
  if (common.point_of_contact && typeof common.point_of_contact === "object") {
    fields.pointOfContact = {
      name: safeString(common.point_of_contact.name),
      role: safeString(common.point_of_contact.role),
      contact_details: safeString(common.point_of_contact.contact_details),
      notes: safeString(common.point_of_contact.notes),
      company: safeString(common.point_of_contact.company),
    };
  }
  return Object.keys(fields).length ? fields : null;
}

/**
 * Map session vendors dict → phase shelf entries for populatePhaseShelf.
 * Each entry: { phaseName, vendor, data }
 */
export function extractVendorShelfEntries(vendors) {
  const entries = [];
  if (!vendors || typeof vendors !== "object") return entries;

  Object.entries(vendors).forEach(([vendor, vdata]) => {
    if (!vdata || typeof vdata !== "object") return;

    const hasBackground =
      vdata.company_report ||
      (Array.isArray(vdata.top_docs) && vdata.top_docs.length > 0);
    if (hasBackground) {
      const data = {};
      if (vdata.company_report != null) data.company_report = vdata.company_report;
      if (vdata.top_docs != null) data.top_docs = vdata.top_docs;
      if (vdata.cost != null) data.cost = vdata.cost;
      entries.push({ phaseName: "background", vendor, data });
    }

    if (vdata.letter_plan != null && vdata.letter_plan !== "") {
      entries.push({
        phaseName: "plan",
        vendor,
        data: { letter_plan: vdata.letter_plan },
      });
    }

    if (vdata.draft_letter != null && vdata.draft_letter !== "") {
      const data = { draft_letter: vdata.draft_letter };
      if (vdata.feedback != null) data.feedback = vdata.feedback;
      if (vdata.cost != null) data.cost = vdata.cost;
      entries.push({ phaseName: "draft", vendor, data });
    }

    if (vdata.final_letter != null && vdata.final_letter !== "") {
      const data = { final_letter: vdata.final_letter };
      if (vdata.cost != null) data.cost = vdata.cost;
      entries.push({ phaseName: "refine", vendor, data });
    }
  });

  return entries;
}

/**
 * Infer vendor UI stage from restored vendor artifacts.
 * @returns {"input"|"phases"|"assembly"}
 */
export function inferVendorStageFromVendors(vendors) {
  if (!vendors || typeof vendors !== "object") return "input";
  let hasAny = false;
  let hasFinal = false;
  Object.values(vendors).forEach((vdata) => {
    if (!vdata || typeof vdata !== "object") return;
    if (
      vdata.company_report ||
      vdata.letter_plan ||
      vdata.draft_letter ||
      vdata.final_letter ||
      (Array.isArray(vdata.top_docs) && vdata.top_docs.length)
    ) {
      hasAny = true;
    }
    if (vdata.final_letter) hasFinal = true;
  });
  if (hasFinal) return "assembly";
  if (hasAny) return "phases";
  return "input";
}

/**
 * Letters map from vendor final_letter fields.
 */
export function extractLettersFromVendors(vendors) {
  const letters = {};
  if (!vendors || typeof vendors !== "object") return letters;
  Object.entries(vendors).forEach(([vendor, vdata]) => {
    if (vdata && typeof vdata === "object" && vdata.final_letter) {
      letters[vendor] = vdata.final_letter;
    } else if (vdata && typeof vdata === "object" && vdata.draft_letter) {
      letters[vendor] = vdata.draft_letter;
    }
  });
  return letters;
}
