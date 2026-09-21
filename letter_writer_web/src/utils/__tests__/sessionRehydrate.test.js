import {
  extractFormFieldsFromSessionState,
  extractVendorShelfEntries,
  inferVendorStageFromVendors,
  extractLettersFromVendors,
  vendorHasCompletedFinal,
} from "../sessionRehydrate.js";

describe("sessionRehydrate", () => {
  it("extracts form fields including German umlauts", () => {
    const fields = extractFormFieldsFromSessionState({
      job_text: "Stelle bei Müller",
      metadata: {
        common: {
          company_name: "Müller GmbH",
          job_title: "Entwickler",
          requirements: ["Python", "FastAPI"],
        },
      },
    });
    expect(fields.jobText).toBe("Stelle bei Müller");
    expect(fields.companyName).toBe("Müller GmbH");
    expect(fields.requirements).toEqual(["Python", "FastAPI"]);
  });

  it("extracts original source URL", () => {
    const fields = extractFormFieldsFromSessionState({
      job_text: "Job",
      metadata: {
        common: {
          source_url: "https://jobs.example/role",
        },
      },
    });
    expect(fields.sourceUrl).toBe("https://jobs.example/role");
  });

  it("extracts About You / About Company additional notes", () => {
    const fields = extractFormFieldsFromSessionState({
      job_text: "Job",
      metadata: {
        common: {
          additional_user_info: "Power user of their product",
          additional_company_info: "Insider: they care about reliability",
        },
      },
    });
    expect(fields.additionalUserInfo).toBe("Power user of their product");
    expect(fields.additionalCompanyInfo).toBe("Insider: they care about reliability");
  });

  it("maps vendor artifacts to shelf phases", () => {
    const entries = extractVendorShelfEntries({
      openai: {
        company_report: "report",
        top_docs: [{ id: 1 }],
        letter_plan: "plan",
        draft_letter: "draft",
        final_letter: "final",
      },
    });
    const phases = entries.map((e) => e.phaseName);
    expect(phases).toEqual(["background", "plan", "draft"]);
    expect(inferVendorStageFromVendors({ openai: { final_letter: "x" } })).toBe("assembly");
    expect(inferVendorStageFromVendors({ openai: { draft_letter: "x" } })).toBe("phases");
    expect(inferVendorStageFromVendors({})).toBe("input");
    expect(extractLettersFromVendors({ openai: { final_letter: "F" } })).toEqual({
      openai: "F",
    });
  });

  it("does not treat drafts or draft-copies as assembled finals", () => {
    expect(vendorHasCompletedFinal({ draft_letter: "D", final_letter: "D" })).toBe(false);
    expect(vendorHasCompletedFinal({ draft_letter: "D", final_letter: "F" })).toBe(true);
    expect(extractLettersFromVendors({ openai: { draft_letter: "D" } })).toEqual({});
    expect(
      extractLettersFromVendors({
        openai: { draft_letter: "D" },
        anthropic: { draft_letter: "D", final_letter: "F" },
        gemini: { draft_letter: "same", final_letter: "same" },
      })
    ).toEqual({ anthropic: "F" });
    expect(
      inferVendorStageFromVendors({
        openai: { draft_letter: "D" },
        anthropic: { draft_letter: "D", final_letter: "F" },
      })
    ).toBe("phases");
  });
});
