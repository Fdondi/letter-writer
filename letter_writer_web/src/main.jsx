import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { LanguageProvider } from "./contexts/LanguageContext.jsx";
import { JobSessionProvider } from "./contexts/JobSessionContext.jsx";
import AppLayout from "./layouts/AppLayout.jsx";
import IntakePage from "./pages/IntakePage.jsx";
import VendorFlowPage from "./pages/VendorFlowPage.jsx";
import AgenticFlowPage from "./pages/AgenticFlowPage.jsx";
import AutocompleteFlowPage from "./pages/AutocompleteFlowPage.jsx";
import { setupApiNotifications } from "./utils/apiNotifications";
import "./critical-theme.css";

// Vite base URL for runtime-only static assets (e.g. public/app-version.txt). Set before render; not part of the bundle graph.
if (typeof document !== "undefined") {
  document.documentElement.dataset.viteBaseUrl = import.meta.env.BASE_URL;
}

// Install global fetch wrapper for API completion notifications.
setupApiNotifications();

// NOTE: StrictMode is intentionally NOT enabled to avoid double-rendering in development
// which causes duplicate API calls and 202 heartbeat responses.
const rootEl = document.getElementById("root");
createRoot(rootEl).render(
  <BrowserRouter>
    <DndProvider backend={HTML5Backend}>
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
  </BrowserRouter>
);
