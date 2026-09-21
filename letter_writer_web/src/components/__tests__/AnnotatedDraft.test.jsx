import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import AnnotatedDraft from "../AnnotatedDraft";

const letter = "Hello world from Zürich.";

describe("AnnotatedDraft", () => {
  test("renders a marker, expands on click, and does not list anchored notes below", () => {
    const notes = [
      {
        id: "n1",
        title: "Precision",
        color: "#d97706",
        start: 6,
        end: 11,
        unanchored: false,
        body: "World is too casual.",
      },
      {
        id: "n2",
        title: "Instruction",
        color: "#6366f1",
        unanchored: true,
        body: "Overall greeting is fine.",
      },
    ];
    let expandedId = null;
    const onToggle = (id) => {
      expandedId = id;
    };

    const { rerender } = render(
      <AnnotatedDraft
        text={letter}
        notes={notes}
        expandedId={expandedId}
        onToggle={(id) => {
          onToggle(id);
        }}
        renderExpanded={(note) => <div>{note.body}</div>}
      />,
    );

    expect(screen.getByLabelText("Precision")).toBeInTheDocument();
    expect(screen.getByText("Notes on the letter as a whole")).toBeInTheDocument();
    expect(screen.getByText("Instruction")).toBeInTheDocument();
    expect(screen.queryByText("World is too casual.")).not.toBeInTheDocument();
    expect(screen.getByText("world")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Precision"));
    rerender(
      <AnnotatedDraft
        text={letter}
        notes={notes}
        expandedId="n1"
        onToggle={onToggle}
        renderExpanded={(note) => <div>{note.body}</div>}
      />,
    );
    const letterBox = screen.getByTestId("annotated-letter");
    expect(screen.getByTestId("inline-note")).toBeInTheDocument();
    expect(screen.getByTestId("note-anchor")).toBeInTheDocument();
    const floating = screen.getByTestId("inline-note");
    expect(floating.style.overflow).toBe("hidden");
    expect(Number.parseFloat(floating.style.maxHeight)).toBeGreaterThan(0);
    expect(letterBox).toContainElement(screen.getByTestId("note-anchor"));
    expect(screen.getByText("World is too casual.")).toBeInTheDocument();
    expect(screen.getByLabelText("Close Precision")).toBeInTheDocument();
    expect(screen.queryByText("Please fix · Precision")).not.toBeInTheDocument();
    expect(screen.getByTestId("unanchored-notes")).not.toContainElement(
      screen.queryByText("World is too casual."),
    );
    const marker = screen.getByTestId("note-marker-n1");
    expect(marker.style.border).toMatch(/1px solid/);
    expect(marker.style.border).not.toMatch(/2px/);
  });

  test("positive and approved notes use a faint marker fill of the topic color", () => {
    render(
      <AnnotatedDraft
        text={letter}
        notes={[
          {
            id: "g1",
            title: "Already good · Human",
            color: "#db2777",
            faint: true,
            start: 6,
            end: 11,
            unanchored: false,
            body: "World is fine.",
          },
        ]}
        expandedId={null}
        onToggle={() => {}}
      />,
    );
    const marker = screen.getByTestId("note-marker-g1");
    expect(marker.style.background).toMatch(/rgba\(219, 39, 119, 0\.2\)/);
    expect(marker.style.width).toBe("5px");
    expect(marker.style.top).toBe("3px");
    expect(marker.getAttribute("data-dealt")).toBe("true");
    expect(screen.queryByTestId("inline-note")).not.toBeInTheDocument();
  });

  test("blank-quote notes appear only below the letter and stay collapsed by default", () => {
    render(
      <AnnotatedDraft
        text={letter}
        notes={[
          {
            id: "u1",
            title: "Already good · Human",
            color: "#16a34a",
            unanchored: true,
            body: "Whole-letter praise.",
          },
        ]}
        expandedId={null}
        onToggle={() => {}}
        renderExpanded={(note) => <div>{note.body}</div>}
      />,
    );
    expect(screen.getByText("Notes on the letter as a whole")).toBeInTheDocument();
    expect(screen.getByText("Already good · Human")).toBeInTheDocument();
    expect(screen.queryByText("Whole-letter praise.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Already good · Human")).not.toBeInTheDocument();
  });
});
