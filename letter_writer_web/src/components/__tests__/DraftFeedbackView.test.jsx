import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
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

  test("invalid comments sit under already-good notes and can be restored", () => {
    const onSave = jest.fn();
    renderView({ onSave });
    expect(screen.queryByTestId("note-marker-hall1")).not.toBeInTheDocument();
    expect(screen.getByText("Laya marked invalid (1) — not treated as critiques")).toBeInTheDocument();
    expect(screen.getByText("Claims a degree the letter never mentions.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(onSave).toHaveBeenCalledWith(
      "precision",
      expect.arrayContaining([
        expect.objectContaining({ id: "hall1", laya_restored: true }),
      ]),
    );
  });
});
