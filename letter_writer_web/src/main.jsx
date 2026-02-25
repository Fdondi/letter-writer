import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import App from "./App";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { setupApiNotifications } from "./utils/apiNotifications";
import { LanguageProvider } from "./contexts/LanguageContext";

// Install global fetch wrapper for API completion notifications.
setupApiNotifications();

function AppWithFlow() {
  const location = useLocation();
  const flow = location.pathname.startsWith("/flows/agentic") ? "agentic" : "vendor";
  return <App flow={flow} />;
}

// NOTE: StrictMode is intentionally NOT enabled to avoid double-rendering in development
// which causes duplicate API calls and 202 heartbeat responses.
// If you need to enable it for debugging, wrap <App /> with <React.StrictMode>
const rootEl = document.getElementById("root");
createRoot(rootEl).render(
  <BrowserRouter>
    <DndProvider backend={HTML5Backend}>
      <LanguageProvider>
        <Routes>
          <Route path="/flows/vendors" element={<AppWithFlow />} />
          <Route path="/flows/agentic" element={<AppWithFlow />} />
          <Route path="/" element={<AppWithFlow />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </LanguageProvider>
    </DndProvider>
  </BrowserRouter>
); 