import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { setupApiNotifications } from "./utils/apiNotifications";
import { LanguageProvider } from "./contexts/LanguageContext";

// If opened at https://localhost (no port), redirect to https://localhost:8443 so OAuth and cookies work
if (
  typeof window !== "undefined" &&
  window.location.hostname === "localhost" &&
  window.location.protocol === "https:" &&
  (window.location.port === "" || window.location.port === "443")
) {
  window.location.replace(
    "https://localhost:8443" + window.location.pathname + window.location.search
  );
}

// Install global fetch wrapper for API completion notifications.
setupApiNotifications();

// NOTE: StrictMode is intentionally NOT enabled to avoid double-rendering in development
// which causes duplicate API calls and 202 heartbeat responses.
// If you need to enable it for debugging, wrap <App /> with <React.StrictMode>
const rootEl = document.getElementById("root");
createRoot(rootEl).render(
  <DndProvider backend={HTML5Backend}>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </DndProvider>
); 