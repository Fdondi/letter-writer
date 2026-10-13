import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { DraftFeedbackView } from "../phases/DraftFeedbackView";

const letter = "Hello world from Zürich.";

function renderView(extra = {}) {
  const onSave = extra.onSave || (() => {});
  return render(
    <DraftFeedbackView
      cardPhaseEdits={{ draft_letter: letter }}
      cardPhaseData={{ draft_letter: letter }}
      handleEditChange={() => {}}
      isLoading={false}
      approved={false}
      vendor="openai"
      feedback={{
        precision: [
          {
            id: "fix1",
            observation: "World is too casual.",
            type: "PLEASE_FIX",
            quote: "world",
            matched_text: "world",
          },
          {
            id: "hall1",
            observation: "Claims a degree the letter never mentions.",
            type: "PLEASE_FIX",
            quote: "Hello",
            matched_text: "Hello",
            laya_verdict: "invalid",
            laya_valid_probability: 0.08,
          },
        ],
        human: [
          {
            id: "good1",
            observation: "Sounds like a person.",
            type: "ALREADY_GOOD",
            quote: "Zürich",
            matched_text: "Zürich",
          },
        ],
        accuracy: [
          {
            id: "whole1",
            observation: "The letter as a whole stays short enough.",
            type: "PLEASE_FIX",
            quote: "",
            matched_text: "",
          },
          {
            id: "wholeGood",
            observation: "Optional whole-letter praise.",
            type: "ALREADY_GOOD",
            quote: "",
            matched_text: "",
          },
          {
            id: "wholeLaya",
            observation: "Invented a salary the letter never states.",
            type: "PLEASE_FIX",
            quote: "",
            matched_text: "",
            laya_verdict: "invalid",
            laya_valid_probability: 0.12,
          },
        ],
      }}
      feedbackKeys={["precision", "human", "accuracy"]}
      feedbackOverrides={{}}
      activeFeedbackKey="precision"
      feedbackItemApprovals={{}}
      setFeedbackItemApprovals={() => {}}
      setSelectedFeedbackTab={() => {}}
      handleSaveFeedbackOverride={onSave}
      translation={null}
      inputClusterText={{}}
      broadcastInputCluster={() => {}}
    />,
  );
}

describe("DraftFeedbackView notes chrome", () => {
  test("adds via + next to each category, not a pile of Add critique buttons", () => {
    renderView();
    const addPrecision = screen.getByRole("button", { name: "Add critique · Precision" });
    const addHuman = screen.getByRole("button", { name: "Add critique · Human" });
    const addAccuracy = screen.getByRole("button", { name: "Add critique · CV accuracy" });
    expect(addPrecision).toHaveTextContent("+");
    expect(addHuman).toHaveTextContent("+");
    expect(addAccuracy).toHaveTextContent("+");
    expect(screen.queryByText("Add critique · precision")).not.toBeInTheDocument();
    expect(screen.queryByText("Add critique · human")).not.toBeInTheDocument();
  });

  test("whole-letter notes use the category list, with already-good collapsed", () => {
    renderView();
    const whole = screen.getByTestId("unanchored-notes");
    expect(whole).toHaveTextContent("The letter as a whole stays short enough.");
    expect(whole).toHaveTextContent("Positive or neutral model notes");
    expect(screen.queryByText("Optional whole-letter praise.")).not.toBeVisible();
    expect(screen.queryByTestId("note-marker-whole1")).not.toBeInTheDocument();
  });

  test("summary counts please-fix and input-needed, not already-good", () => {
    renderView();
    expect(screen.getByTestId("feedback-count-precision")).toHaveTextContent("1");
    expect(screen.getByTestId("feedback-count-human")).toHaveTextContent("0");
    expect(screen.getByTestId("feedback-count-accuracy")).toHaveTextContent("1");
  });

  test("passage notes Laya filtered stay on the letter, inactive, and approve directly", () => {
    const onSave = jest.fn();
    renderView({ onSave });
    const marker = screen.getByTestId("note-marker-hall1");
    expect(marker).toHaveAttribute("data-dealt", "true");
    expect(marker).toHaveAttribute("data-inactive-reason", "laya");
    expect(screen.queryByText("Claims a degree the letter never mentions.")).not.toBeInTheDocument();

    fireEvent.click(marker);
    const note = screen.getByTestId("inline-note");
    expect(note).toHaveTextContent(
      "Inactive because Laya scored this comment as ungrounded (8% grounded). The feedback model did not mark it as no action, and you have not approved or dismissed it.",
    );
    expect(note).toHaveTextContent("Claims a degree the letter never mentions.");
    fireEvent.click(within(note).getByRole("button", { name: "Approve" }));
    expect(onSave).toHaveBeenCalledWith(
      "precision",
      expect.arrayContaining([
        expect.objectContaining({ id: "hall1", laya_restored: true }),
      ]),
    );
  });

  test("whole-letter notes Laya filtered start collapsed and can be edited or approved", () => {
    renderView();
    const section = screen.getByTestId("laya-filtered-section");
    expect(section).not.toHaveAttribute("open");
    expect(section).toHaveTextContent("Laya filtered (1)");
    expect(screen.queryByText("Invented a salary the letter never states.")).not.toBeVisible();
    fireEvent.click(screen.getByText("Laya filtered (1)"));
    expect(screen.getByText("Invented a salary the letter never states.")).toBeVisible();
    expect(screen.getByText(/12% grounded/)).toBeVisible();
    const filtered = screen.getByTestId("laya-filtered-section");
    expect(filtered).toHaveTextContent("Approve");
    expect(filtered).toHaveTextContent("Edit");
  });
});
