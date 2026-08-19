import { fetchWithHeartbeat } from "./apiHelpers";
import { createTextDiff } from "./diff";
import { buildAutocompletePlanAiLetter, sectionsToProposalText } from "./autocompleteEditor";

/**
 * Persist a letter document to the backend.
 * Consolidates vendor, agentic, and autocomplete persist paths.
 *
 * @param {object} opts
 * @param {string} opts.letterText - The final letter text
 * @param {object} opts.jobFields - { companyName, jobTitle, location, language, salary, requirements, jobText }
 * @param {string|null} opts.documentId - Existing document ID for updates
 * @param {Array} [opts.aiLetters] - AI letter entries for vendor/agentic flows
 * @param {object} [opts.feedbackExtras] - { feedback_extra_info, feedback_agent_context } for vendor flow
 * @param {object} [opts.autocompleteData] - { sections, proposalLetterText, autocompleteHistory, completionModel, planModel, planCost, cycleModels, totalCost }
 * @returns {Promise<{ documentId: string|null, warnings: string[] }>}
 */
export async function persistLetterDocument({
  letterText,
  jobFields,
  documentId,
  aiLetters,
  feedbackExtras,
  autocompleteData,
}) {
  const trimmed = (letterText || "").trim();
  if (!trimmed) {
    throw new Error("No letter text to save");
  }

  const payload = {
    company_name: jobFields.companyName || "",
    role: jobFields.jobTitle || "",
    location: jobFields.location || "",
    language: jobFields.language || "",
    salary: jobFields.salary || "",
    requirements: Array.isArray(jobFields.requirements) ? jobFields.requirements : jobFields.requirements ? [jobFields.requirements] : [],
    job_text: jobFields.jobText || "",
    letter_text: trimmed,
  };

  if (aiLetters) {
    payload.ai_letters = aiLetters;
  }

  if (feedbackExtras) {
    if (feedbackExtras.feedback_extra_info !== undefined) {
      payload.feedback_extra_info = feedbackExtras.feedback_extra_info;
    }
    if (feedbackExtras.feedback_agent_context !== undefined) {
      payload.feedback_agent_context = feedbackExtras.feedback_agent_context;
    }
  }

  if (autocompleteData) {
    const { sections, proposalLetterText, autocompleteHistory, completionModel, planModel, planCost, cycleModels, totalCost } = autocompleteData;

    const sectionsPayload = (sections || []).map(({ id, title, description, body, plan, proposal }) => ({
      id, title: title ?? "", description: description ?? "", body: body ?? "", plan: plan ?? "", proposal: proposal ?? "",
    }));
    payload.autocomplete_sections = sectionsPayload;

    const proposalText = (proposalLetterText || sectionsToProposalText(sections) || "").trim();
    const planAiLetter = buildAutocompletePlanAiLetter(planModel, proposalText, planCost);
    if (planAiLetter) {
      payload.ai_letters = [planAiLetter];
    }

    const history = autocompleteHistory || { fixed_context: "", chunks: [] };
    payload.autocomplete_history = {
      fixed_context: history.fixed_context || "",
      chunks: Array.isArray(history.chunks) ? history.chunks : [],
      completion_model: completionModel || "",
      plan_model: planModel || "",
      cycle_models: cycleModels || [],
      total_cost: typeof totalCost === "number" ? totalCost : 0,
    };
  }

  const url = documentId ? `/api/documents/${documentId}/` : "/api/documents/";
  const method = documentId ? "PUT" : "POST";

  const result = await fetchWithHeartbeat(url, {
    method,
    body: JSON.stringify(payload),
  });

  const data = result.data;
  const warnings = Array.isArray(data.warnings) ? data.warnings : [];
  const newDocumentId = data?.document?.id || null;

  return { documentId: documentId || newDocumentId, warnings };
}

/**
 * Build ai_letters array for vendor flow from letters map, costs, feedback, and final paragraphs.
 */
export function buildVendorAiLetters({ letters, vendorCosts, vendorFeedback, finalParagraphs }) {
  const correctionsByVendor = {};
  (finalParagraphs || []).forEach((p) => {
    if (p.vendor && p.originalText !== undefined && p.text !== p.originalText) {
      if (!correctionsByVendor[p.vendor]) correctionsByVendor[p.vendor] = [];
      const diffs = createTextDiff(p.originalText || "", p.text || "");
      if (Array.isArray(diffs) && diffs.length > 0) {
        correctionsByVendor[p.vendor].push(...diffs);
      }
    }
  });

  return Object.entries(letters).map(([vendor, text]) => {
    const feedback = (vendorFeedback || {})[vendor] || {};
    const chunksUsed = (finalParagraphs || []).filter((p) => p.vendor === vendor).length;
    return {
      vendor,
      text: text || "",
      cost: (vendorCosts || {})[vendor] ?? null,
      rating: feedback.rating || null,
      comment: feedback.comment || "",
      chunks_used: chunksUsed,
      user_corrections: correctionsByVendor[vendor] || [],
    };
  });
}

/**
 * Build ai_letters array for agentic flow.
 */
export function buildAgenticAiLetters({ agenticState, vendorFeedback, finalParagraphs, letterText }) {
  const finalLetters = agenticState?.final_letters || {};
  const paragraphs = Array.isArray(finalParagraphs) ? finalParagraphs : [];
  const vendorsFromParagraphs = paragraphs.map((p) => p?.vendor).filter((v) => typeof v === "string" && v.trim().length > 0);
  const vendorKeys = Array.from(new Set([...Object.keys(finalLetters).filter(Boolean), ...vendorsFromParagraphs]));
  const totalCost = agenticState?.cost ?? null;
  const costPerVendor = vendorKeys.length ? (totalCost != null ? totalCost / vendorKeys.length : null) : totalCost;

  const correctionsByVendor = {};
  paragraphs.forEach((p) => {
    if (!p?.vendor) return;
    if (p.originalText === undefined || p.text === p.originalText) return;
    if (!correctionsByVendor[p.vendor]) correctionsByVendor[p.vendor] = [];
    const diffs = createTextDiff(p.originalText || "", p.text || "");
    if (Array.isArray(diffs) && diffs.length > 0) correctionsByVendor[p.vendor].push(...diffs);
  });

  if (vendorKeys.length > 0) {
    return vendorKeys.map((vendor) => ({
      vendor,
      text: (finalLetters[vendor] || paragraphs.filter((p) => p?.vendor === vendor).map((p) => p?.text || "").join("\n\n")).trim(),
      cost: costPerVendor,
      rating: (vendorFeedback || {})[vendor]?.rating || null,
      comment: (vendorFeedback || {})[vendor]?.comment || "",
      chunks_used: paragraphs.filter((p) => p?.vendor === vendor).length,
      user_corrections: correctionsByVendor[vendor] || [],
    }));
  }
  return [{
    vendor: agenticState?.draft_vendor || "agentic",
    text: (letterText || "").trim(),
    cost: totalCost,
    rating: (vendorFeedback || {})[agenticState?.draft_vendor || "agentic"]?.rating || null,
    comment: "",
    chunks_used: 0,
    user_corrections: [],
  }];
}
