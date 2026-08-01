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

  test("fixedVendor hides vendor select and keeps vendor on change", () => {
    const onChange = jest.fn();
    const deepseekGrouped = {
      deepseek: [
        {
          id: "deepseek-v4-pro",
          name: "Deepseek V4 Pro",
          composite: "deepseek/deepseek-v4-pro",
          reasoningEfforts: [],
        },
      ],
    };
    render(
      <ModelPickSelector
        fixedVendor="deepseek"
        value="deepseek/deepseek-v4-pro"
        grouped={deepseekGrouped}
        onChange={onChange}
        showReasoning={false}
      />
    );
    expect(screen.queryByLabelText("Vendor")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "deepseek-v4-pro" },
    });
    expect(onChange).toHaveBeenCalledWith(
      "deepseek",
      "deepseek-v4-pro",
      "",
      "deepseek/deepseek-v4-pro"
    );
  });

  test("defaultComposite marks default model in option label", () => {
    render(
      <ModelPickSelector
        fixedVendor="openai"
        value="openai/gpt-5.5@high"
        defaultComposite="openai/gpt-5.5@high"
        grouped={grouped}
        onChange={() => {}}
      />
    );
    expect(screen.getByRole("option", { name: "Gpt 5.5 (default)" })).toBeInTheDocument();
  });

  test("shows pricing next to selector when grouped entry has input/output", () => {
    const priced = {
      openai: [
        {
          id: "gpt-5.5",
          name: "Gpt 5.5",
          composite: "openai/gpt-5.5",
          reasoningEfforts: ["none", "high"],
          input: 3,
          output: 15,
        },
      ],
    };
    render(
      <ModelPickSelector
        value="openai/gpt-5.5@high"
        grouped={priced}
        onChange={() => {}}
      />
    );
    expect(screen.getByLabelText("Model pricing")).toHaveTextContent("$3.00 in · $15.00 out / 1M");
  });

  test("shows default price in parentheses with comparison color", () => {
    const priced = {
      openai: [
        {
          id: "gpt-5.5",
          name: "Gpt 5.5",
          composite: "openai/gpt-5.5",
          reasoningEfforts: [],
          input: 5,
          output: 20,
        },
        {
          id: "gpt-5-nano",
          name: "Gpt 5 Nano",
          composite: "openai/gpt-5-nano",
          reasoningEfforts: [],
          input: 1,
          output: 2,
        },
      ],
    };
    render(
      <ModelPickSelector
        fixedVendor="openai"
        value="openai/gpt-5.5"
        defaultComposite="openai/gpt-5-nano"
        grouped={priced}
        onChange={() => {}}
        showReasoning={false}
      />
    );
    const el = screen.getByLabelText("Model pricing");
    expect(el).toHaveTextContent("$5.00 in · $20.00 out / 1M");
    expect(el).toHaveTextContent("($1.00 in · $2.00 out / 1M)");
    expect(el.querySelector("span[style]")).toHaveStyle({ color: "#dc2626" });
  });
});
