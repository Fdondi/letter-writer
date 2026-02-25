# AGENTS.md

## Cursor Cloud specific instructions

### Architecture

This is a **Cover Letter Customizator** — an AI-powered app that generates personalized cover letters using RAG + multiple LLM vendors (OpenAI, Anthropic, Gemini, Mistral, Grok, DeepSeek). Three services:

| Service | Port | Command |
|---------|------|---------|
| **Qdrant** (vector DB) | 6333 | `docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:v1.16` |
| **Django backend** | 8000 | `python3 letter_writer_server/manage.py runserver 0.0.0.0:8000` |
| **Vite frontend** | 5173 | `cd letter_writer_web && npm run dev -- --host 0.0.0.0` |

### Running services

1. **Docker must be running** before starting Qdrant. Start dockerd with `sudo dockerd &>/tmp/dockerd.log &` if needed.
2. **Qdrant** must be started before the backend (the backend connects to it). If the container already exists: `docker start qdrant`.
3. **Django backend** runs from the project root. No `cd` needed. It loads API keys from `.env` via `python-dotenv`.
4. **Vite frontend** proxies `/api` requests to the Django backend on port 8000 (configured in `vite.config.js`).
5. All three services must run for the full application to work.

### Environment variables / .env

A `.env` file must exist at the project root with API keys. Required keys:
- `OPENAI_API_KEY` (always required — used for embeddings AND as an LLM vendor)
- `GOOGLE_API_KEY` (for Gemini; the `google-genai` SDK reads this env var)
- Other vendor keys are optional: `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`
- `GOOGLE_TRANSLATE_API_KEY` (for the translate feature)

### Qdrant initialization

Before generating letters, the Qdrant `job_offers` collection must be populated with example job/letter pairs. Use:
```
curl -X POST http://localhost:8000/api/refresh/ -H "Content-Type: application/json" \
  -d '{"jobs_source_folder": "<folder>", "jobs_source_suffix": ".txt", "letters_source_folder": "<folder>", "letters_source_suffix": ".txt"}'
```
Job offers and their corresponding letters must share the same filename (minus suffix). There are no example data files in the repo (private user data). For testing, create minimal pairs in temporary directories.

### Testing

- **Frontend tests**: `cd letter_writer_web && npx jest` — Uses Jest + React Testing Library.
- **Frontend build**: `cd letter_writer_web && npm run build`
- **Python tests** (`letter_writer/test_client.py`): Currently broken due to pre-existing `ImportError` — the test imports `ModelSize` from `letter_writer.client` but only `ModelVendor` is re-exported there (`ModelSize` lives in `letter_writer.clients.base`). These tests also require real API keys to make LLM calls.
- **Django check**: `python3 letter_writer_server/manage.py check`

### Gotchas

- `python` is not on `PATH`; use `python3` instead. The `~/.local/bin` directory (where pip installs scripts like `pytest`, `django-admin`) must be on `PATH`: `export PATH="$HOME/.local/bin:$PATH"`.
- The `docker-compose.yml` has a hardcoded Windows path for CV mount (`C:/Users/franc/...`) — do not use `docker-compose up` directly. Start services individually as shown above.
- The `docker-compose.yml` declares `letter-writer_qdrant_storage` as an `external: true` volume which may not exist. Running Qdrant standalone (as above) avoids this issue.
- The Gemini SDK uses `GOOGLE_API_KEY` (not `GEMINI_API_KEY`). If you have `GEMINI_API_KEY` in your environment, write `GOOGLE_API_KEY=<value>` to `.env`.

### Linting

No dedicated linter is configured for the Python code. The frontend has no ESLint config. Standard checks: `python3 -m py_compile <file>` for Python, `npm run build` for frontend.
