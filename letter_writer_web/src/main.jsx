import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { setupApiNotifications } from "./utils/apiNotifications";

// Install global fetch wrapper for API completion notifications.
setupApiNotifications();

// NOTE: StrictMode is intentionally NOT enabled to avoid double-rendering in development
// which causes duplicate API calls and 202 heartbeat responses.
// If you need to enable it for debugging, wrap <App /> with <React.StrictMode>
const rootEl = document.getElementById("root");
createRoot(rootEl).render(
  <DndProvider backend={HTML5Backend}>
    <App />
  </DndProvider>
); 