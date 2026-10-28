# Letter Writer

Writes cover letters tailored to a job posting from your CV and your previous letters. Several LLM
vendors draft side by side; automatic checks comment on each draft, you answer or approve the
comments, the drafts are rewritten, and you assemble the final letter from the best paragraphs.

It runs as a web app (Docker, on this computer), an Android app, and a browser extension that
captures job postings. The **opportunity pipeline** drafts letters on this computer for the jobs you
send from the phone, the extension or the web app.

The phone never connects to this computer: the Android app and the desktop only read and write
Firestore, at their own pace. No VPN or open port is needed.

## How it fits together

| Part | What it is | Where |
|---|---|---|
| Backend | FastAPI: extraction, research, drafting, feedback, saving | `letter_writer/` (logic), `letter_writer_server/` (API); container `backend`, port 8000 |
| Web app | React; served by nginx over HTTPS | `letter_writer_web/`; container `frontend`, https://localhost:8443 (8442 redirects) |
| Firestore (database `letter`) | All data: profile and CV (`personal_data`), previous letters with their embeddings (`documents`), company research cache (`companies`), letter feedback (`feedbacks`, `phase_draft_feedback`), the job pipeline (`opportunities`) | Google Cloud; the backend uses `gcloud-credentials.json` |
| Redis | Pending cost records before they reach BigQuery | container `redis`, port 6379 |
| BigQuery | Cost history and spending limits | Google Cloud |
| Ollaya ("Laya") | Local decision model that scores feedback and similar letters | container `ollaya`, `127.0.0.1:11435` |
| Event-log admin | Inspects saved application event logs | container `event-log-admin`, port 8444 |
| LLM vendors | OpenAI, Anthropic, Gemini, Mistral, Grok, DeepSeek, a local OpenAI-compatible server, and Claude Code (subscription, batch only) | models per vendor and role in `letter_writer/clients/*.json`, per-phase overrides in Settings |
| Android app | Kotlin/Compose; talks to Firestore and the vendors directly | `app/` |
| Browser extension | Queues the open job posting for the desktop batch, like the phone app | `extensions/job-capture/` (`package.sh` builds the store/self-hosted packages), docs in `docs/JOB_CAPTURE_EXTENSION.md` |
| Opportunity pipeline | Captured postings → drafted letters on a timer; the app combines them | `letter_writer/batch.py`, see below; mail reading experimental in `experimental/email/` |

Similar letters are found by vector search over `documents` (OpenAI `text-embedding-3-small`);
there is no separate vector database.

## Setup

### 1. Configuration

Put these in `.env` in the repository root (Docker Compose and the Python code both read it):

- `OPENAI_API_KEY` — OpenAI models, and embeddings for similar-letter search
- `ANTHROPIC_API_KEY` — Anthropic models
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) — Gemini models
- `MISTRAL_API_KEY`, `XAI_API_KEY` (Grok), `DEEPSEEK_API_KEY` — optional vendors
- `GOOGLE_TRANSLATE_API_KEY` — translation in the assembly stage
- `GOOGLE_CLOUD_PROJECT`, `FIRESTORE_PROJECT_ID`, `FIRESTORE_DATABASE=letter` — Firestore
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_SECRET`, `APP_SECRET_KEY` — sign-in to the web app
- `USER_MONTHLY_LIMIT_USD`, `USER_DAILY_LIMIT_USD` — spending limits for API calls
- optional `LANGSMITH_*` — tracing

The Google service-account key goes in `gcloud-credentials.json` (repository root; gitignored).

Do not put `OLLAYA_BASE_URL` in `.env`: Compose copies `.env` values into the backend container,
where Ollaya is `http://ollaya:11435`, not `127.0.0.1`.

### Local LLM (LM Studio or OpenAI-compatible server)

The **local** model vendor talks to an OpenAI-compatible HTTP API (for example [LM Studio](https://lmstudio.ai/) with the local server enabled). No cloud API key is required; the machine running the server must expose the API (default port **1234**).

Environment variables (optional):

| Variable | Purpose |
|----------|---------|
| `LOCAL_LLM_BASE_URL` | Full base URL including `/v1`, e.g. `http://localhost:1234/v1`. If unset, the app uses `http://localhost:1234/v1` when running on the host, and `http://host.docker.internal:1234/v1` when running **inside a container** so the backend can reach LM Studio on the **host** (Docker Desktop on Windows/macOS resolves `host.docker.internal` to the host). |
| `LOCAL_LLM_API_KEY` | Sent as the API key; LM Studio often accepts any non-empty value. Defaults to `lm-studio`. |
| `LOCAL_GPU_WATTS_AT_100` | **Optional but required for non-zero local cost tracking.** GPU power draw in watts when the GPU is at 100% utilization (e.g. your card’s typical load power). Used with wall-clock inference time and `LOCAL_ENERGY_PRICE_PER_KWH`. |
| `LOCAL_ENERGY_PRICE_PER_KWH` | **Optional but required for non-zero local cost tracking.** Your local electricity price per kWh (same currency unit as other API costs in the app, typically USD/kWh). |

**Local cost model:** Each local LLM call is charged as \((\text{elapsed hours}) \times (\text{watts}/1000) \times \text{price per kWh}\), assuming the GPU runs at full load for the whole request. Token-based rates in `letter_writer/clients/local.json` are not used for billing. If either `LOCAL_GPU_WATTS_AT_100` or `LOCAL_ENERGY_PRICE_PER_KWH` is missing or invalid, recorded cost stays **0** (tokens are still counted).

**Docker / Podman:** Inside a container, `localhost` is the container itself. The backend defaults to `http://host.docker.internal:1234/v1` when it detects a container (`/.dockerenv` on Docker, `/run/.containerenv` on Podman) or when `docker-compose.yml` sets that URL. `extra_hosts: host.docker.internal:host-gateway` maps that hostname to the host on Linux. **LM Studio must listen on the host’s non-loopback address** (e.g. **0.0.0.0**, not **127.0.0.1 only**) and be running, or you still get connection refused even with correct DNS.

`docker-compose.yml` passes `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_API_KEY`, `LOCAL_GPU_WATTS_AT_100`, and `LOCAL_ENERGY_PRICE_PER_KWH` through from the host environment / `.env`.

### CV Source

For the web application, CV content is loaded from Firestore (`cv_revisions`) and stored in session state.

- `docker-compose.yml` no longer mounts `cv-external` or sets `CV_PATH`.
- There is no implicit file fallback in Docker runtime.
- Upload/edit CV content via the Personal Data API/UI.

CLI usage still supports file-based CV input, but it must be provided explicitly with `--cv`.

### Source data

Job offers and correspective letters need to be either in different folders, or have different suffixes (be it file extension or name).
All the pairs which have the same name once the suffix is removed, are considered to be a valid data point.

In case the text the lettter is within boilerplate (for example, a `.tex` source file), it's possible to instruct to ignore before and after a given keyword.

### 2. Run with Docker

```bash
docker compose up -d          # backend, frontend, redis, ollaya, event-log-admin
docker compose up -d --build  # after code changes
docker compose logs backend   # when something does not start
```

Open https://localhost:8443 (the certificate in `certs/` is a local mkcert one; trust it once).
The backend waits for Ollaya to report healthy; the first start downloads the Laya model and can take several minutes.

### 3. Load your previous letters

Similar-letter search needs your past job offers and letters in Firestore (`documents`). Pairs are
files with the same name once the suffix is removed:

```bash
docker compose exec backend python -m letter_writer refresh \
  --jobs-source-folder jobs --jobs-source-suffix .txt \
  --letters-source-folder letters --letters-source-suffix .txt
```

Every letter you save in the app is added to the same collection.

### Running without Docker

```bash
pip install -r requirements.txt
python -m uvicorn letter_writer_server.main:app --host 0.0.0.0 --port 8000
cd letter_writer_web && npm install && npm run dev   # http://localhost:5173, proxies /api to :8000
```

## Opportunity pipeline (job posting → drafted letters → your letter)

Design and reasoning: `OPPORTUNITY_PIPELINE_PLAN.md`; component map: `docs/OPPORTUNITY_PIPELINE.md`.
Reading job alerts and application replies from Gmail is experimental and not used:
`experimental/email/README.md`.

### How it works

1. **Send a job.** On the phone, share a posting (text or link) to Letter Writer, or paste it, pick
   the vendors (all are selected to start with; Anthropic runs as Claude Code on your subscription
   on the desktop and through its API on the phone), how many times the desktop should **comment and
   rewrite** each draft (0, 1 or 2; default 1) and whether it should **comment the last version**
   (default on), and choose **Send to the desktop**. In the browser, the extension queues the open posting
   (Options page: off opens the intake tab instead, for interactive extraction); in the web
   app, **Jobs → Add a job by hand**. The job is saved in Firestore as **captured** (a bare link waits
   as **needs text** until you add the posting text).
2. **The desktop rates it, then drafts the best ones.** Every 3 hours a timer on this computer runs
   `letter_writer.batch daemon --once`, one wake of the pipeline:
   - every **captured** job is extracted (company, title, competences, similar letters) and moved
     to **rated** with its fit score — the weighted competence match the intake page shows — and
     the extraction is stored, so drafting pays for it once;
   - only the best **rated** jobs are drafted, up to a rolling 24-hour cap (default 5 letters;
     `LW_DAILY_CAP` changes it): extraction, one company research, then per vendor: plan →
     draft → (comments → rewrite) as many times as the job asks → comments on the last version if
     asked. Vendors are the job's own list; a job without one (extension, web) uses every vendor:
     the desktop has no defaults. In the batch Anthropic is always Claude Code, never the API. A
     drafted job becomes **ready**, or **failed** with each vendor's error;
   - a **rated** job that was not drafted within 3 days (`LW_ARCHIVE_DAYS`) is **archived** and
     left alone. A wake with nothing captured only reads Firestore.
   The wake interval is `LW_WAKE_INTERVAL_HOURS` (default 3). `run-captured` remains as a manual
   override: it drafts captured jobs right now, ignoring the rating and the cap.
3. **You steer it.** In the app (**Jobs → Rated**) you see each job's fit score with its matched
   competences and gaps, and can change the rating — your rating decides which jobs are drafted
   first. **Jobs → Archived** shows the jobs that waited too long; **Re-enable** brings one back,
   optionally with a new fit estimate. On the phone the same queues are the **Rated** and **Done**
   (archived) tabs of the job pipeline. Skipping works from any of these states.
4. **You finish it.** In the app (**Job pipeline → Ready → Open the drafts**) the **Final** tab shows
   each vendor's letter paragraph by paragraph, with its comments on the paragraph they quote
   (highlighted) or on the whole letter. Add a paragraph as it is, or **Redraft** it right away with
   the comments you keep ticked, your answers to questions and a note: that call goes straight from
   the phone to the vendor's API (a paragraph Claude Code wrote goes to the Anthropic API: same
   vendor, realtime). Nothing has to
   be approved first. Combine paragraphs from any vendors, save; saving marks the job **done**. The
   web app (**Jobs → Ready → Craft letter**) jumps straight to assembling the final letter from the
   drafts.

The phone and the desktop never connect to each other; both only read and write Firestore.

### One-time setup (this Linux machine)

1. **Python environment for the batch** (host, not Docker; the `claude` CLI and its login live here):
   ```bash
   uv venv .venv --python 3.13 && VIRTUAL_ENV=.venv uv pip install -r requirements.txt
   ```
2. **Your account id.** The batch acts for one Google account, identified by its `sub`:
   ```bash
   .venv/bin/python -m letter_writer.batch users
   ```
   lists the profiles in Firestore (yours has your CV revisions); in the web app, hover your name in
   the header. Add it to `.env`:
   ```bash
   echo 'LW_USER_ID=<your sub>' >> .env
   ```
   With a single profile in Firestore this step can be skipped.
3. **Check the connection:** `.venv/bin/python -m letter_writer.batch status`
   (the batch uses `gcloud-credentials.json` and Ollaya on `127.0.0.1:11435` by itself).
4. **Restart Compose** so Ollaya is published on the host (feedback scoring): `docker compose up -d`.
   Without it drafting still works, with a warning that comments were not scored.
5. **Firestore rules** that let the phone save jobs and read drafts:
   ```bash
   (cd firebase && firebase deploy --only firestore --project gen-lang-client-0535858734)
   ```
6. **Extension sign-in (queueing).** From version 1.3.0 the extension queues jobs straight in
   Firestore like the phone app — no backend involved. Open the extension's Options and click
   **Sign in with Google** with the same account the phone app uses (one-time: register the redirect
   URI shown there in the Google Cloud console — on the web
   client Firebase Auth's Google provider uses, i.e. the "Web client ID" under Authentication →
   Sign-in method → Google → *Web SDK configuration*, the same client `google-services.json`
   lists; not the Android client and not the desktop app's own web client; leave *Use this client
   for an AI-powered agent* unchecked — that designates a client for agents calling Google APIs
   (MCP), not for user sign-in). Firefox for
   Android has no sign-in API (and no app server on the phone): there the extension hands the page
   to the **Android app** over a `letterwriter://capture?…` link — install the app and sign in there,
   and it queues the job itself (`docs/JOB_CAPTURE_EXTENSION.md` → *Firefox for Android*).
7. **Extension:** reload it (version 1.3.9; from 1.3.0 it queues sent pages directly in Firestore
   by default — Options page to turn it off; 1.1.0 asked for the job sites' host permissions;
   1.3.1/1.3.2 fixed the Google sign-in call on Firefox and Chrome, 1.3.3 signs in with the
   Firebase-configured web client, 1.3.4 drops the unnecessary Firebase authorized-domains step,
   1.3.5 shows the OAuth client ID next to the redirect URI in the setup, 1.3.6 fixes the
   Firebase sign-in exchange (INVALID_REQUEST_URI) and documents that the redirect URI never
   changes — register it once, 1.3.7 stores the Google sub as the queued-write user id (not the
   Firebase localId), 1.3.8 clears the badge when the page changes, 1.3.9 names the job (title —
   company) in the ✓ tooltip and shows the pipeline counts (queued · running · ready) on the badge).
8. **The timer** (every 15 minutes; a run missed while the machine is off or asleep happens on wake):
   ```bash
   scripts/opportunities/install.sh timer
   systemctl --user enable --now letter-opportunities.timer
   ```
   Log: `temp/opportunities/routine.log`. Stop with `systemctl --user disable --now letter-opportunities.timer`.

By hand instead of the timer: `.venv/bin/python -m letter_writer.batch run-captured`, or
`scripts/opportunities/install.sh skill` and then `/letter-opportunities` in Claude Code started in
this folder. On Claude Code Desktop (Windows/macOS), a scheduled task with
`docs/routines/letter-opportunities/SKILL.md` does the same.

### Day to day

- **Jobs** (web: header button or `/opportunities`; Android: **Job pipeline**): send jobs, follow
  them through Queued (sent) → Running (the desktop is drafting it: step and vendors done so far)
  → Ready, craft the final letter from the drafts.
- **Failed** jobs show each vendor's error; **Retry** queues them again (`batch retry <id>`). A retry
  keeps every draft that already succeeded for the same posting text and drafts only the missing
  vendors; each draft is saved as soon as its vendor finishes, so a run that dies halfway loses
  nothing that was done. New posting text drafts everything again.
- By hand: `.venv/bin/python -m letter_writer.batch seed --url <link> --text-file posting.txt`
  adds a captured job; `batch run-captured --max-jobs 1` drafts it now.
- `batch run-captured --vendors claude_code,openai,gemini --rewrite-rounds 0 --no-final-feedback`
  fills in vendors and settings for jobs that came without them; a job's own choices win.

### Costs

API vendors count toward the spending limits (checked before each job; over the limit only
`claude_code` runs). `claude_code` uses your Claude subscription; its estimated cost is stored on the
job as `cost_subscription_estimate_usd` and is not API spend. Extraction uses the extraction vendor
set in your profile.

### Troubleshooting

| Symptom | Where to look |
|---|---|
| Job stays Queued | Is the timer running (`systemctl --user list-timers`)? `temp/opportunities/routine.log` |
| Job stuck in Running | `temp/opportunities/routine.log`; a crashed run's job is taken over after its 2-hour lease, keeping the drafts it finished |
| Job failed | the error per vendor on the job; `claude_code`: is `claude` logged in on this machine? |
| "Set LW_USER_ID" | setup step 2 |
| The phone cannot save a job | setup step 5 (rules) |
| Extension never shows ✓ | sign in with Google in the extension's Options (queueing on); on Firefox for Android the badge shows `→`: install the Android app, sign in there, and it queues the job (setup step 6) |
| Sign-in fails with `redirect_uri_mismatch` | the redirect URI never changes — register the one shown on the extension's Options page (exactly, no trailing slash) on the OAuth client shown there; a mismatch means it is not registered or is on the wrong client |
| Sign-in fails with `INVALID_REQUEST_URI` | the loaded extension predates 1.3.6 (it sent the extension origin as the Firebase requestUri) — reload 1.3.6+ |
| Extension capture fails with "Missing or insufficient permissions" | the rules key on the Google sub (`107281079540942343648`-style), not the Firebase uid: from 1.3.7 the extension stores the Google sub as the user id — reload 1.3.7+ and check `lwAuth.userId` in the extension storage (about:debugging → Inspect → Storage). The account also needs a `personal_data/{sub}` profile (created by the desktop backend; `LW_USER_ID` in `.env` is the sub) |

## Android app

```bash
cd app && ./gradlew installDebug        # phone connected over adb; or assembleRelease for an APK
```

Firebase setup for a new project: `scripts/firebase/setup_android_firebase.sh`.

**Demo mode** (no sign-in): tap **Try the demo** on the sign-in screen. It is a made-up account
with sample jobs (one per pipeline tab, a ready one with desktop drafts) and letters; every model
reply is canned and nothing leaves the phone. Each visit starts afresh; your account and your real
letter in progress are not touched. **Leave demo** in the banner returns to where you were (your
account, or the sign-in screen). It works in debug and release builds. From adb:
`adb shell am start -n io.github.fdondi.letterwriter/.MainActivity --ez io.github.fdondi.letterwriter.DEMO true`.

Smoke test (demo mode; fails on any crash): `python3 scripts/android/demo_smoke.py [--serial <device>]`.
It is safe on your own phone: demo data is separate, starts afresh, and the app is left as it was.
On an emulator add `--apk app/app/build/outputs/apk/debug/app-debug.apk --fresh` (installs, clears
the app's data, grants the notification permission). Run emulators with the real GPU and a memory
cap, e.g. `systemd-run --user --scope -p MemoryMax=4G emulator -avd <avd> -gpu host`: the
software-GPU modes crash or leak on this machine.

## Command line

`python -m letter_writer <command>` (options can also be set as environment variables):

- `refresh` — loads previous job offers and letters into Firestore (`documents`).
  `--jobs-source-folder`, `--jobs-source-suffix` (default `.txt`), `--letters-source-folder`,
  `--letters-source-suffix` (default `.tex`), `--letters-ignore-until` / `--letters-ignore-after`
  (strip boilerplate such as `\makelettertitle` … `\closing`), `--negative-letters-source-folder`,
  `--negative-letters-source-suffix`, `--clear`.
- `process_job <path>` — writes a letter without the web app. `--cv <path>` (required),
  `--company-name`, `--out`, `--model-vendor` (default: every vendor except `claude_code`), `--refine/--no-refine`,
  `--fancy`.

`python -m letter_writer.batch --help` lists the pipeline commands. Traces of model calls are saved
under `trace/`.

## How a letter is written

1. **Extraction.** The posting is cleaned (site templates for jobs.ch, LinkedIn, swissdevjobs) and an
   LLM extracts company, title, location, language, contact, competences with how critical each is,
   and the problem the hire should solve. Your CV is graded against each competence.
2. **Similar letters.** The 7 most similar previous job offers come from vector search; an LLM and the
   Laya decision model re-score them; the top 3 are the examples.
3. **Company research.** A web-search model writes a report on the company (and the contact person);
   reports are cached in `companies` and reused for 6 months.
4. **Plan** (optional). Each vendor plans the letter's argument, following your structure instructions.
5. **Draft.** Each vendor writes a letter from the CV, the examples, the research, the posting and the
   plan, following your style instructions, and lists the posting's requirements the CV does not meet.
6. **Feedback checks.** Seven checks comment on each draft: style instructions, accuracy against the CV,
   precision against the posting, company fit, goal fit (does it solve the hire's problem), your voice
   (compared with your previous letters), and human tone. A review pass merges and filters the
   comments, and Laya scores them. Comments that need information from you become questions.
7. **Rewrite.** Each draft is rewritten with the comments you approved and the answers you gave
   (optionally a fancier style pass).
8. **Assembly.** You pick paragraphs from the vendors' letters, translate if needed, and save; saving
   adds the letter to your examples and records which vendor's text you kept.

Models per vendor and step are in `letter_writer/clients/<vendor>.json` (`roles`); Settings → models
overrides them per phase.

## Tests

No test calls a real service (`letter_writer/conftest.py` blanks API keys and blocks Firestore,
LangSmith and Ollaya; live vendor checks in `test_client.py` run only with `LW_LIVE_API_TESTS=1`).

```bash
pytest letter_writer letter_writer_server -n 4          # Firestore tests use the local emulator (Java)
pytest experimental/email/tests                          # the email experiments
cd letter_writer_web && npx jest
cd extensions/job-capture && node --test *.test.mjs
scripts/firebase/test_rules.sh                        # rules + the extension's direct-Firestore path
cd app && ./gradlew --offline testDebugUnitTest
python3 scripts/android/demo_smoke.py                    # on a connected phone or emulator
```
