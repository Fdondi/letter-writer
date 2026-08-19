import React from "react";
import { useNavigate } from "react-router-dom";
import AutocompleteFlow from "../components/AutocompleteFlow";
import { useJobSession } from "../contexts/JobSessionContext";
import { persistLetterDocument } from "../utils/persistLetterDocument";
import { fetchWithHeartbeat } from "../utils/apiHelpers";

export default function AutocompleteFlowPage() {
  const navigate = useNavigate();
  const session = useJobSession();

  const handleSaveAndCopy = async (opts) => {
    const { letterText, sections, proposalLetterText, autocompleteHistory, completionModel, planModel, planCost, cycleModels, totalCost } = opts;
    if (!session.jobText?.trim()) {
      session.setError("Job description is required to save");
      throw new Error("Job description is required to save");
    }
    try {
      session.setSavingFinal(true);
      const result = await persistLetterDocument({
        letterText,
        jobFields: {
          companyName: session.companyName,
          jobTitle: session.jobTitle,
          location: session.location,
          language: session.language,
          salary: session.salary,
          requirements: session.requirements,
          jobText: session.jobText,
        },
        documentId: session.documentId,
        autocompleteData: { sections, proposalLetterText, autocompleteHistory, completionModel, planModel, planCost, cycleModels, totalCost },
      });
      if (result.documentId && !session.documentId) {
        session.setDocumentId(result.documentId);
      }
      try {
        await fetchWithHeartbeat("/api/phases/clear/", { method: "POST" });
        session.setPhaseSessionId(null);
      } catch (clearErr) {
        console.warn("Letter saved but failed to clear server session:", clearErr);
      }
    } catch (e) {
      const errorMsg = `Failed to save letter: ${e.message || e}`;
      session.setError(errorMsg);
      throw new Error(errorMsg);
    } finally {
      session.setSavingFinal(false);
    }
  };

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <button type="button" onClick={() => navigate("/")} style={{ padding: "8px 16px", backgroundColor: "var(--button-bg)", color: "var(--button-text)", border: "1px solid var(--border-color)", borderRadius: "4px", cursor: "pointer" }}>
          ← Back to job details
        </button>
      </div>
      {session.error && <p style={{ color: "var(--error-text)" }}>{session.error}</p>}
      <AutocompleteFlow
        {...session.autocompleteContextProps}
        onSaveAndCopy={handleSaveAndCopy}
        savingFinal={session.savingFinal}
      />
    </>
  );
}
