const DEFAULT_ORIGIN = "https://localhost:8443";
const api = typeof browser !== "undefined" ? browser : chrome;

const input = document.getElementById("app-origin");
const form = document.getElementById("options-form");
const status = document.getElementById("status");

function showStatus(message) {
  status.hidden = false;
  status.textContent = message;
}

api.storage.local.get({ appOrigin: DEFAULT_ORIGIN }).then((stored) => {
  input.value = stored.appOrigin || DEFAULT_ORIGIN;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const origin = input.value.trim().replace(/\/+$/, "");
  if (!origin) {
    showStatus("Origin is required.");
    return;
  }
  try {
    const parsed = new URL(origin);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      showStatus("Origin must be an http(s) URL.");
      return;
    }
  } catch {
    showStatus("Not a valid URL.");
    return;
  }

  if (typeof api.permissions?.request === "function") {
    try {
      await api.permissions.request({ origins: [`${origin}/*`] });
    } catch (e) {
      console.warn("Optional host permission request failed:", e);
    }
  }

  await api.storage.local.set({ appOrigin: origin });
  showStatus("Saved.");
});
