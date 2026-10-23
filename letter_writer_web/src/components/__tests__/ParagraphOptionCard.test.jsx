import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import ParagraphOptionCard from "../paragraph-flow/ParagraphOptionCard";
import { AllTestProviders } from "../../utils/__tests__/testUtils";

const paragraph = {
  id: "p1",
  text: "I build reliable things for many teams.",
  status: "active",
  feedback: {
    precision: [{ id: "n1", type: "PLEASE_FIX", observation: "Which teams?", quote: "many teams" }],
    human: [{ id: "n2", type: "ALREADY_GOOD", observation: "Natural tone", quote: "reliable things" }],
  },
  feedbackPending: ["accuracy"],
  feedbackErrors: {},
};

function renderCard(props = {}) {
  const handlers = { onUse: jest.fn(), onDiscard: jest.fn(), onRestore: jest.fn(), onRegenerate: jest.fn() };
  render(
    <AllTestProviders>
      <ParagraphOptionCard paragraph={paragraph} vendor="openai" vendors={["openai", "gemini"]} {...handlers} {...props} />
    </AllTestProviders>,
  );
  return handlers;
}

describe("ParagraphOptionCard", () => {
  test("strong and faint notes render without blocking actions", () => {
    renderCard();
    expect(screen.getByTestId("strong-note-count")).toHaveTextContent("1 to consider");
    expect(screen.getByText(/checking 6\/7/)).toBeInTheDocument();
    const active = document.querySelector('mark[data-active="true"]');
    const faint = document.querySelector('mark[data-active="false"]');
    expect(active).toHaveTextContent("many teams");
    expect(faint).toHaveTextContent("reliable things");
    expect(screen.getByTestId("paragraph-use")).not.toBeDisabled();
  });

  test("use and discard call their handlers", () => {
    const h = renderCard();
    fireEvent.click(screen.getByTestId("paragraph-use"));
    fireEvent.click(screen.getByTestId("paragraph-discard"));
    expect(h.onUse).toHaveBeenCalledTimes(1);
    expect(h.onDiscard).toHaveBeenCalledTimes(1);
  });

  test("regenerate sends user feedback and ticked AI notes", () => {
    const h = renderCard();
    fireEvent.click(screen.getByTestId("paragraph-feedback-toggle"));
    fireEvent.change(screen.getByTestId("paragraph-feedback-text"), { target: { value: "Shorter" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByLabelText("Vendor for regeneration"), { target: { value: "gemini" } });
    fireEvent.click(screen.getByTestId("paragraph-regenerate"));
    expect(h.onRegenerate).toHaveBeenCalledWith({
      userFeedback: "Shorter",
      aiNotes: [{ id: "n1", topic: "precision", observation: "Which teams?", quote: "many teams" }],
      vendor: "gemini",
    });
  });

  test("discarded card offers undo", () => {
    const h = renderCard({ paragraph: { ...paragraph, status: "discarded" } });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(h.onRestore).toHaveBeenCalled();
  });
});
