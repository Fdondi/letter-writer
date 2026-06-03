import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import ModelPickSelector from "../ModelPickSelector";

const grouped = {
  openai: [
    {
      id: "gpt-5.5",
      name: "Gpt 5.5",
      composite: "openai/gpt-5.5",
      reasoningEfforts: ["none", "low", "high"],
    },
  ],
};

describe("ModelPickSelector", () => {
  test("renders vendor, model, and reasoning selects", () => {
    const onChange = jest.fn();
    render(
      <ModelPickSelector
        value="openai/gpt-5.5@high"
        grouped={grouped}
        onChange={onChange}
      />
    );
    expect(screen.getByLabelText("Vendor")).toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toBeInTheDocument();
    expect(screen.getByLabelText("Reasoning effort")).toBeInTheDocument();
  });

  test("calls onChange with composite when reasoning changes", () => {
    const onChange = jest.fn();
    render(
      <ModelPickSelector
        value="openai/gpt-5.5"
        grouped={grouped}
        onChange={onChange}
      />
    );
    fireEvent.change(screen.getByLabelText("Reasoning effort"), { target: { value: "high" } });
    expect(onChange).toHaveBeenCalledWith(
      "openai",
      "gpt-5.5",
      "high",
      "openai/gpt-5.5@high"
    );
  });
});
