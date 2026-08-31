import { applyExtractionPayload } from "../applyExtractionPayload";

function makeSetters() {
  return {
    setPhaseSessionId: jest.fn(),
    setJobText: jest.fn(),
    setCompanyName: jest.fn(),
    setJobTitle: jest.fn(),
    setLocation: jest.fn(),
    setLanguage: jest.fn(),
    setSalary: jest.fn(),
    setPointOfContact: jest.fn(),
    setShowPointOfContact: jest.fn(),
    setTriggerPocResearch: jest.fn(),
    setCompetences: jest.fn(),
    setCompetenceOverrides: jest.fn(),
    setRequirements: jest.fn(),
    setHireProblem: jest.fn(),
    setExtractedData: jest.fn(),
    setCompanyExtractionResult: jest.fn(),
    setCompanyResearchCountdown: jest.fn(),
    setAllSearchResults: jest.fn(),
    setSelectedTopDocs: jest.fn(),
    setSelectedDocIds: jest.fn(),
  };
}

describe("applyExtractionPayload", () => {
  it("fills cleaned job text and company fields on capture overwrite", () => {
    const setters = makeSetters();
    const result = applyExtractionPayload(
      {
        session_id: "sess-cap",
        job_text: "Cleaned posting about Zürich",
        extraction: {
          company_name: "Acme",
          job_title: "Engineerin",
          location: "Zürich",
          language: "German",
          hire_problem: "Scale payments",
          competences: {
            Python: { need: "critical", level: "Professional" },
          },
          requirements: ["Python"],
        },
        similar_documents: [{ company_name: "Other Co" }],
        top_docs: [{ id: "doc-1", company_name: "Other Co" }],
      },
      setters,
      { applyJobText: true, overwriteCompany: true, applySessionId: true }
    );

    expect(result.applied).toBe(true);
    expect(setters.setPhaseSessionId).toHaveBeenCalledWith("sess-cap");
    expect(setters.setJobText).toHaveBeenCalledWith("Cleaned posting about Zürich");
    expect(setters.setCompanyName).toHaveBeenCalledWith("Acme");
    expect(setters.setJobTitle).toHaveBeenCalledWith("Engineerin");
    expect(setters.setHireProblem).toHaveBeenCalledWith("Scale payments");
    expect(setters.setCompetences).toHaveBeenCalled();
    expect(setters.setAllSearchResults).toHaveBeenCalled();
    expect(setters.setSelectedTopDocs).toHaveBeenCalled();
    expect(setters.setCompanyResearchCountdown).toHaveBeenCalledWith(15);
  });

  it("does not replace job text for a normal extract response", () => {
    const setters = makeSetters();
    applyExtractionPayload(
      {
        extraction: {
          hire_problem: "Grow EU",
          competences: { git: { need: "expected", level: "Amateur" } },
        },
      },
      setters,
      { applyJobText: false, overwriteCompany: false, currentJobText: "pasted ad" }
    );
    expect(setters.setJobText).not.toHaveBeenCalled();
    expect(setters.setPhaseSessionId).not.toHaveBeenCalled();
    expect(setters.setHireProblem).toHaveBeenCalledWith("Grow EU");
  });
});
