# Mocked UI harness

Isolated Docker stack for clicking through Letter Writer **without** Google login, Firestore, API keys, or your daily browser. Session snapshots are **synthetic** (`"synthetic": true`). Generation endpoints return `503` with `Harness: LLM disabled` — they never invent a letter.

## Start

```bash
ui-harness/scripts/up.sh
```

(`docker compose` or `podman compose`, whichever talks to a running engine.)

| What | URL |
|------|-----|
| SPA | http://127.0.0.1:3010/?fixture=vendor-draft-notes |
| API | http://127.0.0.1:3011/api/harness/info/ |
| Chromium CDP | http://127.0.0.1:9222 |
| Watch (noVNC) | http://127.0.0.1:7900/vnc.html |

The yellow **Harness · synthetic data · LLM disabled** banner must be visible. If it is not, you are not on this stack.

The job-capture extension should target this SPA (`http://127.0.0.1:3010`), not production `https://localhost:8443`. Ingest is unauthenticated; process fills intake from the captured page text without calling a model.

## Restorable fixtures

Open `http://127.0.0.1:3010/?fixture=<id>` (or `ui-harness/scripts/load-fixture.sh <id>`).

| id | Screen |
|----|--------|
| `empty-intake` | Blank intake |
| `intake-filled` | Job + metadata filled |
| `vendor-plan` | Plan card |
| `vendor-draft-notes` | Quote-anchored notes on the draft |
| `vendor-draft-empty-feedback` | Draft, empty category chips |
| `vendor-assembly` | Assembled final letter |
| `agentic-mid-loop` | Agentic threads with notes |
| `agentic-done` | Agentic assembly |
| `error-generate` | Draft ready to approve; Approve must show the harness 503 |

## Playwright smokes

```bash
ui-harness/scripts/smoke.sh
```

## Agent click-through

Connect Playwright or Cursor CDP to `http://127.0.0.1:9222` (the Docker Chromium, not your profile). Open a `?fixture=` URL, then click. Watch on noVNC if you want to see it.

This compose file does **not** mount `.env` or `gcloud-credentials.json`. Do not point `HARNESS_MODE` at the production `docker-compose.yml`.
