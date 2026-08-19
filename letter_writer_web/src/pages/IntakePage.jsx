import React, { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import VendorSelector from "../components/VendorSelector";
import LanguageConfig from "../components/LanguageConfig";
import LanguageSelector from "../components/LanguageSelector";
import ResearchComponent from "../components/ResearchComponent";
import SimilarOffersCarousel from "../components/SimilarOffersCarousel";
import CompetencesList from "../components/CompetencesList";
import AutocompletePlanModelSelect from "../components/AutocompletePlanModelSelect";
import { useJobSession } from "../contexts/JobSessionContext";
import { useLanguages } from "../contexts/LanguageContext";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { buildCompetenceRatingsForProfile, getEffectiveRating, getEffectiveImportance } from "../utils/competenceScales";

export default function IntakePage() {
  const navigate = useNavigate();
  const session = useJobSession();
  const { enabledLanguages } = useLanguages();

  const [agenticMaxRounds, setAgenticMaxRounds] = useState(3);
  const [agenticSubCommentRounds, setAgenticSubCommentRounds] = useState(0);

  const vendorsList = Array.from(session.selectedVendors);

  const handleStartAutocomplete = async () => {
    if (!session.jobTitle.trim()) {
      session.setError("Job title is required");
      return;
    }
    if (!session.jobText?.trim()) {
      session.setError("Job description is required");
      return;
    }
    session.setError(null);
    try {
      await session.ensurePhaseSessionReady();
      navigate("/flows/autocomplete");
    } catch (e) {
      console.error("Failed to prepare autocomplete session:", e);
      session.setError("Failed to sync job details to session. Fix the issue or try again.");
    }
  };

  const saveCompetenceRatings = async () => {
    const ratingsToSave = buildCompetenceRatingsForProfile(
      session.competences,
      session.requirements,
      session.competenceOverrides,
      session.competenceScaleConfig
    );
    if (Object.keys(ratingsToSave).length > 0) {
      fetchWithHeartbeat("/api/personal-data/", {
        method: "POST",
        body: JSON.stringify({ competence_ratings: ratingsToSave }),
      }).catch((e) => console.warn("Failed to save competence ratings to profile:", e));
    }
  };

  const handleSubmit = async () => {
    if (!session.jobTitle.trim()) {
      session.setError("Job title is required");
      return;
    }
    session.setLoading(true);
    session.setError(null);
    session.setDocumentId(null);

    try {
      await session.ensurePhaseSessionReady();
    } catch (e) {
      console.error("Failed to update session data:", e);
      session.setError("Failed to update session data. Please try again.");
      session.setLoading(false);
      return;
    }

    await saveCompetenceRatings();
    session.setLoading(false);
    navigate("/flows/vendors", { state: { start: true } });
  };

  const handleSubmitAgentic = async () => {
    if (!session.jobTitle.trim()) {
      session.setError("Job title is required");
      return;
    }

    try {
      await session.ensurePhaseSessionReady();
    } catch (e) {
      console.error("Failed to update session:", e);
      session.setError("Failed to update session. Please try again.");
      return;
    }

    await saveCompetenceRatings();
    navigate("/flows/agentic", {
      state: {
        start: true,
        maxRounds: agenticMaxRounds,
        subCommentRounds: agenticSubCommentRounds,
      },
    });
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <VendorSelector
          vendors={session.vendors}
          selected={session.selectedVendors}
          onToggle={session.toggleVendor}
          onSelectAll={session.selectAll}
        />
        <LanguageConfig />
      </div>
      <div style={{ marginTop: 10 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <label style={{ fontSize: "14px", fontWeight: 600, color: "var(--text-color)" }}>
            Job Description
          </label>
          <LanguageSelector
            languages={enabledLanguages}
            viewLanguage={session.jobTextViewLanguage}
            onLanguageChange={session.handleJobTextLanguageChange}
            hasTranslation={(code) => Boolean(session.jobTextTranslations[code])}
            disabled={false}
            isTranslating={session.isTranslatingJobText}
            size="small"
          />
        </div>
        {session.jobTextTranslationError && (
          <div style={{ color: "var(--error-text)", fontSize: "12px", marginBottom: 6 }}>
            {session.jobTextTranslationError}
          </div>
        )}
        <textarea
          style={{
            width: "100%",
            height: 150,
            backgroundColor: session.jobTextViewLanguage === "source" ? "var(--input-bg)" : "var(--panel-bg)",
            color: "var(--text-color)",
            border: "1px solid var(--border-color)",
            borderRadius: "4px",
            padding: 8,
            opacity: session.jobTextViewLanguage === "source" ? 1 : 0.9,
          }}
          placeholder="Paste job description here"
          value={session.displayedJobText}
          onChange={(e) => {
            if (session.jobTextViewLanguage === "source") {
              session.setJobText(e.target.value);
            }
          }}
          readOnly={session.jobTextViewLanguage !== "source"}
        />
      </div>

      {/* Additional Information - collapsible section */}
      <div style={{ marginTop: 15, textAlign: "center" }}>
        <button
          onClick={() => session.setShowAdditionalInfo(!session.showAdditionalInfo)}
          style={{
            padding: "6px 16px",
            fontSize: "13px",
            backgroundColor: "transparent",
            color: "var(--text-color)",
            border: "1px dashed var(--border-color)",
            borderRadius: "4px",
            cursor: "pointer",
            opacity: 0.8,
          }}
        >
          {session.showAdditionalInfo ? "− Hide additional information" : "+ Anything extra the AI should consider for this?"}
        </button>
        {session.showAdditionalInfo && (
          <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 15 }}>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600, color: "var(--text-color)" }}>
                About You (not in CV)
              </label>
              <textarea
                style={{
                  width: "100%",
                  height: 80,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  padding: 8,
                  fontSize: "14px",
                }}
                placeholder={`Info about you relevant to this position that isn't in your CV, e.g.,\n'this certification/project that is rarely relevant might make the difference here',\n'I am a power user of this service they provide', 'my commute would be easy', ...`}
                value={session.additionalUserInfo}
                onChange={(e) => session.setAdditionalUserInfo(e.target.value)}
              />
              <p style={{ marginTop: 4, fontSize: "11px", color: "var(--text-color)", opacity: 0.7 }}>
                Passed to the letter writer and CV accuracy check.
              </p>
            </div>
            <div>
              <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600, color: "var(--text-color)" }}>
                About the Company
              </label>
              <textarea
                style={{
                  width: "100%",
                  height: 80,
                  backgroundColor: "var(--input-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                  padding: 8,
                  fontSize: "14px",
                }}
                placeholder={`Extra info about the company or role, e.g.,\n'I have insider information on what they are like and care about / what they really need for this position',\n'I want to highlight this aspect of their culture or needs on why they might want to hire me', ...`}
                value={session.additionalCompanyInfo}
                onChange={(e) => session.setAdditionalCompanyInfo(e.target.value)}
              />
              <p style={{ marginTop: 4, fontSize: "11px", color: "var(--text-color)", opacity: 0.7 }}>
                Passed to company background research.
              </p>
            </div>
          </div>
        )}
      </div>
      
      <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
        <button
          onClick={session.extractData}
          disabled={session.extracting || !session.jobText.trim()}
          style={{
            padding: "10px 20px",
            backgroundColor: session.extracting || !session.jobText.trim() ? "var(--header-bg)" : "#10b981",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: session.extracting || !session.jobText.trim() ? "not-allowed" : "pointer",
          }}
        >
          {session.extracting ? "Extracting..." : "Extract data"}
        </button>
        {session.extractionError && (
          <div style={{ color: "var(--error-text)", padding: "10px 0", fontSize: "14px" }}>
            {session.extractionError}
          </div>
        )}
      </div>

      <div style={{ marginTop: 20, padding: 15, border: "1px solid var(--border-color)", borderRadius: 8, backgroundColor: "var(--input-bg)" }}>
         <h3 style={{ marginTop: 0, fontSize: "16px", fontWeight: 600 }}>Company & Job Details</h3>
         <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div>
                    <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Job Title *</label>
                    <input type="text" value={session.jobTitle} onChange={(e) => session.setJobTitle(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Job title" />
                </div>
                <div>
                    <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Company Name</label>
                    <input type="text" value={session.companyName} onChange={(e) => session.setCompanyName(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Company name" />
                </div>
                <div>
                    <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Location</label>
                    <input type="text" value={session.location} onChange={(e) => session.setLocation(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Location" />
                </div>
                <div>
                    <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Language</label>
                    <input type="text" value={session.language} onChange={(e) => session.setLanguage(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Language" />
                </div>
                <div>
                    <label style={{ display: "block", marginBottom: 4, fontSize: "14px", fontWeight: 600 }}>Salary</label>
                    <input type="text" value={session.salary} onChange={(e) => session.setSalary(e.target.value)} style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }} placeholder="Salary range" />
                </div>
            </div>
            <div>
                {session.companyResearchCountdown !== null && session.companyResearchCountdown > 0 && (
                  <div style={{
                    padding: "8px 12px",
                    marginBottom: 8,
                    borderRadius: 4,
                    border: "1px solid #5b9bd5",
                    backgroundColor: "rgba(91, 155, 213, 0.1)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    fontSize: 13,
                  }}>
                    <span>
                      Extracted: <strong>{session.companyExtractionResult?.company_name || session.companyName || "—"}</strong>
                      {session.companyExtractionResult?.job_title ? ` — ${session.companyExtractionResult.job_title}` : ""}
                      {session.companyExtractionResult?.location ? ` (${session.companyExtractionResult.location})` : ""}
                      {". "}Background research in <strong>{session.companyResearchCountdown}s</strong>…
                    </span>
                    <button
                      onClick={() => {
                        session.setCompanyResearchCountdown(null);
                        session.setCompanyAutoResearchBlocked(true);
                        session.setCompanyResearchNotification("Auto-research paused. Edit details above, then click \"Start Research\" below.");
                      }}
                      style={{
                        padding: "3px 10px",
                        fontSize: 12,
                        border: "1px solid var(--border-color)",
                        borderRadius: 4,
                        backgroundColor: "var(--bg-color)",
                        color: "var(--text-color)",
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                        marginLeft: 12,
                      }}
                    >
                      Edit first
                    </button>
                  </div>
                )}
                {session.companyAutoResearchBlocked && session.companyResearchNotification && (
                  <div style={{
                    padding: "6px 12px",
                    marginBottom: 8,
                    borderRadius: 4,
                    border: "1px solid #d4a843",
                    backgroundColor: "rgba(212, 168, 67, 0.1)",
                    fontSize: 12,
                    color: "var(--text-color)",
                  }}>
                    {session.companyResearchNotification}
                  </div>
                )}
                {!session.companyAutoResearchBlocked && session.companyResearchNotification && session.companyResearchCountdown === null && (
                  <div style={{
                    padding: "6px 12px",
                    marginBottom: 8,
                    borderRadius: 4,
                    border: `1px solid ${session.companyResearchNotification.includes("cached") || session.companyResearchNotification.includes("similar") ? "#5a9e6f" : "#5b9bd5"}`,
                    backgroundColor: session.companyResearchNotification.includes("cached") || session.companyResearchNotification.includes("similar") ? "rgba(90, 158, 111, 0.1)" : "rgba(91, 155, 213, 0.1)",
                    fontSize: 12,
                    color: "var(--text-color)",
                  }}>
                    {session.companyResearchNotification}
                  </div>
                )}
                <ResearchComponent 
                    label="Company Research"
                    type="company"
                    query={session.companyName}
                    context={{ job_text: session.jobText, additional_company_info: session.additionalCompanyInfo }}
                    vendors={session.backgroundModels}
                    onResultSelected={(report, topDocs, source, resolvedName) => {
                        session.setSelectedCompanyReport(report);
                        session.setSelectedTopDocs(topDocs);
                        if (topDocs && topDocs.length > 0) {
                          const llmIds = new Set(topDocs.map(d => d.id || d.company_name).filter(Boolean));
                          session.setSelectedDocIds(llmIds);
                        }
                        if (source === "cache") {
                          session.setCompanyResearchNotification(`Found cached research for "${resolvedName || session.companyName}".`);
                        } else if (source === "similar") {
                          session.setCompanyResearchNotification(`Found similar company "${resolvedName}", using existing research.`);
                        } else {
                          session.setCompanyResearchNotification(`New research completed for "${session.companyName}".`);
                        }
                        session.setCompanyAutoResearchBlocked(false);
                    }}
                    externalTrigger={session.triggerCompanyResearch}
                />
            </div>
         </div>
      </div>

      <div style={{ marginTop: 20, padding: 15, border: "1px solid var(--border-color)", borderRadius: 8, backgroundColor: "var(--input-bg)" }}>
         <button
           onClick={() => session.setShowPointOfContact(!session.showPointOfContact)}
           style={{
             width: "100%",
             display: "flex",
             justifyContent: "space-between",
             alignItems: "center",
             marginTop: 0,
             marginBottom: 0,
             padding: 0,
             fontSize: "16px",
             fontWeight: 600,
             color: "var(--text-color)",
             background: "transparent",
             border: "none",
             cursor: "pointer",
             textAlign: "left",
           }}
           aria-expanded={session.showPointOfContact}
           aria-label={session.showPointOfContact ? "Collapse point of contact" : "Expand point of contact"}
         >
           <span>Point of Contact</span>
           <span style={{ fontSize: 12, opacity: 0.8 }}>{session.showPointOfContact ? "▲" : "▼"}</span>
         </button>
         {!session.hasPointOfContactData && (
           <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--secondary-text-color)" }}>
             Empty - collapsed by default.
           </p>
         )}
         {session.showPointOfContact && (
         <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 10 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div>
                <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Name</label>
                <input type="text" value={session.pointOfContact.name} onChange={(e) => session.setPointOfContact({ ...session.pointOfContact, name: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Contact name" />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Role</label>
                <input type="text" value={session.pointOfContact.role} onChange={(e) => session.setPointOfContact({ ...session.pointOfContact, role: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Role in company" />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Contact Details</label>
                <input type="text" value={session.pointOfContact.contact_details} onChange={(e) => session.setPointOfContact({ ...session.pointOfContact, contact_details: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Email, phone, etc." />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Company (if intermediary)</label>
                <input type="text" value={session.pointOfContact.company} onChange={(e) => session.setPointOfContact({ ...session.pointOfContact, company: e.target.value })} style={{ width: "100%", padding: 6, fontSize: 13, backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Intermediary company" />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 2, fontSize: "12px", fontWeight: 600 }}>Notes</label>
                <textarea value={session.pointOfContact.notes} onChange={(e) => session.setPointOfContact({ ...session.pointOfContact, notes: e.target.value })} style={{ width: "100%", height: 48, padding: 6, fontSize: 13, resize: "vertical", backgroundColor: "var(--bg-color)", color: "var(--text-color)", border: "1px solid var(--border-color)", borderRadius: 4 }} placeholder="Notes about contact" />
              </div>
            </div>
            <div>
                <ResearchComponent 
                    label="POC Research"
                    type="poc"
                    query={session.pointOfContact.name}
                    context={{ job_text: session.jobText, company_name: session.companyName }}
                    vendors={session.backgroundModels}
                    onResultSelected={(report) => {
                        session.setSelectedPocReport(report);
                    }}
                    externalTrigger={session.triggerPocResearch}
                />
            </div>
         </div>
         )}
      </div>

      {/* Two-column layout: Similar offers (left) | Competences (right) */}
      <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gridTemplateRows: "minmax(0, 1fr)", gap: 16, height: "min(80vh, 600px)" }}>
        <div style={{ display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
          <div style={{ marginBottom: 4, flexShrink: 0 }}>
            <label style={{ display: "block", fontSize: "14px", fontWeight: 600 }}>
              Similar Previous Offers
            </label>
            <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginTop: 2 }}>
              RAG-retrieved offers. LLM picks are highlighted. Toggle to include/exclude from draft.
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <SimilarOffersCarousel
              allSearchResults={session.allSearchResults}
              topDocs={session.selectedTopDocs || []}
              selectedDocIds={session.selectedDocIds}
              onSelectionChange={session.setSelectedDocIds}
            />
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" }}>
          <div style={{ marginBottom: 4, flexShrink: 0 }}>
            <label style={{ display: "block", fontSize: "14px", fontWeight: 600 }}>
              How good is your fit? Key competences weighted match:
              {(() => {
              const keys = Object.keys(session.competences);
              if (keys.length === 0) return null;
              let totalWeighted = 0;
              let totalWeight = 0;
              keys.forEach(key => {
                const num = getEffectiveRating(key, session.competences, session.competenceScaleConfig, session.competenceOverrides);
                const imp = getEffectiveImportance(key, session.competences, session.competenceScaleConfig, session.competenceOverrides);
                if (num.presence != null && imp != null) {
                  totalWeighted += num.presence * imp;
                  totalWeight += imp;
                }
              });
              if (totalWeight === 0) return null;
              const avgPresence = totalWeighted / totalWeight;
              const avgStars = Math.round(avgPresence);
              return (
                <span style={{ fontWeight: 500, color: "var(--secondary-text-color)", marginLeft: 6 }}>
                  <span style={{ fontSize: 11 }}>{"★".repeat(avgStars)}{"☆".repeat(5 - avgStars)}</span> ({avgPresence.toFixed(1)})
                </span>
              );
            })()}
            </label>
            <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginTop: 2 }}>
              CV fit levels can be adjusted. They will be remembered.
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: "block", fontSize: "12px", fontWeight: 600, marginBottom: 4 }}>
                What problem is this hire meant to solve?
              </label>
              <div style={{ fontSize: 11, color: "var(--secondary-text-color)", marginBottom: 6 }}>
                Extracted in the same pass as key competences; edit if the model missed nuance.
              </div>
              <textarea
                value={session.hireProblem}
                onChange={(e) => session.setHireProblem(e.target.value)}
                placeholder="e.g. scale the data platform, lead a regulatory migration, own the first sales motion in a new region…"
                rows={4}
                style={{
                  width: "100%",
                  boxSizing: "border-box",
                  padding: 8,
                  fontSize: 13,
                  resize: "vertical",
                  backgroundColor: "var(--bg-color)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                  fontFamily: "inherit",
                }}
              />
            </div>
            <CompetencesList
              requirements={session.requirements}
              competences={session.competences}
              scaleConfig={session.competenceScaleConfig}
              overrides={session.competenceOverrides}
              onOverridesChange={session.setCompetenceOverrides}
              editable
              onRequirementsChange={session.setRequirements}
              onCompetencesChange={session.setCompetences}
            />
          </div>
        </div>
      </div>
      {session.error && <p style={{ color: "var(--error-text)" }}>{session.error}</p>}
      {session.documentSaveNotice && (
        <p
          role="status"
          style={{
            color: "var(--secondary-text-color)",
            background: "var(--warning-bg)",
            border: "1px solid var(--warning-border)",
            padding: "10px 12px",
            borderRadius: 4,
          }}
        >
          {session.documentSaveNotice}
        </p>
      )}

      <div style={{ marginTop: 20, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <button
          type="button"
          onClick={handleStartAutocomplete}
          disabled={!session.jobText || !session.jobTitle.trim()}
          style={{
            padding: "10px 20px",
            backgroundColor: !session.jobText || !session.jobTitle.trim() ? "var(--header-bg)" : "#0d9488",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: !session.jobText || !session.jobTitle.trim() ? "not-allowed" : "pointer",
          }}
        >
          Start autocomplete
        </button>
        <AutocompletePlanModelSelect />
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--text-color)" }}>
          <input
            type="checkbox"
            checked={session.includePlanStep}
            onChange={(e) => session.setIncludePlanStep(e.target.checked)}
          />
          Include plan step
        </label>
        <button
          onClick={handleSubmit}
          disabled={session.loading || !session.jobText || !session.jobTitle.trim() || session.selectedVendors.size === 0}
          style={{
            padding: "10px 20px",
            backgroundColor: session.loading || !session.jobText || !session.jobTitle.trim() || session.selectedVendors.size === 0 ? "var(--header-bg)" : "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: session.loading || !session.jobText || !session.jobTitle.trim() || session.selectedVendors.size === 0 ? "not-allowed" : "pointer",
          }}
        >
          {session.loading ? "Starting..." : "Start vendor flow"}
        </button>
        <div
          style={{
            width: 1,
            minHeight: 24,
            backgroundColor: "var(--border-color)",
            margin: "0 4px",
          }}
          aria-hidden="true"
        />
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <button
            onClick={handleSubmitAgentic}
            disabled={!session.jobText || !session.jobTitle.trim() || session.selectedVendors.size === 0}
            style={{
              padding: "10px 20px",
              backgroundColor: !session.jobText || !session.jobTitle.trim() || session.selectedVendors.size === 0 ? "var(--header-bg)" : "#7c3aed",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: !session.jobText || !session.jobTitle.trim() || session.selectedVendors.size === 0 ? "not-allowed" : "pointer",
            }}
          >
            Start agentic flow
          </button>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, color: "var(--text-color)" }}>Max rounds:</span>
            <input
              type="number"
              min={1}
              max={15}
              value={agenticMaxRounds}
              onChange={(e) => setAgenticMaxRounds(Math.max(1, Math.min(15, parseInt(e.target.value, 10) || 3)))}
              style={{ width: 48, padding: "6px 8px", borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }}
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }} title="Per main round: add-subcomment phases then vote/prune, after top-level comments (0 = skip sub-comments).">
            <span style={{ fontSize: 13, color: "var(--text-color)" }}>Sub-comment rounds:</span>
            <input
              type="number"
              min={0}
              max={8}
              value={agenticSubCommentRounds}
              onChange={(e) => setAgenticSubCommentRounds(Math.max(0, Math.min(8, parseInt(e.target.value, 10) || 0)))}
              style={{ width: 48, padding: "6px 8px", borderRadius: 4, border: "1px solid var(--border-color)", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }}
            />
          </label>
        </div>
      </div>
    </>
  );
}
