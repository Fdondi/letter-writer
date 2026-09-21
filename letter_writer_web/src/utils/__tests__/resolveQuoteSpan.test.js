import { findExactSpan, findNormalizedSpan, resolveQuoteSpan, splitHighlightedSegments } from "../resolveQuoteSpan";

describe("resolveQuoteSpan", () => {
  const letter = "Dear team,\nI enjoy working with cats.\nKind regards";

  test("exact match", () => {
    const exact = findExactSpan(letter, "working with cats");
    expect(letter.slice(exact.start, exact.end)).toBe("working with cats");
    const span = resolveQuoteSpan(letter, "working with cats", "");
    expect(letter.slice(span.start, span.end)).toBe("working with cats");
  });

  test("prefers matched_text then quote", () => {
    const span = resolveQuoteSpan(letter, "missing quote", "working with cats");
    expect(letter.slice(span.start, span.end)).toBe("working with cats");
  });

  test("normalized whitespace and case", () => {
    const span = findNormalizedSpan(letter, "WORKING   with   CATS");
    expect(span).not.toBeNull();
    expect(letter.slice(span.start, span.end).toLowerCase()).toContain("cats");
  });

  test("miss returns null", () => {
    expect(resolveQuoteSpan(letter, "no such passage", "")).toBeNull();
  });
});

describe("splitHighlightedSegments", () => {
  test("splits overlapping ranges", () => {
    const segs = splitHighlightedSegments("abcdefgh", [
      { id: "a", start: 1, end: 5 },
      { id: "b", start: 3, end: 7 },
    ]);
    const covering = segs.map((s) => s.noteIds.join("+") + ":" + s.text);
    expect(covering).toContain("a:bc");
    expect(covering).toContain("a+b:de");
    expect(covering).toContain("b:fg");
  });
});
