# UI overlay pattern

**Keep this behavior.**

- **AI Instructions**, **CV**, **Previous Examples**, and **Settings** are overlays over the main flow. They occupy ~90% of the screen, do not navigate away, and closing them returns to where the user was.
- **Compose**, **agentic flow**, and **vendor flow** are not buttons or pages you navigate to. The main content is always the flow. The flow (vendor vs agentic) is fixed per page load—no switching; the two are incompatible.

Do not convert these overlays back to full-page navigation. Do not add flow-switching buttons.
