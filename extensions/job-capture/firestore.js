// Direct Firestore access for the extension: the queue writes of pipeline.js and the pending-jobs
// queries, plus the Google sign-in the Firestore rules require (firebase/firestore.rules: writes
// need a Google-linked Firebase Auth token whose `sub` is the user_id). Plain REST — no SDK, no
// build step. The client is injected with its base URL and token getter, so the same code runs
// against the Firestore emulator in firebase/tests/extension-firestore.test.mjs.
/* exported LW_FIRESTORE */
const LW_FIRESTORE = (() => {
  const PROJECT_ID = "gen-lang-client-0535858734";
  const DATABASE_ID = "letter";
  // Public values from app/app/google-services.json and app/local.properties (not secrets).
  const API_KEY = "AIzaSyBrzL4mDFhvA8zuhj5DaNM4eFf_HNVWkdA";
  // The web client Firebase Auth's Google provider is configured with (Firebase console →
  // Authentication → Sign-in method → Google → Web SDK configuration; the same client
  // app/app/google-services.json lists as its web client). signInWithIdp rejects id_tokens
  // whose aud is any other client — the desktop app's own web client or the Android client
  // (io.github.fdondi.letterwriter) do not work here.
  const GOOGLE_CLIENT_ID = "218248446074-e6emeq1df844r8fimneg8l7vtgkqd05c.apps.googleusercontent.com";
  const FIRESTORE_BASE = `https://firestore.googleapis.com/v1/projects/${PROJECT_ID}/databases/${DATABASE_ID}/documents`;
  const IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1";
  const SECURE_TOKEN = "https://securetoken.googleapis.com/v1";
  const AUTH_STORAGE_KEY = "lwAuth";
  const TOKEN_REFRESH_MARGIN_MS = 60000;

  function firestoreError(code, message) {
    const err = new Error(message);
    err.code = code;
    return err;
  }

  // --- Firestore REST value codecs ---------------------------------------------------------

  function toValue(value) {
    if (value === null || value === undefined) return { nullValue: null };
    if (typeof value === "boolean") return { booleanValue: value };
    if (typeof value === "number") {
      return Number.isInteger(value) ? { integerValue: String(value) } : { doubleValue: value };
    }
    if (typeof value === "string") return { stringValue: value };
    if (value instanceof Date) return { timestampValue: value.toISOString() };
    if (Array.isArray(value)) return { arrayValue: { values: value.map(toValue) } };
    if (typeof value === "object") return { mapValue: { fields: encodeFields(value) } };
    throw new Error(`unsupported Firestore value: ${typeof value}`);
  }

  function fromValue(value) {
    if (!value || typeof value !== "object") return null;
    if (value.nullValue !== undefined) return null;
    if (value.stringValue !== undefined) return value.stringValue;
    if (value.integerValue !== undefined) return parseInt(value.integerValue, 10);
    if (value.doubleValue !== undefined) return value.doubleValue;
    if (value.booleanValue !== undefined) return value.booleanValue;
    if (value.timestampValue !== undefined) return value.timestampValue; // ISO string
    if (value.arrayValue !== undefined) return (value.arrayValue.values || []).map(fromValue);
    if (value.mapValue !== undefined) return decodeFields(value.mapValue.fields || {});
    return null;
  }

  function encodeFields(obj) {
    const out = {};
    for (const [k, v] of Object.entries(obj || {})) out[k] = toValue(v);
    return out;
  }

  function decodeFields(fields) {
    const out = {};
    for (const [k, v] of Object.entries(fields || {})) out[k] = fromValue(v);
    return out;
  }

  // --- Firestore REST client ----------------------------------------------------------------

  function createClient({ baseUrl = FIRESTORE_BASE, getIdToken }) {
    // Commit writes name documents by resource path (`projects/.../documents/...`), not URL.
    const namePrefix = baseUrl.replace(/^.+?\/v1\//, "");
    async function authedFetch(url, init) {
      const token = await getIdToken();
      if (!token) throw firestoreError("UNAUTHENTICATED", "Not signed in to Firestore.");
      return fetch(url, {
        ...(init || {}),
        headers: { ...((init && init.headers) || {}), Authorization: `Bearer ${token}` },
      });
    }

    async function parseError(response) {
      const body = await response.json().catch(() => ({}));
      const status = (body && body.error && body.error.status) || "";
      const message = (body && body.error && body.error.message) || response.statusText || `HTTP ${response.status}`;
      return firestoreError(status || `HTTP_${response.status}`, message);
    }

    async function getDocument(path) {
      const response = await authedFetch(`${baseUrl}/${path}`);
      if (response.status === 404) return null;
      if (!response.ok) throw await parseError(response);
      const doc = await response.json();
      return { id: doc.name.split("/").pop(), ...decodeFields(doc.fields || {}) };
    }

    async function commit(write) {
      const response = await authedFetch(`${baseUrl}:commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ writes: [write] }),
      });
      if (!response.ok) throw await parseError(response);
    }

    /** Create only when the document does not exist (atomic; the rules also gate the fields).
     * The Write proto has no `create` operation: a create is an `update` write with an
     * exists:false precondition, and `update` carries the Document itself. */
    async function createIfAbsent(path, fields) {
      await commit({
        update: { name: `${namePrefix}/${path}`, fields: encodeFields(fields) },
        currentDocument: { exists: false },
      });
    }

    /** Update only the given top-level fields; the rules reject updates while the batch drafts. */
    async function update(path, fields) {
      await commit({
        update: { name: `${namePrefix}/${path}`, fields: encodeFields(fields) },
        updateMask: { fieldPaths: Object.keys(fields) },
        currentDocument: { exists: true },
      });
    }

    /** Equality filters ANDed together; the rules only allow listing the caller's own jobs. */
    async function query(collectionId, filters, selectFields) {
      const response = await authedFetch(`${baseUrl}:runQuery`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          structuredQuery: {
            from: [{ collectionId }],
            where: {
              compositeFilter: {
                op: "AND",
                filters: filters.map(([field, value]) => ({
                  fieldFilter: { field: { fieldPath: field }, op: "EQUAL", value: toValue(value) },
                })),
              },
            },
            select: { fields: selectFields.map((f) => ({ fieldPath: f })) },
          },
        }),
      });
      if (!response.ok) throw await parseError(response);
      const rows = await response.json();
      return (Array.isArray(rows) ? rows : [])
        .filter((row) => row.document)
        .map((row) => ({ id: row.document.name.split("/").pop(), ...decodeFields(row.document.fields || {}) }));
    }

    function queryApproved(userId) {
      return query("opportunities", [["user_id", userId], ["status", "approved"]], ["url", "canonical_key", "status"]);
    }

    function queryByCanonicalKey(userId, key) {
      return query(
        "opportunities",
        [["user_id", userId], ["status", "approved"], ["canonical_key", key]],
        ["url", "canonical_key", "status"],
      );
    }

    return { getDocument, createIfAbsent, update, query, queryApproved, queryByCanonicalKey };
  }

  // --- Google sign-in → Firebase Auth (REST) -------------------------------------------------

  function launchWebAuthFlow(api, details) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (fn, value) => {
        if (!settled) {
          settled = true;
          fn(value);
        }
      };
      try {
        const maybe = api.identity.launchWebAuthFlow(details, (result) => {
          const err = api.runtime && api.runtime.lastError;
          if (err) finish(reject, new Error(err.message || String(err)));
          else if (!result) finish(reject, new Error("Sign-in was cancelled."));
          else finish(resolve, result);
        });
        if (maybe && typeof maybe.then === "function") {
          maybe.then(finish.bind(null, resolve), finish.bind(null, reject));
        }
      } catch (e) {
        finish(reject, e);
      }
    });
  }

  /** Decode a JWT payload without verifying it — the signature was verified by Google/Firebase
   * when the token was issued; the payload is only read for the account id. */
  function decodeJwtPayload(token) {
    const part = String(token || "").split(".")[1];
    if (!part) return {};
    const bytes = Uint8Array.from(atob(part.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  }

  /** The Google account id (sub): the Firebase token's identities['google.com'][0] — exactly
   * what the Firestore rules read from the bearer token. The Firebase localId is a different
   * id when the account was created with email/password and Google linked later, so it must
   * not be used as the user id (the phone app uses the Google account id; the desktop's
   * LW_USER_ID is the sub). */
  function googleSub(firebaseIdToken, googleIdToken) {
    try {
      const payload = decodeJwtPayload(firebaseIdToken);
      const identities = payload && payload.firebase && payload.firebase.identities;
      const google = identities && identities["google.com"];
      if (Array.isArray(google) && google[0]) return google[0];
    } catch (e) { /* fall through to the Google token's sub */ }
    try {
      return decodeJwtPayload(googleIdToken).sub || "";
    } catch (e) {
      return "";
    }
  }

  function createAuth({ api }) {
    function available() {
      return !!(api.identity && typeof api.identity.launchWebAuthFlow === "function");
    }

    /** The OAuth redirect URI to register in Google Cloud (the only console value the sign-in
     * needs — the authorized-domains list is SDK-only, see options.html). */
    function redirectInfo() {
      let redirectUri = "";
      try {
        const generated = api.identity.getRedirectURL();
        redirectUri = generated.includes("chromiumapp.org")
          ? generated // Chrome: https://<extension-id>.chromiumapp.org/
          : `http://127.0.0.1/mozoauth2/${new URL(generated).hostname.split(".")[0]}`; // Firefox loopback (RFC 8252)
      } catch (e) {
        redirectUri = "";
      }
      return { redirectUri };
    }

    async function readStored() {
      const stored = await api.storage.local.get({ [AUTH_STORAGE_KEY]: null });
      return stored[AUTH_STORAGE_KEY] || null;
    }

    async function status() {
      const auth = await readStored();
      return auth && auth.refreshToken
        ? { signedIn: true, userId: auth.userId || "", email: auth.email || "", displayName: auth.displayName || "" }
        : { signedIn: false, userId: "", email: "", displayName: "" };
    }

    async function signOut() {
      await api.storage.local.remove(AUTH_STORAGE_KEY);
    }

    /** A valid Firebase id token, refreshing it when close to expiry; null when signed out. */
    async function getIdToken() {
      const auth = await readStored();
      if (!auth || !auth.refreshToken) return null;
      if (auth.idToken && Date.now() < auth.expiresAt - TOKEN_REFRESH_MARGIN_MS) return auth.idToken;
      try {
        const response = await fetch(`${SECURE_TOKEN}/token?key=${API_KEY}`, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: `grant_type=refresh_token&refresh_token=${encodeURIComponent(auth.refreshToken)}`,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.id_token) {
          throw new Error((data.error && data.error.message) || "token refresh failed");
        }
        const next = {
          ...auth,
          idToken: data.id_token,
          refreshToken: data.refresh_token || auth.refreshToken,
          expiresAt: Date.now() + (parseInt(data.expires_in, 10) || 3600) * 1000,
        };
        await api.storage.local.set({ [AUTH_STORAGE_KEY]: next });
        return next.idToken;
      } catch (e) {
        await api.storage.local.remove(AUTH_STORAGE_KEY); // stale refresh token: sign in again
        return null;
      }
    }

    /** Google sign-in through the browser's identity API, exchanged for Firebase credentials.
     * The Firestore rules key on the Google `sub`, which becomes the opportunity user_id. */
    async function signIn(interactive) {
      if (!available()) {
        throw new Error("This browser has no extension sign-in API (Firefox for Android); use the stash flow or a desktop browser.");
      }
      const { redirectUri } = redirectInfo();
      const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
      const authUrl =
        "https://accounts.google.com/o/oauth2/v2/auth?" +
        new URLSearchParams({
          client_id: GOOGLE_CLIENT_ID,
          redirect_uri: redirectUri,
          response_type: "id_token",
          scope: "openid email profile",
          nonce,
          prompt: "select_account",
        }).toString();
      // Neither browser's schema has a redirect property — Firefox's identity.json declares
      // `url` + `interactive` only, Chrome's likewise — and both reject unknown properties with
      // "Unexpected property". The redirect URI rides solely in the authorization URL's
      // redirect_uri parameter; each browser intercepts its own generated redirect URL there
      // (Chrome: chromiumapp.org, Firefox: the mozoauth2 loopback, RFC 8252).
      const redirect = await launchWebAuthFlow(api, {
        url: authUrl,
        interactive: !!interactive,
      });
      const googleIdToken = new URLSearchParams(new URL(redirect).hash.replace(/^#/, "")).get("id_token");
      if (!googleIdToken) throw new Error("Google sign-in returned no id token.");
      const response = await fetch(`${IDENTITY_TOOLKIT}/accounts:signInWithIdp?key=${API_KEY}`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          postBody: `id_token=${googleIdToken}&providerId=google.com`,
          // identitytoolkit rejects a non-http(s) requestUri — the extension origin
          // (moz-extension://<uuid>/) gets INVALID_REQUEST_URI; http://localhost is the
          // conventional stand-in (probed against the REST endpoint).
          requestUri: "http://localhost",
          returnSecureToken: "true",
          autoCreate: "true",
        }).toString(),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.idToken) {
        throw new Error((data.error && data.error.message) || "Firebase sign-in failed");
      }
      const profile = {
        refreshToken: data.refreshToken || "",
        idToken: data.idToken,
        expiresAt: Date.now() + (parseInt(data.expiresIn, 10) || 3600) * 1000,
        // The Google account id (sub) — the id the Firestore rules key on, the phone app's
        // user id, and the personal_data doc id. Not the Firebase localId (they differ when
        // the account was created with email/password and Google linked later), and not
        // federatedId (not reliably the raw sub) — read it from the tokens.
        userId: googleSub(data.idToken, googleIdToken) || data.federatedId || data.localId || "",
        email: data.email || "",
        displayName: data.displayName || "",
      };
      await api.storage.local.set({ [AUTH_STORAGE_KEY]: profile });
      return profile;
    }

    return { available, redirectInfo, status, signIn, signOut, getIdToken };
  }

  return {
    PROJECT_ID,
    DATABASE_ID,
    FIRESTORE_BASE,
    GOOGLE_CLIENT_ID,
    API_KEY,
    toValue,
    fromValue,
    encodeFields,
    decodeFields,
    createClient,
    createAuth,
  };
})();

if (typeof module !== "undefined") {
  module.exports = LW_FIRESTORE;
}
