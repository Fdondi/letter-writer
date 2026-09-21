import { nextAnchoredNoteId } from "../nextAnchoredNoteId";

describe("nextAnchoredNoteId", () => {
  const notes = [
    { id: "a", start: 0, faint: false, unanchored: false },
    { id: "b", start: 10, faint: false, unanchored: false },
    { id: "c", start: 20, faint: true, unanchored: false },
  ];

  test("opens the next still-open note in letter order", () => {
    expect(nextAnchoredNoteId(notes, "a")).toBe("b");
  });

  test("skips dealt-with notes and wraps", () => {
    expect(nextAnchoredNoteId(notes, "b")).toBe("a");
  });

  test("returns null when nothing open remains", () => {
    const allDealt = notes.map((n) => ({ ...n, faint: true }));
    expect(nextAnchoredNoteId(allDealt, "a")).toBeNull();
  });
});
