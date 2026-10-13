import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import FlowModelPopover from "../FlowModelPopover";

jest.mock("../flowModelStore", () => ({
  ensureFlowModelsLoaded: jest.fn(),
  getFlowModelState: () => ({
    flows: [{ id: "initial", title: "Extract", role_defaults: {} }],
    error: null,
    vendorRoleModels: {},
    grouped: {},
    extractionVendor: "openai",
    saving: false,
  }),
  subscribeFlowModels: () => () => {},
  updateExtractionVendor: jest.fn(),
  updateFlowRole: jest.fn(),
}));

jest.mock("../VendorFlowModelSettings", () => function MockSettings() {
  return <button type="button">Pick model</button>;
});

describe("FlowModelPopover", () => {
  test("opens the menu on the document so a covering sibling cannot take the click", () => {
    render(
      <div style={{ overflow: "hidden" }}>
        <FlowModelPopover flowId="initial" ariaLabel="Extraction models" testId="flow-model-extract" />
        <div style={{ position: "relative", zIndex: 5, height: 400 }}>Company details</div>
      </div>
    );

    fireEvent.click(screen.getByTestId("flow-model-extract"));

    const dialog = screen.getByRole("dialog", { name: "Extraction models" });
    expect(dialog.parentElement).toBe(document.body);
    expect(dialog).toHaveStyle({ position: "fixed", zIndex: 80 });

    fireEvent.mouseDown(screen.getByRole("button", { name: "Pick model" }));
    expect(screen.getByRole("dialog", { name: "Extraction models" })).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByText("Company details"));
    expect(screen.queryByRole("dialog", { name: "Extraction models" })).not.toBeInTheDocument();
  });
});
