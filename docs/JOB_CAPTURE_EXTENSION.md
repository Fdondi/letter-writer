# Job capture browser extension

Send the current job-posting tab to Letter Writer (queued for the desktop batch by default; see *Queuing jobs* below). The extension grabs visible text and HTML.

With queueing on, the extension writes the job **straight to Firestore** — the same write the phone app makes — so no local server is involved at all. It signs in with Google (the account the phone app uses) and the Firestore rules identify you by the Google account (`firebase/firestore.rules`: writes need a Google-linked token whose `sub` is your `user_id`). With queueing off, the page goes to the local app instead: the session cookie is `HttpOnly` and `SameSite=Lax`, so the extension cannot call authenticated APIs itself; ingest is unauthenticated and local-only and identifies you by the session cookie it sends, or by `OPPORTUNITY_OWNER_USER_ID` on the backend.

## Packaged install (no Developer mode)

An unpacked extension needs Chrome/Edge **Developer mode**, which an update can switch off again (Chrome's "Disable developer mode extensions?" prompt), and a Firefox *temporary* add-on dies with the browser restart. A packaged extension needs none of that:

```bash
extensions/job-capture/package.sh [download-base-url] [--sign]
```

The download-base-url is only used for the self-hosted CRX below (`update.xml` and the
force-install policy); the Firefox xpi and the store zip are built without it — omit the
argument and a placeholder stays in `update.xml`, unused.

builds in `extensions/job-capture/dist/`:

| Artifact | Install route |
|---|---|
| `letter-writer-capture-<version>.zip` | Chrome Web Store / Edge Add-ons upload (see below) |
| `letter-writer-capture-<version>.xpi` | Firefox: **unsigned** — release Firefox rejects it; sign on AMO first, then install the signed file (see below) |
| `letter-writer-capture-<version>.signed.xpi` | Firefox: AMO-signed (unlisted), from `package.sh --sign` — install this file as-is |
| `letter-writer-capture-<version>.crx` + `update.xml` | Self-hosted Chrome/Edge install without Developer mode (see below) |

The package holds only the runtime files (`examples/` HTML fixtures and the tests stay out). The CRX signing key is kept in `extensions/job-capture/keys/` (gitignored) — **back it up**: losing it changes the extension ID and every installed copy must be reinstalled. The script prints the extension ID and the force-install policy snippet.

**Chrome Web Store** (one-time $5 developer registration): Developer Dashboard → New item → upload the zip → *Unlisted* (only people with the link can install) → share the store link. **Edge Add-ons**: Partner Center → new extension → upload the zip (free registration).

**Self-hosted (your own machines, no store):** the CRX path needs Chrome/Chromium on the build machine — a `google-chrome`/`chromium` binary, or the `com.google.Chrome` / `org.chromium.Chromium` Flatpak (`package.sh` runs it through `flatpak run` with a one-run `--filesystem=home` grant, so the sandbox can read the staging dir; the repo must be under your home directory). `package.sh` skips the CRX with a note when no Chrome is found. Host the `.crx` and `update.xml` over HTTPS at `download-base-url`, then force-install with the `ExtensionInstallForcelist` policy — Linux, `/etc/opt/chrome/policies/managed/letter-writer.json` (Chrome) or `/etc/opt/edge/policies/managed/` (Edge):

```json
{"ExtensionInstallForcelist": ["<extension-id>;https://<download-base-url>/update.xml"]}
```

The extension ID is derived from the signing key; `package.sh` prints it — verify it on `chrome://extensions` → Details after the first install. Policy-installed extensions cannot be disabled or removed by the user and survive updates without Developer mode.

**Firefox:** release Firefox only installs **AMO-signed** add-ons — there is no setting that changes this. The unsigned `.xpi` from `package.sh` is the *input* to signing, not an installable file: installing it fails with `ERROR_SIGNEDSTATE_REQUIRED: The addon must be signed and isn't.` Setting `xpinstall.signatures.required=false` in `about:config` (or via `user.js`, or the enterprise `Preferences` policy) does **not** work in release builds — the requirement is a hard-coded constant there (`MOZ_REQUIRE_SIGNING`, verified in Firefox 158; only ESR / Developer Edition / Nightly / unbranded builds honor the pref). Verified on Firefox 158: unsigned rejected, temporary load (`about:debugging`) works but dies on restart, an AMO-signed xpi installs permanently.

To get the installable file, sign the `.xpi` on AMO as *unlisted* (it is never published, no review):

- **Manual:** upload the `.xpi` at [addons.mozilla.org](https://addons.mozilla.org) → Developer Hub → *Submit a New Add-on* → distribution *unlisted* → download the signed `.xpi`.
- **CLI:** `./package.sh --sign` runs `web-ext sign --channel unlisted` and writes `dist/letter-writer-capture-<version>.signed.xpi`. It needs AMO API credentials in `WEB_EXT_API_KEY` / `WEB_EXT_API_SECRET` (addons.mozilla.org → Developer Hub → *Manage API Keys*): the script loads them from an `.env` file next to itself when present (gitignored; variables already set in the environment win), or pass them inline.

The texts for the AMO form — **Version notes** and **Notes to Reviewer** (permissions, data collection, source-code answers, how to test, test account) — are ready to paste in `extensions/job-capture/amo-submission.md`.

Then install the **signed** file: `about:addons` → ⋮ → *Install Add-on From File…* → pick the `.signed.xpi`. It installs permanently — nothing cleared on restart, no `about:config` switch. Firefox for Android installs the same signed file the same way. The manifest lists both `service_worker` (Chrome/Edge) and `scripts` (Firefox event page); Firefox 140+ desktop / 142+ Android (Manifest V3). The package passes `addons-linter` with 0 errors. `browser_specific_settings.gecko.data_collection_permissions` declares the extension's data collection (`websiteActivity`, `websiteContent` — the page URL, title, text and HTML it sends to your own Letter Writer server); AMO requires this key for new extensions, and Firefox 140+ shows it in the install-time consent prompt.

## Load unpacked (development)

1. Start Letter Writer as usual (`https://localhost:8443`). Trust the mkcert certificate the same way you already do for the web app.
2. Open `chrome://extensions` (or `edge://extensions`), enable **Developer mode**.
3. **Load unpacked** and choose `extensions/job-capture/` in this repository.
4. Pin the toolbar button. On a job page, click it (or use the page context menu **Send job to Letter Writer**).

Firefox: `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → `extensions/job-capture/manifest.json`. Temporary add-ons are cleared when Firefox restarts — use the packaged install above for a permanent one.

## Options

Right-click the extension → **Options**.

**Queue jobs (direct to Firestore)** is the top section: a **Sign in with Google** button shows the current account (or prompts to sign in). Sign in once with the same Google account the phone app uses — the Firestore rules key on that account's `sub`. Under *One-time setup* the page shows the two values to register (see below). The **Queue captured jobs directly in Firestore** checkbox (default on) switches between the queued flow below and the stash flow. On Firefox for Android (no sign-in API) the section says so instead and points at the app handoff below; the sign-in buttons are hidden, the queue checkbox is locked on and the stash origin is disabled — the handoff only runs in the queue path, and the stash flow has no server to talk to on a phone.

**Stash flow (app origin)**: with queueing off, captured pages are sent to this origin. Default is `https://localhost:8443`. For the UI harness (`ui-harness/scripts/up.sh`) set it to `http://127.0.0.1:3010`. If you change it, the extension asks for host permission for that origin.

One-time setup for the direct queue flow (the Options page shows the exact values for your browser):

1. **Google Cloud Console** → project `gen-lang-client-0535858734` → APIs & Services → Credentials → the OAuth 2.0 **web** client that Firebase Auth's Google provider is configured with — the "Web client ID" under Firebase console → Authentication → Sign-in method → Google → *Web SDK configuration* (the same client `app/app/google-services.json` lists; **not** the Android client for `io.github.fdondi.letterwriter` and not the desktop app's own web client — Firebase's `signInWithIdp` rejects id_tokens whose `aud` is any other client) → add the redirect URI the Options page shows (`https://<extension-id>.chromiumapp.org/` on Chrome, the `http://127.0.0.1/mozoauth2/…` loopback URI on Firefox). Leave *Use this client for an AI-powered agent* unchecked — that option designates a client for AI agents and MCP tool execution (Google keeps agentic client IDs separate from login clients); this one is for user sign-in.
2. Back in Options, click **Sign in with Google** and pick the phone app's account.

No Firebase console step is needed: the extension signs in through the Firebase Auth **REST API** (`accounts:signInWithIdp` with the web API key), not the Firebase JS SDK, and the authorized-domains list is only enforced for SDK sign-in and the hosted auth handler (`auth/unauthorized-domain`) — neither applies to REST calls. Entering `chrome-extension://<id>/` or `moz-extension://<uuid>/` there is rejected anyway ("A valid domain name is required"), and the Firefox origin changes per install.

The redirect URI never changes — register it once. On Firefox its label (`http://127.0.0.1/mozoauth2/<label>`) is the SHA-1 of the add-on ID in the manifest (`browser_specific_settings.gecko.id`), so it is the same whether the add-on is loaded unpackaged or installed signed, in any profile, across updates and reinstalls (verified in Firefox 158's `ext-identity.js`, which hashes the extension ID). On Chrome/Edge the URI (`https://<extension-id>.chromiumapp.org/`) is keyed to the extension ID: pinned by the signing key in `keys/` for the self-hosted CRX, assigned by the store for a store install, and derived from the folder path for an unpacked load — register the value the Options page shows for the copy you installed. If sign-in fails with `redirect_uri_mismatch`, the URI is not registered (exactly, no trailing slash) or sits on the wrong OAuth client.

Firefox MV3 keeps host patterns in `host_permissions` only (not `permissions`). Packaged add-ons grant `host_permissions` at install; reload the add-on after a manifest change.

## Flow (queueing off, or when the backend stashes)

1. Toolbar click captures `document.body.innerText` and `document.documentElement.outerHTML` (truncated).
2. `POST /api/job-capture/ingest/` stores a short-lived capture id (about 15 minutes).
3. A new tab opens `{origin}/?capture={id}`.
4. After Google login, the intake page peeks `GET /api/job-capture/{id}/` (fills Original URL immediately and shows that extraction is running), then `POST /api/job-capture/{id}/process/` and fills the rest of the form.

You still review intake before starting vendor or agentic flows. If ingest fails (app not running, untrusted cert, CORS), the toolbar badge shows `!` — hover for the error. The extension opens only the origin in Options (default `https://localhost:8443`). It does not fall back to the UI harness.

On 8443, `/process/` runs the same extraction pipeline as pasting a job ad (cleaned `job_text`, company/title fields, competences). Saved examples in `extensions/job-capture/examples/` have hostname-matched BeautifulSoup templates (`jobs.ch` search listing, `jobs.ch_inner` detail page, `jobs.ch_company` company profile, `swissdevjobs.ch`, `linkedin.com`). When the capture URL matches, the posting is parsed from JSON-LD or stable DOM selectors instead of sending the whole tab (search chrome, similar jobs) to the model. On jobs.ch search, the selected card is `a.cursor_pointer[id^="vacancy-link-"]` with `vacancy-serp-item-active` — that href is the Original URL, not the search JSON-LD (which can describe a different vacancy). Search vs clicked-through detail use different templates but the same vacancy panel: location from `[data-cy="info-location-link"]` (city under the logo if that link is missing), salary from `[data-cy="info-salary_estimate"]` (the CHF range, not the salary-teaser CTA). The estimate can differ slightly between search preview and the detail page; capture uses the figure on the tab you sent. The server never fetches pages itself (JobCloud bans automated access): About the Company (`additional_company_info`) is filled only when you capture a company profile page (`jobs.ch_company` template, `[data-cy="company-description"]`). Unknown hosts still use the page-dump extractor. The harness origin skips the model; if a template matches it fills intake from that parse, otherwise it dumps raw page text.

## Job pipeline (extension 1.1.0, direct Firestore from 1.3.0)

When a captured page is the posting of a job you approved under **Jobs**, the extension attaches it to that job (status `captured`, drafted by the next batch run) and shows ✓ instead of opening an intake tab. The extension also does this on its own: it keeps your approved jobs (their hosts, refreshed every 15 minutes) and, when a page on one of those hosts loads, checks whether it is one of them; only then is the page read and sent.

From 1.3.0 the approved-jobs list and the per-URL check come straight from Firestore (queries on `opportunities` filtered by your `user_id` — the rules only allow listing your own jobs), so auto-capture works signed in, without the backend. When signed out it falls back to the server endpoints (`/api/job-capture/pending/`, `?url=`), which need the signed-in session or `OPPORTUNITY_OWNER_USER_ID` on the backend; that also needs the job-site host permissions in the manifest (reload the add-on). Auto-capture is desktop-only: on browsers without the `identity` API (Firefox for Android) there is no pending list and no server to ask, so no page is ever read automatically — capture is manual there (see *Firefox for Android* below). Tests: `node --test extensions/job-capture/pending.test.mjs`. See `docs/OPPORTUNITY_PIPELINE.md`.

## Queuing jobs (extension 1.2.0 server-side, direct Firestore from 1.3.0)

With **Queue captured jobs directly in Firestore** on in Options (the default), sending a page writes the job straight to Firestore — the same write the phone app makes (`extensions/job-capture/pipeline.js` is a port of `letter_writer/opportunity_store.py`, verified against the shared fixture `letter_writer/tests/fixtures/opportunity_keys.json`): a new job is created `captured` with the page's text, an existing job with the same link gets the text (unless the desktop is drafting it or already did). The desktop drafts it on the next `batch run-captured`; the toolbar badge shows ✓ with the job's message and no intake tab opens. The write is a read-plan-commit through the Firestore REST API (`firestore.js`, no SDK): an atomic create-if-absent, or an update limited to the fields the rules allow. A rules rejection while the desktop is drafting reports "The desktop is drafting this job right now." instead of rewriting it.

No local server is needed — the browser needs no `localhost:8443` at all. What it needs is the Google sign-in from Options (the rules only accept writes from your Google-linked account). Fallbacks, in order:

- Not signed in: a manual capture prompts the sign-in flow; auto-capture skips silently (on desktop; on Android it queues through the app, see below).
- Sign-in fails or is cancelled: the badge shows `!` with a message pointing at Options — it does **not** fall back to `localhost:8443`.
- No `identity` API (Firefox for Android): there is no Firestore access and no app server on the phone, so the page is handed to the **Letter Writer app** over the `letterwriter://capture?url=…&text=…` URL scheme — the app queues the job itself. The badge shows `→`. See *Firefox for Android* below.

1.2.0 queued through the backend instead: ingest (`POST /api/job-capture/ingest/` with `queue:true`) created the job server-side. That needed the signed-in session (`credentials: "include"`) or `OPPORTUNITY_OWNER_USER_ID` on the backend, and without either it stashed the page and opened the intake tab (the response says so in `note`). The ingest endpoint stays for the stash flow and the harness.

With the option off, the flow is unchanged: stash, open `{origin}/?capture={id}`, review the extraction.

The extension's Firestore path is covered end to end against the emulator with the real rules: `scripts/firebase/test_rules.sh` runs `firebase/tests/extension-firestore.test.mjs` (queue writes, drafting guard, own-jobs-only queries) next to `rules.test.mjs`.

## Firefox for Android (no sign-in API: hand off to the app)

Firefox for Android has no `identity` API, so the extension can neither sign in nor write Firestore itself — and there is no app server on the phone to POST to either (the point of the direct flow is to bypass `localhost:8443`). Capturing a page therefore opens `letterwriter://capture?url=…&text=…`, and the **Letter Writer app** queues the job: it is already signed in and writes Firestore exactly like the share flow does (`capture.via` is `extension`, a value the pipeline plan reserves for this).

1. Install the app and sign in with the same Google account the desktop uses.
2. In Firefox, open a job page and tap the extension's toolbar button (or the page context menu **Send job to Letter Writer**).
3. The app opens without UI, queues the job, and toasts the outcome; the extension's badge shows `→` ("handed to the Letter Writer app"). If the app is not signed in, the toast says to sign in there first and nothing is queued.

The posting text rides along only while the encoded URL stays small (100 000 characters); a bigger posting is handed over as a bare URL and the app downloads the page itself (`JobPageFetcher`), like a shared link. Auto-capture stays off — with no pending list and no server to ask, the extension never reads a page on its own. On desktop Firefox the flow is the same as on Chrome once signed in; only Android lacks the API.

App side: `QueueCaptureActivity` (manifest intent filter `VIEW` `letterwriter://capture`, translucent, no UI) parses the query with `parseExtensionHandoff` (`app/app/src/main/java/io/github/fdondi/letterwriter/ExtensionHandoff.kt` — pure JVM, unit-tested in `ExtensionHandoffTest.kt`) and queues through `graph.opportunities.capture`, or fetches the page when the URL carried no text.
