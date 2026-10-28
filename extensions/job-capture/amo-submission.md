# AMO submission texts — Letter Writer Capture 1.3.9 (unlisted)

Paste-ready texts for the addons.mozilla.org Developer Hub form when uploading
`dist/letter-writer-capture-1.3.9.xpi` as an **unlisted** add-on. The two sections below map to
the form's **Version notes** and **Notes to Reviewer** fields. Source: `github.com/Fdondi/letter-writer`
(`extensions/job-capture/`); the packaged files are those sources verbatim (`package.sh` copies them).

## Version notes

**1.3.9 — the ✓ tooltip names the job; the badge shows how many drafts are ready**

- The ✓ tooltip now names the job that was queued — its title and company (`Senior Engineer —
  Acme`), falling back to the page title — instead of the Firestore document id, and no longer
  appends the "Saved. The desktop drafts it on its next run." boilerplate. A note is still
  appended when the job is not a plain capture, e.g. "(The desktop is drafting this job right
  now.)".
- The toolbar badge now shows your pipeline at a glance: the badge itself counts the drafts that
  are **ready for your attention**, and hovering it reads `Letter Writer: N queued · N running ·
  N ready`. The counts refresh on startup, every 15 minutes, and after each capture; they are
  read from your own Firestore jobs, scoped to your account by the rules.
- No other changes. See 1.3.8 … 1.3.0 below.

### Previous version — 1.3.8: the badge clears when the page changes; the ✓ tooltip names the uploaded document

- The toolbar badge's ✓ (or →) meant "this page was captured", but it stayed after the tab
  navigated elsewhere. The badge now clears when the tab starts loading a new page (or its URL
  changes) and the tooltip resets to the default.
- The ✓ tooltip now names the Firestore document that was written — `opportunities/<id>` — so
  hovering the badge shows exactly what was uploaded (the same id the desktop batch drafts).
- No other changes. See 1.3.7 … 1.3.0 below.

### Previous version — 1.3.7: fix the queued-write user id (the Google sub, not the Firebase localId)

- The sign-in stored `federatedId || localId` as the user id; for an account created with
  email/password and Google linked later that is the Firebase `localId`, but the Firestore
  rules key on the Google account id (the Firebase token's `identities['google.com'][0]`) —
  also the phone app's user id and the `personal_data` doc id — so every queue write was
  rejected with `Missing or insufficient permissions`. The extension now decodes the Firebase
  id_token and stores `identities['google.com'][0]` (fallback: the Google id_token's `sub`),
  so captures are accepted by the rules.
- No other changes. See 1.3.6 … 1.3.0 below.

### Previous version — 1.3.6: fix the Google sign-in; document that the redirect URI never changes

- Fixes the Google sign-in on both browsers: the Firebase Auth REST exchange
  (`accounts:signInWithIdp`) sent the extension's own origin (`moz-extension://<uuid>/`) as
  `requestUri`, which the API rejects with `INVALID_REQUEST_URI` — the sign-in died right after
  the account chooser. It now sends `http://localhost`, the conventional stand-in for
  extensions (probed against the REST endpoint: the `moz-extension://` form is rejected, the
  `http://localhost` form is accepted and proceeds to id_token verification).
- The Options page setup note now says the redirect URI is registered once — it is not an
  update-time value. On Firefox its label (`http://127.0.0.1/mozoauth2/<label>`) is the SHA-1 of
  the add-on ID in the manifest (`browser_specific_settings.gecko.id`), so it is the same whether
  the add-on is loaded unpackaged or installed signed, in any profile, across updates and
  reinstalls (verified against Firefox 158's `ext-identity.js`, which hashes the extension ID).
  On Chrome/Edge the URI (`https://<extension-id>.chromiumapp.org/`) is keyed to the extension
  ID: pinned by the signing key in `keys/` for the self-hosted CRX, assigned by the store for a
  store install, and derived from the folder path for an unpacked load — register the value the
  Options page shows for the copy you installed. A `redirect_uri_mismatch` at sign-in means the
  URI is not registered (exactly, no trailing slash) or sits on the wrong client.
- No other changes. See 1.3.5 … 1.3.0 below.

### Previous version — 1.3.5: the Options page shows the OAuth client ID next to the redirect URI

- The one-time setup now displays the OAuth 2.0 web client ID alongside the redirect URI, so the
  URI is registered on the right client (the one Firebase Auth's Google provider uses).
  A `redirect_uri_mismatch` at sign-in almost always means the URI landed on a different client
  (for example the desktop app's own web client) or the loaded extension predates 1.3.3 (which
  still used the desktop app's client ID).
- No other changes. See 1.3.4, 1.3.3, 1.3.2 and 1.3.0 below.

### Previous version — 1.3.4: drop the unnecessary Firebase authorized-domains step

- The one-time setup no longer includes Firebase → Authentication → Settings → *Authorized
  domains*. The extension signs in through the Firebase Auth **REST API** (`accounts:signInWithIdp`
  with the web API key), which does not consult that list — it is only enforced for the Firebase JS
  SDK (`auth/unauthorized-domain`) and the hosted auth handler, neither of which this add-on uses.
  The field also rejects `chrome-extension://…` / `moz-extension://…` entries ("A valid domain name
  is required"), and the Firefox extension origin changes per install, so the step could not work
  there anyway. The Options page's setup section now shows only the Google Cloud redirect URI.
- No other changes. See 1.3.3, 1.3.2 and 1.3.0 below.

### Previous version — 1.3.3: sign in with the Firebase-configured web client

- The Google sign-in now uses the OAuth 2.0 **web** client that Firebase Auth's Google provider is
  configured with (the "Web client ID" under Firebase console → Authentication → Sign-in method →
  Google → *Web SDK configuration* — the client `google-services.json` lists). The previous
  version used the desktop app's own web client: Google's step accepted it, but Firebase's
  `signInWithIdp` rejects id_tokens whose `aud` is any other client, so the sign-in failed at the
  Firebase step. The phone app's `webClientId` is switched to the same client.
- The Android OAuth client (`io.github.fdondi.letterwriter`) is not usable for extension sign-in
  (Google's extension flow requires a web client); it stays registered for the app's
  `google-services.json`.
- No other changes. See 1.3.2 and 1.3.0 below.

### Previous version — 1.3.2: fix the redirect property on both browsers

- Fixes the Google sign-in again (toolbar button, or Options → *Sign in with Google*): the call to
  `identity.launchWebAuthFlow` carried a redirect property — `redirect_uri` in 1.3.0, `redirectUri`
  in 1.3.1 — but neither browser's schema has one, so both rejected it with `Type error for
  parameter details (Unexpected property …)`. The call is now `{url, interactive}` only, on
  Chrome/Edge and Firefox alike; the redirect URI rides in the authorization URL's `redirect_uri`
  parameter (Chrome: the `chromiumapp.org` URL, Firefox: the `http://127.0.0.1/mozoauth2/…`
  loopback), which is what each browser intercepts.
- No other changes. See 1.3.1 and 1.3.0 below.

### Previous version — 1.3.1: fix the redirect property spelling

- 1.3.1 passed the redirect URI as `redirectUri` (camelCase) on Firefox — also rejected, the
  property does not exist in either browser's schema. Superseded by 1.3.2.

### Previous version — 1.3.0: queue straight to Firestore, auto-capture approved jobs, Firefox for Android via the app

What this add-on does: it sends the job posting you are looking at to Letter Writer, where a
desktop batch drafts a cover letter for it — the same job queue the phone app and the web app use.

New in 1.3.0:

- **Queueing without the local server.** With *Queue captured jobs directly in Firestore* on in
  Options (the default), sending a page writes the job straight to Firestore — the same write the
  phone app makes — so the browser never needs `localhost:8443`. Sign in once with Google in the
  Options page: it shows the redirect URI and the extension origin to register in the Google Cloud
  and Firebase consoles, and the account you are signed in as (with sign-out).
- **Auto-capture of approved jobs.** The extension keeps your approved jobs (refreshed on startup
  and every 15 minutes) and, when a page on one of their hosts finishes loading, checks whether it
  is one of them; if it is, the posting is attached automatically and the badge shows ✓ — no click.
  Only your own jobs are listed (the Firestore rules scope the queries to your account).
- **Firefox for Android.** Firefox on Android has no extension sign-in API (and there is no app
  server on the phone), so sending a page opens a `letterwriter://capture?url=…&text=…` link and the
  Letter Writer Android app queues the job itself — install the app and sign in there. Auto-capture
  stays off on Android; capture is manual (toolbar button or the page context menu).
- **Options page.** The signed-in account with sign-out, the one-time setup values, and the
  queue/stash toggle. With queueing off, the stash flow is unchanged: the page goes to the origin in
  Options (default `https://localhost:8443`) and the intake tab opens there.

## Notes to Reviewer

Version 1.3.9 names the queued job (title — company, page title as fallback) in the ✓ tooltip —
no Firestore internals — and shows the pipeline counts on the badge: the number of ready drafts
on the badge itself, `N queued · N running · N ready` in its tooltip. Version 1.3.8 clears the
toolbar badge when the tab navigates away. Version 1.3.7 stores the Google account id (the Firebase token's
`identities['google.com'][0]` — the phone app's user id and the `personal_data` doc id) instead
of the Firebase `localId`, so queue writes pass the rules (`Missing or insufficient permissions`
before). Version 1.3.6 fixes the sign-in's Firebase exchange — the `requestUri` sent to
`accounts:signInWithIdp` is now `http://localhost` (the API rejects the extension's
`moz-extension://` origin with `INVALID_REQUEST_URI`) — and the Options page documents that the
redirect URI never changes (register it once; on Firefox the label is the SHA-1 of the
manifest's `browser_specific_settings.gecko.id`, the same for unpackaged or signed installs).
Version 1.3.4 drops the unnecessary Firebase authorized-domains setup step (the sign-in is a
Firebase Auth REST call; that list is only enforced for the Firebase JS SDK and the hosted auth
handler). 1.3.3 switched the sign-in to the OAuth web client Firebase Auth's Google provider is
configured with (the `aud` of the Google id_token must match it; the Android client and the
desktop app's own web client are not accepted). 1.3.2 fixed the `launchWebAuthFlow` call shape
(`{url, interactive}` only — neither browser's schema has a redirect property; the redirect URI
rides in the authorization URL, verified against Firefox's `identity.json` schema and Chrome's
documented details). Everything below applies unchanged, and the test account exercises the fixed
sign-in.

**What this add-on does.** Letter Writer Capture sends the job-posting page you are viewing to
"Letter Writer", a personal job-application tool (web app + Android app + desktop batch;
`github.com/Fdondi/letter-writer`). The page (URL, title, visible text, HTML) becomes an
"opportunity" job in the user's own Firestore project (`gen-lang-client-0535858734`, database
`letter`, collection `opportunities`), where a desktop batch drafts a cover letter. There is no
third-party service: all writes go to the user's own Firebase project with the user's own Google
token or — in the stash flow — to a user-configured local origin (default `https://localhost:8443`,
the user's own web app).

**How to test.**

1. Install, open any http(s) page, click the toolbar button with queueing **off** (Options →
   uncheck *Queue captured jobs directly in Firestore*): it POSTs the page to
   `https://localhost:8443/api/job-capture/ingest/`. Without the local app running this fails and
   the badge shows `!` with the error — that is the expected behavior without the backend.
2. Queueing **on** (the default), not signed in: clicking the button starts the Google sign-in flow;
   the Options page shows the account once signed in.
3. Full flow: sign in with the test account below, open any page (a job posting on jobs.ch is
   typical), click the toolbar button → badge ✓ with the job's name in the tooltip (and the
   `N queued · N running · N ready` counts on hover). The write lands in Firestore project
   `gen-lang-client-0535858734`. The rules only accept known users: any other account gets a
   clear rules-rejection message on the badge (also logged to the console).
4. Auto-capture: approve a job in the app, open its page in the browser → the posting is attached
   automatically (badge ✓). On Firefox for Android, sending a page opens
   `letterwriter://capture?url=…&text=…` — the companion Android app queues the job; without the
   app installed the browser reports that no app handles the link.

**Test account** (Google sign-in for the Firestore queue flow; the account must be a known user in
the project's Firestore rules — a `personal_data/{google sub}` document):

- Username: `‹test-account@gmail.com›`
- Password: `‹test-account-password›`

**Permissions.**

- `activeTab`, `scripting`: read the page (URL, title, text, HTML) when the user clicks the toolbar
  button or the context menu, or when a page on an approved job's host finishes loading
  (auto-capture). No page is read unless the user sends it or it is an approved job's page.
- `host_permissions` for the job sites (`*.jobs.ch`, `*.jobup.ch`, `*.jobscout24.ch`,
  `*.linkedin.com`, `*.swissdevjobs.ch`): auto-capture on those pages.
  `optional_host_permissions` (`http://*/*`, `https://*/*`) are requested only when the user sets a
  custom app origin in Options. `firestore.googleapis.com`, `identitytoolkit.googleapis.com`,
  `securetoken.googleapis.com`: the direct-Firestore queue flow (REST API, no SDK) and the Google
  sign-in token exchange.
- `identity`: Google sign-in (`launchWebAuthFlow`) for the Firestore queue flow. The API does not
  exist on Firefox for Android — there the extension hands the page to the Android app instead.
- `storage`: Options settings and the Firebase Auth tokens (kept locally; sent only to Google's
  token endpoints).
- `alarms`: refresh the approved-jobs list every 15 minutes. `contextMenus`: the *Send job to
  Letter Writer* page menu. There is no `tabs` permission: the intake tab and the app handoff only
  use `tabs.create`, which needs none.

**Data collection** (declared in the manifest: `websiteActivity`, `websiteContent`). Collected: the
URL, title, visible text and HTML of the page the user sends (or of an approved job's page,
automatically). Sent to: the user's own Firestore project with the user's own Google token, or the
user-configured local origin in the stash flow. Not collected: browsing history beyond the current
page, credentials, or personal data beyond the account email shown in Options. No analytics, no
advertising, no selling or sharing — the data never leaves the user's own services.

**Source code.** No minifiers, no bundlers or code generators, no web template engines, no tools
that combine files, and no remote code: the packaged `.xpi` contains the same handwritten
JavaScript/HTML the repository holds (`package.sh` copies the files verbatim). Nothing is fetched or
executed at runtime beyond the WebExtension and Google/Firestore REST APIs listed above.
