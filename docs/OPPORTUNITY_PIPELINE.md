# Opportunity pipeline: running it

Design and reasons: `OPPORTUNITY_PIPELINE_PLAN.md`. This page is how to set it up and use it.

```
phone / extension / web ──send──▶ captured ──timer: daemon --once──▶ rated ──best under the 24h cap──▶ drafting ──▶ ready ──open/save──▶ done
        (bare link: approved, "needs text")            │                        └──▶ failed (retry)
                                                         └── older than 3 days ──▶ archived (re-enable from the web)
```

Each wake of the daemon (`scripts/opportunities/run-routine.sh`, every `LW_WAKE_INTERVAL_HOURS`,
default 3): archive expired rated jobs → extract and fit-rate every captured job (`fit_score`,
the weighted competence match the intake shows; the user's `fit_score_user` override wins) →
draft the best rated jobs up to the rolling 24h cap (`LW_DAILY_CAP`, default 5). `run-captured`
is the manual override (drafts captured jobs now, ignoring the rating and the cap).

## Pieces

| Piece | Where |
|---|---|
| Store, keys (`canonical_key`, document ids) | `letter_writer/opportunity_store.py`; the Android app's `OpportunityKeys.kt` must agree (shared cases: `letter_writer/tests/fixtures/opportunity_keys.json`) |
| Mail (experimental, unused) | `experimental/email/`: alert templates, reply classification, outcomes, Gmail routine, findings |
| Batch CLI | `python -m letter_writer.batch daemon [--once] / run-captured / status / retry / seed / users` |
| Headless sessions | `letter_writer/headless.py` (phased pipeline without a request, one thread per vendor) |
| Claude Code vendor | `letter_writer/clients/claude_code.py` + `claude_code.json` (`claude -p`, no tools, subscription) |
| Web API | `/api/opportunities/…`; `/api/job-capture/pending/`; ingest attaches captures to approved jobs and queues pages (`queue: true`) |
| Web UI | **Jobs** button / `/opportunities` (desktop); **Ready → Craft letter** jumps to assembling the final letter from the batch's drafts |
| Extension | `extensions/job-capture/` queues the sent page like the phone app (Options, default on) and auto-captures an approved job's page when you open it |
| Phone | Android app: **Job pipeline** tab reads the same Firestore collection (no connection to this computer) |
| Firestore rules | `firebase/firestore.rules` (`opportunities`, drafts read-only for the phone) |
| Schedule | `scripts/opportunities/run-routine.sh` + `install.sh timer` (every 15 min, no Claude agent); `docs/routines/letter-opportunities/SKILL.md` for running it from Claude Code |

## Setup and use

Every step (one-time setup, running the routine by hand or every 4 hours, day-to-day use, what
happens when you already applied, troubleshooting) is in the README, section **Opportunity pipeline**.

Batch commands: `daemon [--once] [--interval-hours H] [--daily-cap N] [--archive-days D] [--vendors a,b] [--rewrite-rounds 0|1|2] [--[no-]final-feedback] [--dry-run]`
(the scheduled path; the env vars `LW_WAKE_INTERVAL_HOURS` / `LW_DAILY_CAP` / `LW_ARCHIVE_DAYS` set
the same defaults), `run-captured [--max-jobs N] [--vendors a,b] [--rewrite-rounds 0|1|2] [--[no-]final-feedback] [--detach] [--dry-run]` (manual override), `status`, `retry <id>`,
`seed --url … [--text-file …]`, `users`.

Web API additions: `POST /api/opportunities/{id}/rate/ {score|null}` sets or clears the user's fit
estimate (shown and sorted by instead of the computed one); `POST /api/opportunities/{id}/reenable/ {score?}`
moves an archived job back to `rated` with a fresh archive window. The web app shows the queues
under **Jobs → Rated** (editable rating) and **Jobs → Archived** (re-enable).

## Costs

API vendors count toward the spending limits as before (checked before each job; when over the
limit only `claude_code` runs). `claude_code` records `total_cost_usd` from the CLI as
`cost_subscription_estimate_usd` on the job; it is not API spend.

## Tests

No test calls a real service (`letter_writer/conftest.py` blanks keys and blocks Firestore,
LangSmith and Ollaya). Store, batch and API tests use the local Firestore emulator
(`firebase setup:emulators:firestore` once; Java required), LLM calls use the fixtures in
`app/debug/fixtures`.

```bash
pytest letter_writer letter_writer_server -n 4
node --test extensions/job-capture/pending.test.mjs
scripts/firebase/test_rules.sh
cd letter_writer_web && npx jest
cd app && ./gradlew --offline testDebugUnitTest
```
