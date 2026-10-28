const DEFAULT_ORIGIN = "https://localhost:8443";
const api = typeof browser !== "undefined" ? browser : chrome;

const input = document.getElementById("app-origin");
const queueInput = document.getElementById("queue-jobs");
const form = document.getElementById("options-form");
const status = document.getElementById("status");
const authStatus = document.getElementById("auth-status");
const signInBtn = document.getElementById("sign-in");
const signOutBtn = document.getElementById("sign-out");
const setupRedirect = document.getElementById("setup-redirect");
const setupClient = document.getElementById("setup-client");

function showStatus(message) {
  status.hidden = false;
  status.textContent = message;
}

api.storage.local.get({ appOrigin: DEFAULT_ORIGIN, queueJobs: true }).then((stored) => {
  input.value = stored.appOrigin || DEFAULT_ORIGIN;
  queueInput.checked = stored.queueJobs !== false;
});

const auth = LW_FIRESTORE.createAuth({ api });

// The client the redirect URI must be registered on — shown next to it so the setup cannot
// register the URI on the wrong OAuth client (a redirect_uri_mismatch at sign-in almost always
// means exactly that, or an extension older than 1.3.3 still using the desktop app's client).
setupClient.textContent = LW_FIRESTORE.GOOGLE_CLIENT_ID;

async function refreshAuthUi() {
  const s = await auth.status();
  if (s.signedIn) {
    authStatus.textContent = `Signed in as ${s.email || s.userId} — queued jobs go to your pipeline.`;
    signInBtn.hidden = true;
    signOutBtn.hidden = false;
  } else {
    authStatus.textContent = "Not signed in — queueing falls back to the app origin below.";
    signInBtn.hidden = false;
    signOutBtn.hidden = true;
  }
  if (auth.available()) {
    const info = auth.redirectInfo();
    setupRedirect.textContent = info.redirectUri || "(unavailable)";
  } else {
    authStatus.textContent +=
      " This browser has no extension sign-in API (Firefox for Android): sending a page" +
      " hands it to the Letter Writer app, which queues the job — install the app and sign in there." +
      " Queueing stays on (it is what triggers the handoff) and the stash flow below is unavailable" +
      " (there is no app server on the phone). Auto-capture stays off (no pending list without" +
      " Firestore or the app server).";
    signInBtn.hidden = true;
    signOutBtn.hidden = true;
    setupRedirect.textContent = "(unavailable on this browser)";
    // The handoff only happens in the queue path; the stash flow is a dead end without a server.
    queueInput.checked = true;
    queueInput.disabled = true;
    input.disabled = true;
  }
}

signInBtn.addEventListener("click", async () => {
  signInBtn.disabled = true;
  try {
    await auth.signIn(true);
    await refreshAuthUi();
    showStatus("Signed in.");
  } catch (e) {
    showStatus(`Sign-in failed: ${e.message}`);
  } finally {
    signInBtn.disabled = false;
  }
});

signOutBtn.addEventListener("click", async () => {
  await auth.signOut();
  await refreshAuthUi();
});

refreshAuthUi();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const origin = input.disabled ? "" : input.value.trim().replace(/\/+$/, "");
  if (!input.disabled) {
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
  }

  await api.storage.local.set({
    ...(input.disabled ? {} : { appOrigin: origin, appOriginExplicit: true }),
    queueJobs: queueInput.checked,
  });
  showStatus("Saved.");
});
