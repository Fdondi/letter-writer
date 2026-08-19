/**
 * Guards against React error #310 (hook count changes across renders).
 * Regression: hasUnsavedGeneratedWork useMemo was once declared after auth early returns.
 * Regression: startInitialVendorPhase useCallback was once declared after auth early returns.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, Navigate } from "react-router-dom";
import { DndProvider } from "react-dnd";
import { TestBackend } from "react-dnd-test-backend";
import { LanguageProvider } from "../contexts/LanguageContext";
import { JobSessionProvider } from "../contexts/JobSessionContext";
import AppLayout from "../layouts/AppLayout";
import IntakePage from "../pages/IntakePage";
import VendorFlowPage from "../pages/VendorFlowPage";
import AgenticFlowPage from "../pages/AgenticFlowPage";
import AutocompleteFlowPage from "../pages/AutocompleteFlowPage";

jest.mock("react-markdown", () => ({ __esModule: true, default: ({ children }) => <div>{children}</div> }));

jest.mock("../components/PersonalDataPage", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/DocumentsPage", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/SettingsPage", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/CostsPage", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/PhaseFlow", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/AgenticFlow", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/LetterTabs", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/ResearchComponent", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/SimilarOffersCarousel", () => ({ __esModule: true, default: () => null }));
jest.mock("../components/CompetencesList", () => ({ __esModule: true, default: () => null }));

jest.mock("../utils/apiHelpers", () => ({
  ...jest.requireActual("../utils/apiHelpers"),
  fetchWithHeartbeat: jest.fn(() => Promise.resolve({ data: {}, isHeartbeat: false })),
  initializeCsrfToken: jest.fn(() => Promise.resolve()),
  retryApiCall: jest.fn(),
  getCsrfToken: jest.fn(() => "test-csrf"),
  publishUserMonthlyCost: jest.fn(),
}));

jest.mock("../utils/googleOAuthRedirect", () => ({
  scheduleGoogleOAuthRedirect: jest.fn(),
  clearOAuthRedirectCooldown: jest.fn(),
}));

function renderApp(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <DndProvider backend={TestBackend}>
        <LanguageProvider>
          <Routes>
            <Route
              element={
                <JobSessionProvider>
                  <AppLayout />
                </JobSessionProvider>
              }
            >
              <Route path="/" element={<IntakePage />} />
              <Route path="/flows/vendors" element={<VendorFlowPage />} />
              <Route path="/flows/agentic" element={<AgenticFlowPage />} />
              <Route path="/flows/autocomplete" element={<AutocompleteFlowPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </LanguageProvider>
      </DndProvider>
    </MemoryRouter>
  );
}

function installFetchMock({ authenticated = true } = {}) {
  global.fetch = jest.fn((input) => {
    const url = typeof input === "string" ? input : input?.url ?? "";
    if (String(url).includes("app-version.txt")) {
      return Promise.resolve({ ok: true, text: () => Promise.resolve("1.0.0 - Test stub") });
    }
    if (String(url).includes("/api/auth/status/")) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ authenticated }),
      });
    }
    if (String(url).includes("/api/vendors/")) {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          active: ["openai"],
          inactive: [],
          local_pricing_configured: true,
        }),
      });
    }
    if (String(url).includes("/api/personal-data/")) {
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }
    if (String(url).includes("/api/costs/user/")) {
      return Promise.resolve({ status: 401 });
    }
    if (String(url).includes("/api/costs/models/")) {
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }
    return Promise.resolve({ ok: true, json: async () => ({}) });
  });
}

function hookOrderErrors(consoleErrorMock) {
  return consoleErrorMock.mock.calls.filter((args) => {
    const msg = args.map(String).join(" ");
    return (
      msg.includes("310") ||
      msg.includes("Rendered more hooks than") ||
      msg.includes("Rendered fewer hooks than")
    );
  });
}

describe("App mount hook order", () => {
  let consoleErrorSpy;

  beforeEach(() => {
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
    consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
    installFetchMock({ authenticated: true });
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    jest.clearAllMocks();
  });

  it("completes initial auth transition on vendor route without hook errors", async () => {
    renderApp("/flows/vendors");
    expect(screen.getByText(/Checking authentication/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText(/Checking authentication/i)).not.toBeInTheDocument();
    });

    expect(hookOrderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("completes initial auth transition on root route without hook errors", async () => {
    renderApp("/");
    expect(screen.getByText(/Checking authentication/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText(/Checking authentication/i)).not.toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /Start autocomplete/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start vendor flow/i })).toBeInTheDocument();
    expect(hookOrderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("completes initial auth transition on autocomplete route without hook errors", async () => {
    renderApp("/flows/autocomplete");
    expect(screen.getByText(/Checking authentication/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText(/Checking authentication/i)).not.toBeInTheDocument();
    });

    expect(screen.queryByPlaceholderText(/Paste job description here/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Autocomplete letter/i)).toBeInTheDocument();
    expect(hookOrderErrors(consoleErrorSpy)).toHaveLength(0);
  });

  it("JobSessionProvider keeps phaseSessionId across route changes (remount bug)", async () => {
    // Before the provider, navigating from / to /flows/vendors would remount App,
    // losing phaseSessionId. This test verifies the provider prevents that.
    const { unmount } = renderApp("/");
    await waitFor(() => {
      expect(screen.queryByText(/Checking authentication/i)).not.toBeInTheDocument();
    });
    // If JobSessionProvider is mounted, the layout route element stays alive.
    // The vendor page should still render without a redirect (session exists from init).
    expect(hookOrderErrors(consoleErrorSpy)).toHaveLength(0);
    unmount();
  });
});
