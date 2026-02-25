# AGENTS.md

## Cursor Cloud specific instructions

### Architecture

**Cover Letter Customizator** — AI-powered cover letter generation using RAG + multiple LLM vendors (OpenAI, Anthropic, Gemini, Mistral, Grok, DeepSeek). Uses Firestore for document storage, Google OAuth for authentication, and optional Redis/BigQuery for cost tracking.

| Service | Port | Start command |
|---------|------|---------------|
| **FastAPI backend** | 8000 | `python3 -m uvicorn letter_writer_server.main:app --host 0.0.0.0 --port 8000 --workers 1` |
| **Vite frontend** | 5173 | `cd letter_writer_web && npm run dev -- --host 0.0.0.0` |

Qdrant is **no longer used** (replaced by Firestore). Redis is optional (cost tracking falls back to in-memory).

### Running services

1. **FastAPI backend** runs from the project root. Uses `python-dotenv` + `pydantic-settings` to load config.
2. **Vite frontend** proxies `/api` and `/accounts` to the backend on port 8000 (see `vite.config.js`).
3. Both services must run for the full application to work.

### Authentication

The app uses **Google OAuth** (via `authlib`). For local/cloud dev without Google OAuth set up, use the **test-login backdoor**:

1. Set `TEST_AUTH_PASSWORD=<password>` and `ENVIRONMENT=development` in `.env`
2. In the browser console at `http://localhost:5173`:
   ```javascript
   fetch('/api/auth/test-login/', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password:'<password>'}), credentials:'include'}).then(r=>r.json()).then(d=>{console.log(d);location.reload()})
   ```
3. The `ENVIRONMENT=development` setting makes session cookies work over HTTP (no HTTPS required).

### Environment variables / .env

The `.env` file must **only** contain fields defined in the `Settings` class (`letter_writer_server/core/config.py`), because `pydantic-settings` rejects unknown keys. API keys should be system env vars (not in `.env`).

Minimal `.env` for development:
```
ENVIRONMENT=development
TEST_AUTH_PASSWORD=<your-test-password>
```

API keys read via `os.getenv()` throughout the `letter_writer` package:
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` (for Gemini), `MISTRAL_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY`, `GOOGLE_TRANSLATE_API_KEY`

Firestore/GCP: `GOOGLE_CLOUD_PROJECT`, `FIRESTORE_PROJECT_ID`, `FIRESTORE_DATABASE`

### Firestore (GCP) dependency

Most core features (`/api/extract/`, `/api/phases/init/`, `/api/documents/`, `/api/personal-data/`) require **GCP Application Default Credentials** for Firestore. Without credentials, these endpoints fail with `DefaultCredentialsError`.

**Setup for Cursor Cloud:** Add a secret named `GOOGLE_CREDENTIALS_JSON` containing the full service account JSON. The update script writes it to `/workspace/gcloud-credentials.json`, and `~/.bashrc` sets `GOOGLE_APPLICATION_CREDENTIALS` to point at it. After adding the secret, restart the backend for it to take effect.

**Setup for local dev:** Place the service account JSON at `/workspace/gcloud-credentials.json` and `export GOOGLE_APPLICATION_CREDENTIALS=/workspace/gcloud-credentials.json`.

Endpoints that work **without** Firestore: `/health`, `/api/auth/*`, `/api/vendors/`, `/api/style-instructions/`, `/api/search-instructions/`, `/api/costs/*`.

### Testing

- **Frontend tests**: `cd letter_writer_web && npx jest` — many tests fail due to pre-existing `LanguageProvider` context not being wrapped in test harnesses (31 pass, 64 fail).
- **Frontend build**: `cd letter_writer_web && npm run build`
- **Backend health**: `curl http://localhost:8000/health`
- **Python tests** (`letter_writer/test_client.py`): pre-existing `ImportError` — `ModelSize` not re-exported from `letter_writer.client`.

### Gotchas

- Use `python3` not `python`. Add `~/.local/bin` to `PATH`: `export PATH="$HOME/.local/bin:$PATH"`.
- The `.env` file must NOT contain API keys or other vars not defined in the `Settings` class — `pydantic-settings` will reject them with `extra_forbidden`.
- The Gemini SDK uses `GOOGLE_API_KEY` (not `GEMINI_API_KEY`).
- The session cookie `secure` flag is controlled by `ENVIRONMENT`: set to `development` for HTTP, anything else for HTTPS.
- `docker-compose.yml` is designed for production with nginx. For dev, run services individually as shown above.

### Linting

No dedicated Python linter or ESLint configured. Use `python3 -m py_compile <file>` for Python syntax, `npm run build` for frontend.
