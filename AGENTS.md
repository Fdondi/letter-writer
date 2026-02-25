# AGENTS.md

## Cursor Cloud specific instructions

### Architecture

This is a **Cover Letter Customizator** — an AI-powered app that generates personalized cover letters using RAG + multiple LLM vendors. Three services:

| Service | Port | Command |
|---------|------|---------|
| **Qdrant** (vector DB) | 6333 | `docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:v1.16` |
| **Django backend** | 8000 | `python3 letter_writer_server/manage.py runserver 0.0.0.0:8000` |
| **Vite frontend** | 5173 | `cd letter_writer_web && npm run dev -- --host 0.0.0.0` |

### Running services

1. **Docker must be running** before starting Qdrant. Start dockerd with `sudo dockerd &>/tmp/dockerd.log &` if needed.
2. **Qdrant** must be started before the backend (the backend connects to it). If the container already exists: `docker start qdrant`.
3. **Django backend** runs from the project root. No `cd` needed.
4. **Vite frontend** proxies `/api` requests to the Django backend on port 8000 (configured in `vite.config.js`).
5. All three services must run for the full application to work.

### Testing

- **Frontend tests**: `cd letter_writer_web && npx jest` — 95 tests, all pass. Uses Jest + React Testing Library.
- **Frontend build**: `cd letter_writer_web && npm run build`
- **Python tests** (`letter_writer/test_client.py`): Currently broken due to pre-existing `ImportError` — the test imports `ModelSize` which does not exist in `letter_writer/client.py`. These tests also require real API keys to make LLM calls.
- **Django check**: `python3 letter_writer_server/manage.py check`

### Gotchas

- `python` is not on `PATH`; use `python3` instead. The `~/.local/bin` directory (where pip installs scripts like `pytest`, `django-admin`) must be on `PATH`: `export PATH="$HOME/.local/bin:$PATH"`.
- The `docker-compose.yml` has a hardcoded Windows path for CV mount (`C:/Users/franc/...`) — do not use `docker-compose up` directly. Start services individually as shown above.
- The `docker-compose.yml` declares `letter-writer_qdrant_storage` as an `external: true` volume which may not exist. Running Qdrant standalone (as above) avoids this issue.
- `OPENAI_API_KEY` is required for the full pipeline (embedding step always uses OpenAI). Other vendor keys are optional.
- Before generating letters, the Qdrant collection must be initialized via the `/api/refresh/` endpoint or the CLI `refresh` command.

### Linting

No dedicated linter is configured for the Python code. The frontend has no ESLint config. Standard checks: `python3 -m py_compile <file>` for Python, `npm run build` for frontend.
