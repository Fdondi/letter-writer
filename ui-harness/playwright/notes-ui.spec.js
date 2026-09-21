const { test, expect } = require("@playwright/test");

test("vendor draft notes use topic color, overlay under the quote, and + on each category", async ({ page }) => {
  await page.goto("/?fixture=vendor-draft-notes");
  await expect(page.getByTestId("harness-banner")).toBeVisible();
  await expect(page.getByTestId("annotated-draft")).toBeVisible();

  await expect(page.getByRole("button", { name: /^Add critique · / })).toHaveCount(7);
  await expect(page.getByRole("button", { name: "Add critique · Precision" })).toBeVisible();
  await expect(page.getByText("Add critique · precision")).toHaveCount(0);

  const fixMarker = page.getByTestId("note-marker-fix1");
  const goodMarker = page.getByTestId("note-marker-good1");
  await expect(fixMarker).toBeVisible();
  await expect(goodMarker).toBeVisible();

  const fixBg = await fixMarker.evaluate((el) => getComputedStyle(el).backgroundColor);
  const goodBg = await goodMarker.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(fixBg).toMatch(/217,\s*119,\s*6/);
  expect(goodBg).toMatch(/219,\s*39,\s*119/);
  expect(goodBg).toMatch(/0\.2[0-9]/);

  await expect(page.getByTestId("inline-note")).toHaveCount(0);
  await fixMarker.click();
  const inline = page.getByTestId("inline-note");
  await expect(inline).toBeVisible();
  await expect(inline).toContainText("Name the stack instead of the generic phrase.");
  await expect(page.getByTestId("annotated-letter").getByTestId("inline-note")).toBeVisible();

  const quoteMark = page.locator('mark[data-note-id="fix1"]').last();
  const markBox = await quoteMark.boundingBox();
  const noteBox = await inline.boundingBox();
  expect(markBox).toBeTruthy();
  expect(noteBox).toBeTruthy();
  expect(noteBox.y).toBeGreaterThanOrEqual(markBox.y + markBox.height - 2);

  await expect(page.getByTestId("unanchored-notes")).toBeVisible();
  await expect(page.getByTestId("unanchored-notes")).toContainText(
    "The letter as a whole stays short enough for this synthetic posting.",
  );
  await expect(page.getByTestId("unanchored-notes")).not.toContainText("Name the stack");
});
