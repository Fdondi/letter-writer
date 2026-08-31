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
3. Firefox 121+ is required (Manifest V3 service worker). Temporary add-ons are cleared when Firefox restarts.

## Options

Right-click the extension → **Options**. Default origin is `https://localhost:8443`. If you change it, the extension asks for host permission for that origin.

## Flow

1. Toolbar click captures `document.body.innerText` and `document.documentElement.outerHTML` (truncated).
2. `POST /api/job-capture/ingest/` stores a short-lived capture id (about 15 minutes).
3. A new tab opens `{origin}/?capture={id}`.
4. After Google login, the intake page calls `POST /api/job-capture/{id}/process/` and fills the form.

You still review intake before starting vendor or agentic flows. If ingest fails (app not running, untrusted cert), the toolbar badge shows `!` — hover for the error.
