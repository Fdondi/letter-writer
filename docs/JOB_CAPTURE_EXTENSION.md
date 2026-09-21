# Job capture browser extension

Send the current job-posting tab to Letter Writer. The extension grabs visible text and HTML, stashes them on the local app, then opens the app so extraction can run in your logged-in session (cleaned job description, company/title fields, competences, similar jobs).

The session cookie is `HttpOnly` and `SameSite=Lax`, so the extension cannot call authenticated APIs itself. Ingest is unauthenticated and local-only; process runs after you are signed in.

## Load unpacked (Chrome / Edge)

1. Start Letter Writer as usual (`https://localhost:8443`). Trust the mkcert certificate the same way you already do for the web app.
2. Open `chrome://extensions` (or `edge://extensions`), enable **Developer mode**.
3. **Load unpacked** and choose `extensions/job-capture/` in this repository.
4. Pin the toolbar button. On a job page, click it (or use the page context menu **Send job to Letter Writer**).

## Load in Firefox

1. Open `about:debugging#/runtime/this-firefox`.
2. **Load Temporary Add-on…** and select `extensions/job-capture/manifest.json`.
3. Firefox 109+ (Manifest V3). The manifest lists both `service_worker` (Chrome/Edge) and `scripts` (Firefox event page). Temporary add-ons are cleared when Firefox restarts.

## Options

Right-click the extension → **Options**. Default origin is `https://localhost:8443`. For the UI harness (`ui-harness/scripts/up.sh`) set it to `http://127.0.0.1:3010`. If you change it, the extension asks for host permission for that origin.

Firefox MV3 keeps host patterns in `host_permissions` only (not `permissions`). Temporary add-ons may not auto-grant those hosts; ingest still works when the API allows CORS from `moz-extension://`. Reload the add-on after a manifest change.

## Flow

1. Toolbar click captures `document.body.innerText` and `document.documentElement.outerHTML` (truncated).
2. `POST /api/job-capture/ingest/` stores a short-lived capture id (about 15 minutes).
3. A new tab opens `{origin}/?capture={id}`.
4. After Google login, the intake page peeks `GET /api/job-capture/{id}/` (fills Original URL immediately and shows that extraction is running), then `POST /api/job-capture/{id}/process/` and fills the rest of the form.

You still review intake before starting vendor or agentic flows. If ingest fails (app not running, untrusted cert, CORS), the toolbar badge shows `!` — hover for the error. The extension opens only the origin in Options (default `https://localhost:8443`). It does not fall back to the UI harness.

On 8443, `/process/` runs the same extraction pipeline as pasting a job ad (cleaned `job_text`, company/title fields, competences). Saved examples in `extensions/job-capture/examples/` have hostname-matched BeautifulSoup templates (`jobs.ch` search listing, `jobs.ch_inner` detail page, `jobs.ch_company` company profile, `swissdevjobs.ch`, `linkedin.com`). When the capture URL matches, the posting is parsed from JSON-LD or stable DOM selectors instead of sending the whole tab (search chrome, similar jobs) to the model. On jobs.ch search, the selected card is `a.cursor_pointer[id^="vacancy-link-"]` with `vacancy-serp-item-active` — that href is the Original URL, not the search JSON-LD (which can describe a different vacancy). Search vs clicked-through detail use different templates but the same vacancy panel: location from `[data-cy="info-location-link"]` (city under the logo if that link is missing), salary from `[data-cy="info-salary_estimate"]` (the CHF range, not the salary-teaser CTA). The estimate can differ slightly between search preview and the detail page; capture uses the figure on the tab you sent. Both vacancy templates also follow the company-profile CTA (`Voir le profil de l'entreprise` / DE/EN equivalents, path `/entreprises/{id-slug}/`) and put `[data-cy="company-description"]` into About the Company (`additional_company_info`). A failed fetch leaves that field empty. Unknown hosts still use the page-dump extractor. The harness origin skips the model; if a template matches it fills intake from that parse (including a company-profile fetch when the CTA is present), otherwise it dumps raw page text.
