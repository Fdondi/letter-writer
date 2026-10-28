import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OpportunitiesPage, { tabForStatus } from "../OpportunitiesPage";
import { fetchWithHeartbeat } from "../../utils/apiHelpers";

jest.mock("../../utils/apiHelpers", () => ({
  fetchWithHeartbeat: jest.fn(),
}));

// One job per tab, as the backend lists them (no capture text in lists).
const JOBS = [
  { id: "p1", status: "proposed", title: "Proposed Engineer", company: "Alpha AG", location: "Zug", source: "jobs.ch", url: "https://www.jobs.ch/x" },
  { id: "a1", status: "approved", title: "Waiting Engineer", company: "Beta AG", url: "https://www.linkedin.com/jobs/view/1" },
  { id: "c1", status: "captured", title: "Queued Engineer", company: "Gamma AG" },
  {
    id: "f1",
    status: "failed",
    title: "Failed Engineer",
    company: "Delta AG",
    vendors_failed: { openai: "boom" },
  },
  {
    id: "r1",
    status: "ready",
    title: "Ready Engineer",
    company: "Epsilon AG",
    vendors_done: ["claude_code", "openai"],
    vendors_failed: { gemini: "limit" },
    input_needed_count: 3,
    fit_summary: { matched: ["C++", "CUDA"], gaps: ["Rust"] },
  },
  { id: "s1", status: "skipped", title: "Skipped Engineer", skip_reason: "Location" },
  {
    id: "ap1",
    status: "applied",
    title: "Applied Engineer",
    company: "Zeta AG",
    document_id: "doc-1",
    outcome: { stage: "interview", interviews: 2, result: "rejected", positive_feedback: true, feedback_quotes: ["Strong letter."] },
  },
];

function mockList(jobs = JOBS) {
  global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ opportunities: jobs }) }));
}

beforeEach(() => {
  mockList();
  fetchWithHeartbeat.mockReset();
  fetchWithHeartbeat.mockResolvedValue({ data: { status: "ok", message: "Done." } });
});

test("tabs count jobs by status and open on the first tab with work", async () => {
  render(<OpportunitiesPage />);
  expect(await screen.findByText("Proposed Engineer")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Proposed (1)" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tab", { name: "Needs text (1)" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Drafting (2)" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Ready (1)" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Applied (1)" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Skipped (1)" })).toBeInTheDocument();
  expect(screen.queryByText("Ready Engineer")).not.toBeInTheDocument();
});

test("each tab renders its jobs and actions", async () => {
  const user = userEvent.setup();
  render(<OpportunitiesPage />);
  await screen.findByText("Proposed Engineer");

  const proposed = screen.getByTestId("opportunity-p1");
  expect(within(proposed).getByText("Alpha AG · Zug · jobs.ch")).toBeInTheDocument();
  expect(within(proposed).getByRole("link", { name: "Proposed Engineer" })).toHaveAttribute("rel", "noopener noreferrer");
  expect(within(proposed).getByRole("button", { name: "Approve" })).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /Needs text/ }));
  expect(within(screen.getByTestId("opportunity-a1")).getByRole("button", { name: "Paste text" })).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /Drafting/ }));
  expect(screen.getByText("queued for the next desktop run")).toBeInTheDocument();
  const failed = screen.getByTestId("opportunity-f1");
  expect(within(failed).getByText("openai failed")).toBeInTheDocument();
  expect(within(failed).getByRole("button", { name: "Retry" })).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /Ready/ }));
  const ready = screen.getByTestId("opportunity-r1");
  expect(within(ready).getByText("Claude Code")).toBeInTheDocument();
  expect(within(ready).getByText("gemini failed")).toBeInTheDocument();
  expect(within(ready).getByText("3 questions for you")).toBeInTheDocument();
  expect(within(ready).getByText("gap: Rust")).toBeInTheDocument();
  expect(within(ready).getByRole("button", { name: "Craft letter" })).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /Skipped/ }));
  expect(screen.getByText("Skipped: Location")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /Applied/ }));
  const applied = screen.getByTestId("opportunity-ap1");
  expect(within(applied).getByText("interview ×2")).toBeInTheDocument();
  expect(within(applied).getByText("rejected")).toBeInTheDocument();
  expect(within(applied).getByText("praised").parentElement).toHaveAttribute("title", "Strong letter.");
  expect(within(applied).getByText("letter from this app")).toBeInTheDocument();
});

test("approve, skip with a reason, and paste text call the API and reload", async () => {
  const user = userEvent.setup();
  render(<OpportunitiesPage />);
  await screen.findByText("Proposed Engineer");
  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(fetchWithHeartbeat).toHaveBeenCalledWith("/api/opportunities/p1/approve/", { method: "POST", body: "{}" });

  await user.click(screen.getByRole("button", { name: "Skip" }));
  await user.click(screen.getByRole("button", { name: "Location" }));
  expect(fetchWithHeartbeat).toHaveBeenCalledWith("/api/opportunities/p1/skip/", { method: "POST", body: JSON.stringify({ reason: "Location" }) });

  await user.click(screen.getByRole("tab", { name: /Needs text/ }));
  await user.click(screen.getByRole("button", { name: "Paste text" }));
  await user.type(screen.getByLabelText("Posting text"), "Full posting");
  await user.click(screen.getByRole("button", { name: "Send to the desktop" }));
  expect(fetchWithHeartbeat).toHaveBeenCalledWith("/api/opportunities/a1/capture/", { method: "POST", body: JSON.stringify({ text: "Full posting" }) });
  await waitFor(() => expect(global.fetch.mock.calls.length).toBeGreaterThanOrEqual(4));
});

test("crafting the letter of a ready job hands its session to the caller", async () => {
  const user = userEvent.setup();
  const onOpened = jest.fn();
  fetchWithHeartbeat.mockResolvedValue({ data: { session_state: { vendors: { openai: {} } }, session_id: "s1", opportunity: { id: "r1", title: "Ready Engineer" } } });
  render(<OpportunitiesPage onOpened={onOpened} highlightId="r1" />);
  await screen.findByText("Ready Engineer");
  expect(screen.getByRole("tab", { name: /Ready/ })).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("button", { name: "Craft letter" }));
  expect(fetchWithHeartbeat).toHaveBeenCalledWith("/api/opportunities/r1/open/", { method: "POST" });
  expect(onOpened).toHaveBeenCalledWith({ vendors: { openai: {} } }, "s1", { id: "r1", title: "Ready Engineer" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Craft letter" })).not.toBeDisabled());
});

test("a failed action shows the error and keeps the list", async () => {
  const user = userEvent.setup();
  fetchWithHeartbeat.mockRejectedValue(new Error("This job is now 'drafting'"));
  render(<OpportunitiesPage />);
  await screen.findByText("Proposed Engineer");
  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("This job is now 'drafting'");
  expect(screen.getByText("Proposed Engineer")).toBeInTheDocument();
});

test("an empty or failing list renders instead of crashing", async () => {
  mockList([]);
  const { unmount } = render(<OpportunitiesPage />);
  expect(await screen.findByText("Nothing here.")).toBeInTheDocument();
  unmount();
  global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 503, text: () => Promise.resolve("Firestore unavailable") }));
  render(<OpportunitiesPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Firestore unavailable");
});

test("tabForStatus", () => {
  expect(tabForStatus("failed")).toBe("drafting");
  expect(tabForStatus("applied")).toBe("applied");
  expect(tabForStatus("skipped")).toBe("skipped");
  expect(tabForStatus("unknown")).toBe("proposed");
});
