import { getScaleConfig, getEffectiveRating, getEffectiveImportance } from "./competenceScales";

function sortCompetenceKeys(comp, cfg, overrides = {}) {
  return Object.keys(comp).sort((a, b) => {
    const numA = getEffectiveRating(a, comp, cfg, overrides);
    const numB = getEffectiveRating(b, comp, cfg, overrides);
    const impA = getEffectiveImportance(a, comp, cfg, overrides);
    const impB = getEffectiveImportance(b, comp, cfg, overrides);
    if (numA.presence == null || impA == null) return 1;
    if (numB.presence == null || impB == null) return -1;
    const scoreA = impA * (numA.presence - 2.5);
    const scoreB = impB * (numB.presence - 2.5);
    const absA = Math.abs(scoreA);
    const absB = Math.abs(scoreB);
    if (Math.abs(absB - absA) < 0.01) return scoreB - scoreA;
    return absB - absA;
  });
}

/**
 * Apply /api/extract/ or /api/job-capture/{id}/process/ payload onto JobSession setters.
 */
export function applyExtractionPayload(payload, setters, options = {}) {
  if (!payload || typeof payload !== "object") return { applied: false };
  const extracted = payload.extraction || {};
  const applyJobText = options.applyJobText === true;
  const overwriteCompany = options.overwriteCompany === true;
  const additionalUserInfo = options.additionalUserInfo || "";
  const additionalCompanyInfo = options.additionalCompanyInfo || "";
  const currentJobText = options.currentJobText || "";

  if (options.applySessionId && payload.session_id && setters.setPhaseSessionId) {
    setters.setPhaseSessionId(payload.session_id);
  }

  if (applyJobText && payload.job_text != null && setters.setJobText) {
    setters.setJobText(String(payload.job_text));
  }

  const fillCompany = (key, setter, value) => {
    if (!setter || value == null || String(value).trim() === "") return;
    if (overwriteCompany) {
      setter(String(value));
      return;
    }
    setter((prev) => (String(prev || "").trim() ? prev : String(value)));
  };

  fillCompany("company_name", setters.setCompanyName, extracted.company_name);
  fillCompany("job_title", setters.setJobTitle, extracted.job_title);
  fillCompany("location", setters.setLocation, extracted.location);
  fillCompany("language", setters.setLanguage, extracted.language);
  fillCompany("salary", setters.setSalary, extracted.salary);

  const capturedAbout = String(extracted.additional_company_info || "").trim();
  if (overwriteCompany && setters.setAdditionalCompanyInfo) {
    setters.setAdditionalCompanyInfo(capturedAbout);
    if (capturedAbout) setters.setShowAdditionalInfo?.(true);
  } else {
    fillCompany("additional_company_info", setters.setAdditionalCompanyInfo, capturedAbout);
    if (capturedAbout) setters.setShowAdditionalInfo?.(true);
  }

  if (setters.setSourceUrl) {
    const sourceUrl = String(payload.source_url || extracted.source_url || "").trim();
    if (sourceUrl) {
      if (overwriteCompany) {
        setters.setSourceUrl(sourceUrl);
      } else {
        setters.setSourceUrl((prev) => (String(prev || "").trim() ? prev : sourceUrl));
      }
    }
  }

  if (extracted.point_of_contact && setters.setPointOfContact) {
    const poc = extracted.point_of_contact;
    const next = {
      name: poc.name || "",
      role: poc.role || "",
      contact_details: poc.contact_details || "",
      notes: poc.notes || "",
      company: poc.company || "",
    };
    if (overwriteCompany) {
      setters.setPointOfContact(next);
      setters.setShowPointOfContact?.(true);
      setters.setTriggerPocResearch?.(Date.now());
    } else {
      setters.setPointOfContact((prev) => {
        const hasManual =
          prev.name || prev.role || prev.contact_details || prev.notes || prev.company;
        if (hasManual) return prev;
        return next;
      });
      setters.setShowPointOfContact?.(true);
      setters.setTriggerPocResearch?.(Date.now());
    }
  }

  const comp = extracted.competences;
  const cfg = getScaleConfig();
  if (comp && typeof comp === "object" && Object.keys(comp).length > 0) {
    setters.setCompetences?.(comp);
    setters.setCompetenceOverrides?.({});
    setters.setRequirements?.(sortCompetenceKeys(comp, cfg, {}));
  } else if (extracted.requirements) {
    const reqs = Array.isArray(extracted.requirements)
      ? extracted.requirements
      : [extracted.requirements];
    setters.setRequirements?.(reqs.filter(Boolean));
    setters.setCompetences?.({});
    setters.setCompetenceOverrides?.({});
  }

  if (extracted.hire_problem != null && String(extracted.hire_problem).trim()) {
    setters.setHireProblem?.(String(extracted.hire_problem).trim());
  }

  const jobTextForExtracted = applyJobText
    ? String(payload.job_text || "")
    : currentJobText;

  const fromExtractAbout = String(extracted.additional_company_info || "").trim();
  const fromOptionsAbout = String(additionalCompanyInfo || "").trim();
  const aboutCompany = overwriteCompany
    ? fromExtractAbout || fromOptionsAbout
    : fromOptionsAbout || fromExtractAbout;

  setters.setExtractedData?.((prev) => ({
    ...(prev || {}),
    requirements: extracted.requirements || prev?.requirements,
    competences: extracted.competences ?? prev?.competences ?? {},
    hire_problem: extracted.hire_problem ?? prev?.hire_problem ?? "",
    job_text: jobTextForExtracted || prev?.job_text,
    additional_user_info: additionalUserInfo,
    additional_company_info: aboutCompany || prev?.additional_company_info || "",
    company_name: extracted.company_name || prev?.company_name || "",
    job_title: extracted.job_title || prev?.job_title || "",
    location: extracted.location || prev?.location || "",
    language: extracted.language || prev?.language || "",
    salary: extracted.salary || prev?.salary || "",
    source_url: payload.source_url || extracted.source_url || prev?.source_url || "",
    point_of_contact: extracted.point_of_contact || prev?.point_of_contact || null,
  }));

  if (overwriteCompany && (extracted.company_name || extracted.job_title)) {
    setters.setCompanyExtractionResult?.({
      company_name: extracted.company_name || "",
      job_title: extracted.job_title || "",
      location: extracted.location || "",
      language: extracted.language || "",
      salary: extracted.salary || "",
      point_of_contact: extracted.point_of_contact || null,
    });
    if (extracted.company_name) {
      setters.setCompanyResearchCountdown?.(15);
    }
  }

  const similarDocs = payload.similar_documents || [];
  const topDocs = payload.top_docs || [];
  if (similarDocs.length > 0) {
    setters.setAllSearchResults?.(similarDocs);
  }
  if (topDocs.length > 0) {
    setters.setSelectedTopDocs?.(topDocs);
    const llmIds = new Set(topDocs.map((d) => d.id || d.company_name).filter(Boolean));
    setters.setSelectedDocIds?.(llmIds);
  }

  return { applied: true };
}
