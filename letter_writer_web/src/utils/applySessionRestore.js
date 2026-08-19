import {
  extractFormFieldsFromSessionState,
  extractVendorShelfEntries,
  inferVendorStageFromVendors,
  extractLettersFromVendors,
} from "./sessionRehydrate";
import { normalizeAgenticThreads } from "./agenticThreads";

/**
 * Apply shared JobSession fields from a server session_state snapshot.
 * Returns a flow-specific restore descriptor; callers handle navigation.
 */
export function applyRestoredSessionState(sessionState, setters, { sessionId = null } = {}) {
  if (!sessionState || typeof sessionState !== "object") {
    return { restored: false, vendor: null, agentic: null };
  }

  let restored = false;

  if (sessionId) {
    setters.setPhaseSessionId(sessionId);
    restored = true;
  }

  const fields = extractFormFieldsFromSessionState(sessionState);
  if (fields) {
    if (fields.jobText !== undefined) setters.setJobText(fields.jobText);
    if (fields.companyName !== undefined) setters.setCompanyName(fields.companyName);
    if (fields.jobTitle !== undefined) setters.setJobTitle(fields.jobTitle);
    if (fields.location !== undefined) setters.setLocation(fields.location);
    if (fields.language !== undefined) setters.setLanguage(fields.language);
    if (fields.salary !== undefined) setters.setSalary(fields.salary);
    if (fields.additionalUserInfo !== undefined) setters.setAdditionalUserInfo(fields.additionalUserInfo);
    if (fields.additionalCompanyInfo !== undefined) setters.setAdditionalCompanyInfo(fields.additionalCompanyInfo);
    if (
      String(fields.additionalUserInfo || "").trim() ||
      String(fields.additionalCompanyInfo || "").trim()
    ) {
      setters.setShowAdditionalInfo(true);
    }
    if (fields.hireProblem !== undefined) setters.setHireProblem(fields.hireProblem);
    if (fields.requirements !== undefined) setters.setRequirements(fields.requirements);
    if (fields.competences !== undefined) setters.setCompetences(fields.competences);
    if (fields.pointOfContact !== undefined) {
      setters.setPointOfContact(fields.pointOfContact);
      const poc = fields.pointOfContact;
      if (
        String(poc?.name || "").trim() ||
        String(poc?.role || "").trim() ||
        String(poc?.contact_details || "").trim() ||
        String(poc?.notes || "").trim() ||
        String(poc?.company || "").trim()
      ) {
        setters.setShowPointOfContact(true);
      }
    }
    restored = true;
  }

  const metadata = sessionState.metadata?.common || sessionState.metadata || {};
  if (sessionState.metadata?.common && setters.setExtractedData) {
    setters.setExtractedData(sessionState.metadata.common);
    restored = true;
  } else if (metadata && Object.keys(metadata).length > 0 && setters.setExtractedData) {
    setters.setExtractedData(metadata);
    restored = true;
  }

  const vendors = sessionState.vendors;
  const shelfEntries = extractVendorShelfEntries(vendors);
  const vendorStageHint = inferVendorStageFromVendors(vendors);
  const lettersFromVendors = extractLettersFromVendors(vendors);

  let vendor = null;
  if (shelfEntries.length > 0 || vendorStageHint !== "input" || Object.keys(lettersFromVendors).length > 0) {
    vendor = {
      shelfEntries,
      vendorStage: vendorStageHint === "input" ? "phases" : vendorStageHint,
      assemblyVisible: vendorStageHint === "assembly",
      letters: lettersFromVendors,
    };
    restored = true;
  }

  let agentic = null;
  const rawAgentic = sessionState.agentic;
  if (rawAgentic && typeof rawAgentic === "object" && rawAgentic.status) {
    const normalized = normalizeAgenticThreads(rawAgentic.threads || {}, rawAgentic.topic_meta || {});
    agentic = {
      state: {
        ...rawAgentic,
        threads: normalized.threads,
        topic_meta: normalized.topicMeta,
      },
      stage: rawAgentic.status === "done" ? "assembly" : "agentic",
      maxRounds: rawAgentic.max_rounds ?? null,
      subCommentRounds: rawAgentic.sub_comment_rounds ?? null,
    };
    restored = true;
  }

  return { restored, vendor, agentic };
}
