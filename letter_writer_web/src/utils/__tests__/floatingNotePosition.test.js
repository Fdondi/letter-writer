import { placeFloatingNote } from "../floatingNotePosition";

describe("placeFloatingNote", () => {
  test("centers on the letter card and stays inset from the sides", () => {
    const pos = placeFloatingNote({ bottom: 200 }, { left: 100, width: 340 });
    expect(pos.width).toBe(324);
    expect(pos.left).toBe(108);
    expect(pos.top).toBe(204);
    expect(pos.maxHeight).toBeNull();
  });

  test("does not follow a marker at the card edge off the card", () => {
    const pos = placeFloatingNote({ bottom: 80, left: 100, right: 108 }, { left: 100, width: 340 });
    expect(pos.left).toBeGreaterThan(100);
    expect(pos.left + pos.width).toBeLessThanOrEqual(100 + 340);
  });

  test("keeps the note under the quote when there is room below", () => {
    const pos = placeFloatingNote({ bottom: 200 }, { left: 100, width: 340 }, 8, { height: 800 });
    expect(pos.top).toBe(204);
    expect(pos.maxHeight).toBe(800 - 8 - 204);
    expect(pos.top + pos.maxHeight).toBe(792);
  });

  test("lifts and caps height so the bottom stays on screen", () => {
    const pos = placeFloatingNote({ bottom: 760 }, { left: 100, width: 340 }, 8, { height: 800 });
    expect(pos.top).toBeGreaterThanOrEqual(8);
    expect(pos.top + pos.maxHeight).toBeLessThanOrEqual(792);
    expect(pos.maxHeight).toBeGreaterThan(0);
  });
});
