const { test, expect } = require("@playwright/test");

const CASES = [
  { id: "empty-intake", testId: "intake-page" },
  { id: "intake-filled", testId: "intake-page" },
  { id: "vendor-plan", testId: "phase-plan" },
  { id: "vendor-draft-notes", testId: "annotated-draft" },
  { id: "vendor-draft-empty-feedback", testId: "vendor-draft-view" },
  { id: "vendor-assembly", testId: "vendor-assembly" },
  { id: "agentic-mid-loop", testId: "agentic-flow" },
  { id: "agentic-done", testId: "agentic-assembly" },
  { id: "error-generate", testId: "vendor-draft-view" },
];

for (const { id, testId } of CASES) {
  test(`fixture ${id} shows harness banner and ${testId}`, async ({ page }) => {
    await page.goto(`/?fixture=${id}`);
    await expect(page.getByTestId("harness-banner")).toBeVisible();
    await expect(page.getByTestId(testId)).toBeVisible();
  });
}

test("error-generate approve hits harness LLM 503", async ({ page }) => {
  await page.goto("/?fixture=error-generate");
  await expect(page.getByTestId("vendor-draft-view")).toBeVisible();
  const approve = page.getByRole("button", { name: "Approve", exact: true }).last();
  await expect(approve).toBeVisible();
  await approve.click();
  await expect(page.getByText(/Harness: LLM disabled/i)).toBeVisible();
});

test("job-capture process fills intake from captured page text", async ({ page, request }) => {
  const ingest = await request.post("/api/job-capture/ingest/", {
    data: {
      url: "https://jobs.example/role",
      title: "Senior Engineer",
      text: "We hire for payments in Zürich.",
      html: "<p>We hire for payments in Zürich.</p>",
    },
  });
  expect(ingest.ok(), await ingest.text()).toBeTruthy();
  const body = await ingest.json();
  expect(body.capture_id).toBeTruthy();

  await page.route("**/api/job-capture/*/process/", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    await route.continue();
  });

  await page.goto(`/?capture=${body.capture_id}`);
  await expect(page.getByTestId("harness-banner")).toBeVisible();
  await expect(page.getByTestId("intake-page")).toBeVisible();
  await expect(page.getByTestId("capture-extracting-banner")).toBeVisible();
  await expect(page.getByLabel("Original URL")).toHaveValue("https://jobs.example/role");
  await expect(
    page.getByPlaceholder(/Paste job description here/i)
  ).toHaveValue("We hire for payments in Zürich.", { timeout: 20_000 });
  await expect(page.getByPlaceholder("Job title")).toHaveValue("Senior Engineer");
  await expect(page.getByLabel("Original URL")).toHaveValue("https://jobs.example/role");
  await expect(page.getByTestId("capture-extracting-banner")).toBeHidden();
});
