import { applyRestoredSessionState } from "../applySessionRestore";

describe("applyRestoredSessionState", () => {
  it("returns vendor restore descriptor from session vendors", () => {
    const setters = {
      setPhaseSessionId: jest.fn(),
      setJobText: jest.fn(),
      setCompanyName: jest.fn(),
      setJobTitle: jest.fn(),
      setLocation: jest.fn(),
      setLanguage: jest.fn(),
      setSalary: jest.fn(),
      setAdditionalUserInfo: jest.fn(),
      setAdditionalCompanyInfo: jest.fn(),
      setShowAdditionalInfo: jest.fn(),
      setHireProblem: jest.fn(),
      setRequirements: jest.fn(),
      setCompetences: jest.fn(),
      setPointOfContact: jest.fn(),
      setShowPointOfContact: jest.fn(),
      setExtractedData: jest.fn(),
    };

    const result = applyRestoredSessionState(
      {
        job_text: "Engineer role",
        vendors: {
          openai: {
            draft_letter: "Dear hiring manager",
            final_letter: "Dear hiring manager, refined",
          },
        },
      },
      setters,
      { sessionId: "sess-123" }
    );

    expect(result.restored).toBe(true);
    expect(setters.setPhaseSessionId).toHaveBeenCalledWith("sess-123");
    expect(setters.setJobText).toHaveBeenCalledWith("Engineer role");
    expect(result.vendor).toMatchObject({
      vendorStage: "assembly",
      assemblyVisible: true,
    });
    expect(result.vendor.shelfEntries.length).toBeGreaterThan(0);
    expect(result.vendor.letters.openai).toContain("refined");
  });

  it("returns agentic restore descriptor when agentic status present", () => {
    const setters = {
      setPhaseSessionId: jest.fn(),
      setJobText: jest.fn(),
      setCompanyName: jest.fn(),
      setJobTitle: jest.fn(),
      setLocation: jest.fn(),
      setLanguage: jest.fn(),
      setSalary: jest.fn(),
      setAdditionalUserInfo: jest.fn(),
      setAdditionalCompanyInfo: jest.fn(),
      setShowAdditionalInfo: jest.fn(),
      setHireProblem: jest.fn(),
      setRequirements: jest.fn(),
      setCompetences: jest.fn(),
      setPointOfContact: jest.fn(),
      setShowPointOfContact: jest.fn(),
      setExtractedData: jest.fn(),
    };

    const result = applyRestoredSessionState(
      {
        agentic: {
          status: "feedback",
          threads: { instruction: [] },
          topic_meta: {},
          max_rounds: 3,
        },
      },
      setters
    );

    expect(result.restored).toBe(true);
    expect(result.agentic).toMatchObject({
      stage: "agentic",
      maxRounds: 3,
    });
    expect(result.agentic.state.status).toBe("feedback");
  });
});
