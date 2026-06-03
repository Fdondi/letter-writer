import React from "react";
import { render, screen } from "@testing-library/react";
import AutocompleteFlow from "../AutocompleteFlow";
import { getScaleConfig } from "../../utils/competenceScales";

describe("AutocompleteFlow", () => {
  beforeEach(() => {
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({}),
      })
    );
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("renders editor without hook errors", () => {
    render(
      <AutocompleteFlow
        jobText="Sample job offer text"
        additionalUserInfo=""
        additionalCompanyInfo=""
        structureInstructions=""
        companyReport="Company research notes"
        requirements={["Python"]}
        competences={{ Python: { need: "expected", level: "Professional" } }}
        competenceScaleConfig={getScaleConfig()}
      />
    );
    expect(screen.getAllByPlaceholderText(/Paragraph text/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByDisplayValue(/You are great/i)).toBeInTheDocument();
    expect(screen.getByText(/Autocomplete letter/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Job offer/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Plan context/i })).toBeInTheDocument();
    expect(screen.getByText(/Key Competences/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save & Copy/i })).toBeInTheDocument();
  });

  it("disables Save & Copy when letter body is empty", () => {
    render(
      <AutocompleteFlow
        jobText="Sample job"
        onSaveAndCopy={jest.fn()}
      />
    );
    expect(screen.getByRole("button", { name: /Save & Copy/i })).toBeDisabled();
  });
});
