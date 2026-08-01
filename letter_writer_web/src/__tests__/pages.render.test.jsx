/**
 * Build-gate smoke: every user-facing screen must mount without throwing.
 * Intentionally does NOT mock LetterTabs / overlay pages — those mocks hid
 * the LanguageSelector import break that only showed up in final assembly.
 */
import React from "react";
import { render, screen, waitFor, within, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { DndProvider } from "react-dnd";
import { TestBackend } from "react-dnd-test-backend";
import { LanguageProvider } from "../contexts/LanguageContext";
import { AllTestProviders, createDefaultLetterTabsProps } from "../utils/__tests__/testUtils";
import App from "../App";
import LetterTabs from "../components/LetterTabs";
import PhaseFlow from "../components/PhaseFlow";
import AgenticFlow from "../components/AgenticFlow";
import AutocompleteFlow from "../components/AutocompleteFlow";
import PersonalDataPage from "../components/PersonalDataPage";
import DocumentsPage from "../components/DocumentsPage";
import SettingsPage from "../components/SettingsPage";
import CostsPage from "../components/CostsPage";
import StyleInstructionsBlade from "../components/StyleInstructionsBlade";

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }) => <div data-testid="markdown">{children}</div>,
}));

jest.mock("../utils/apiHelpers", () => ({
  ...jest.requireActual("../utils/apiHelpers"),
  fetchWithHeartbeat: jest.fn(() =>
    Promise.resolve({ data: { instructions: "" }, isHeartbeat: false })
  ),
  initializeCsrfToken: jest.fn(() => Promise.resolve()),
  retryApiCall: jest.fn(),
  getCsrfToken: jest.fn(() => "test-csrf"),
  publishUserMonthlyCost: jest.fn(),
}));

jest.mock("../utils/googleOAuthRedirect", () => ({
  scheduleGoogleOAuthRedirect: jest.fn(),
  clearOAuthRedirectCooldown: jest.fn(),
}));

function AppWithFlow() {
  const location = useLocation();
  const flow = location.pathname.startsWith("/flows/autocomplete")
    ? "autocomplete"
    : location.pathname.startsWith("/flows/agentic")
      ? "agentic"
      : location.pathname.startsWith("/flows/vendors")
        ? "vendor"
        : "intake";
  return <App flow={flow} />;
}

function renderApp(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <DndProvider backend={TestBackend}>
        <LanguageProvider>
          <Routes>
            <Route path="*" element={<AppWithFlow />} />
          </Routes>
        </LanguageProvider>
      </DndProvider>
    </MemoryRouter>
  );
}

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return Promise.resolve({
    ok,
    status,
    text: async () => text,
    json: async () => (typeof body === "string" ? JSON.parse(body) : body),
  });
}

function installFetchMock({ authenticated = true } = {}) {
  global.fetch = jest.fn((input) => {
    const url = typeof input === "string" ? input : input?.url ?? "";
    if (String(url).includes("app-version.txt")) {
      return Promise.resolve({ ok: true, text: () => Promise.resolve("1.0.0 - Test stub") });
    }
    if (String(url).includes("/api/auth/status/")) {
      return jsonResponse({ authenticated, auth_available: true });
    }
    if (String(url).includes("/api/vendors/")) {
      return jsonResponse({
        active: ["openai"],
        inactive: [],
        local_pricing_configured: true,
      });
    }
    if (String(url).includes("/api/personal-data/")) {
      return jsonResponse({
        default_languages: [
          { code: "en", label: "English", color: "#3b82f6", enabled: true },
          { code: "de", label: "German", color: "#6366f1", enabled: true },
        ],
        cv_markdown: "# Test CV\n\nExperience.",
        default_models: [],
        background_models: [],
        autocomplete_models: [],
        min_column_width: 200,
      });
    }
    if (String(url).includes("/api/costs/user/")) {
      return jsonResponse({
        total_cost: 1.25,
        cost_available: true,
        by_phase: {},
        by_vendor: {},
        by_vendor_phase: {},
      });
    }
    if (String(url).includes("/api/costs/daily/")) {
      return jsonResponse({ cost_available: true, days: [] });
    }
    if (String(url).includes("/api/costs/models/")) {
      return jsonResponse({
        openai: [{ id: "gpt-4o", name: "GPT-4o", input: 2.5, output: 10 }],
      });
    }
    if (String(url).includes("/api/documents/")) {
      return jsonResponse({ documents: [] });
    }
    if (
      String(url).includes("/api/style-instructions/") ||
      String(url).includes("/api/structure-instructions/") ||
      String(url).includes("/api/search-instructions/")
    ) {
      return jsonResponse({ instructions: "" });
    }
    return jsonResponse({});
  });
}

function installDomShims() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: jest.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    })),
  });
  Object.defineProperty(window, "performance", {
    writable: true,
    value: { getEntriesByType: jest.fn(() => []) },
  });
  global.ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
}

function renderErrors(consoleErrorMock) {
  return consoleErrorMock.mock.calls.filter((args) => {
    const msg = args.map(String).join(" ");
    return (
      msg.includes("Error:") ||
      msg.includes("Uncaught") ||
      msg.includes("is not defined") ||
      msg.includes("Element type is invalid") ||
      msg.includes("Cannot read properties") ||
      msg.includes("310") ||
      msg.includes("Rendered more hooks than") ||
      msg.includes("Rendered fewer hooks than")
    );
  });
}

async function waitForAuthenticatedApp() {
  expect(screen.getByText(/Checking authentication/i)).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.queryByText(/Checking authentication/i)).not.toBeInTheDocument();
  });
}

describe("pages render smoke (build gate)", () => {
  let consoleErrorSpy;

  beforeEach(() => {
    installDomShims();
    consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    installFetchMock({ authenticated: true });
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    cleanup();
    jest.clearAllMocks();
  });

  const routes = [
    {
      path: "/",
      assert: async () => {
        expect(screen.getByRole("button", { name: /Start autocomplete/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Start vendor flow/i })).toBeInTheDocument();
      },
    },
    {
      path: "/flows/vendors",
      assert: async () => {
        expect(screen.getByPlaceholderText(/Paste job description here/i)).toBeInTheDocument();
      },
    },
    {
      path: "/flows/agentic",
      assert: async () => {
        expect(screen.getByPlaceholderText(/Paste job description here/i)).toBeInTheDocument();
      },
    },
    {
      path: "/flows/autocomplete",
      assert: async () => {
        expect(screen.getByText(/Autocomplete letter/i)).toBeInTheDocument();
      },
    },
  ];

  it.each(routes)("App route $path renders", async ({ path, assert }) => {
    renderApp(path);
    await waitForAuthenticatedApp();
    await assert();
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("unauthenticated App shows sign-in", async () => {
    installFetchMock({ authenticated: false });
    renderApp("/");
    await waitForAuthenticatedApp();
    expect(screen.getByText(/Sign in to continue/i)).toBeInTheDocument();
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("opens CV, Documents, Settings, Costs, and AI Instructions overlays", async () => {
    const user = userEvent.setup();
    renderApp("/flows/vendors");
    await waitForAuthenticatedApp();

    await user.click(screen.getByRole("button", { name: /^Your CV$/i }));
    const cvDialog = await screen.findByRole("dialog", { name: /^Your CV$/i });
    expect(within(cvDialog).getByRole("button", { name: /Edit/i })).toBeInTheDocument();
    await user.click(within(cvDialog).getByRole("button", { name: /Close/i }));

    await user.click(screen.getByRole("button", { name: /Previous Examples/i }));
    const docsDialog = await screen.findByRole("dialog", { name: /Previous Examples/i });
    expect(within(docsDialog).getByRole("heading", { name: /^Documents$/i })).toBeInTheDocument();
    await user.click(within(docsDialog).getByRole("button", { name: /Close/i }));

    await user.click(screen.getByRole("button", { name: /^Settings$/i }));
    const settingsDialog = await screen.findByRole("dialog", { name: /^Settings$/i });
    await waitFor(() => {
      expect(within(settingsDialog).getByText(/Default Translation Languages/i)).toBeInTheDocument();
    });
    await user.click(within(settingsDialog).getByRole("button", { name: /Close/i }));

    await waitFor(() => {
      expect(screen.getByTitle(/Your API usage this month/i)).toBeInTheDocument();
    });
    await user.click(screen.getByTitle(/Your API usage this month/i));
    const costsDialog = await screen.findByRole("dialog", { name: /API Costs/i });
    await waitFor(() => {
      expect(within(costsDialog).getByText(/Total Cost/i)).toBeInTheDocument();
    });
    await user.click(within(costsDialog).getByRole("button", { name: /Close/i }));

    await user.click(screen.getByRole("button", { name: /AI Instructions/i }));
    expect(await screen.findByRole("button", { name: /^Draft Style$/i })).toBeInTheDocument();

    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("final assembly LetterTabs renders", async () => {
    render(
      <AllTestProviders>
        <LetterTabs {...createDefaultLetterTabsProps()} />
      </AllTestProviders>
    );
    expect(screen.getByText("Final Letter")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("PhaseFlow renders with a vendor list", () => {
    render(
      <AllTestProviders>
        <PhaseFlow
          vendorsList={["openai"]}
          sessionId="test-session"
          onEditChange={jest.fn()}
          onApprove={jest.fn()}
          onApproveAll={jest.fn()}
        />
      </AllTestProviders>
    );
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("AgenticFlow empty state renders", () => {
    render(
      <AllTestProviders>
        <AgenticFlow agenticState={null} />
      </AllTestProviders>
    );
    expect(
      screen.getByText(/No agentic state. Start the agentic flow to see draft and feedback threads./i)
    ).toBeInTheDocument();
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("AutocompleteFlow renders", async () => {
    render(
      <AllTestProviders>
        <AutocompleteFlow jobText="Job description" onSaveAndCopy={jest.fn()} />
      </AllTestProviders>
    );
    await waitFor(() => {
      expect(screen.getByText(/Autocomplete letter/i)).toBeInTheDocument();
    });
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("standalone overlay pages render", async () => {
    const { unmount: unmountCv } = render(
      <AllTestProviders>
        <PersonalDataPage />
      </AllTestProviders>
    );
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /^Your CV$/i, level: 2 })).toBeInTheDocument();
    });
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
    unmountCv();

    const { unmount: unmountDocs } = render(
      <AllTestProviders>
        <DocumentsPage />
      </AllTestProviders>
    );
    expect(screen.getByText(/Documents/i)).toBeInTheDocument();
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
    unmountDocs();

    const { unmount: unmountSettings } = render(
      <AllTestProviders>
        <SettingsPage
          vendors={["openai"]}
          selectedVendors={new Set(["openai"])}
          setSelectedVendors={jest.fn()}
          setBackgroundModels={jest.fn()}
        />
      </AllTestProviders>
    );
    await waitFor(() => {
      expect(screen.getByText(/Default Translation Languages/i)).toBeInTheDocument();
    });
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
    unmountSettings();

    const { unmount: unmountCosts } = render(
      <AllTestProviders>
        <CostsPage />
      </AllTestProviders>
    );
    await waitFor(() => {
      expect(screen.getByText(/Total Cost/i)).toBeInTheDocument();
    });
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
    unmountCosts();

    render(
      <AllTestProviders>
        <StyleInstructionsBlade isOpen onClose={jest.fn()} />
      </AllTestProviders>
    );
    expect(screen.getByRole("button", { name: /^Draft Style$/i })).toBeInTheDocument();
    expect(renderErrors(consoleErrorSpy)).toHaveLength(0);
  });
});
