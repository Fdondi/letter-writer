"""Test guard: no test reaches a real service.

Imported first by every conftest, before anything imports ``letter_writer.config`` (which loads
``.env`` without overriding variables that are already set). It blanks vendor API keys, turns
LangSmith tracing off, points Firestore and Ollaya at closed ports and hides the ``claude`` CLI and
the service account, so a call that slips past the fakes fails instead of spending money.
``LW_LIVE_API_TESTS=1`` keeps the keys for the opt-in live tests in ``test_client.py``.
"""
import os

LIVE_API_TESTS = os.environ.get("LW_LIVE_API_TESTS") == "1"
BLOCKED_FIRESTORE_HOST = "127.0.0.1:9"

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
if not LIVE_API_TESTS:
    for _key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "MISTRAL_API_KEY",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        os.environ[_key] = ""
os.environ.setdefault("FIRESTORE_EMULATOR_HOST", BLOCKED_FIRESTORE_HOST)
# Never the real `claude` CLI (it would spend the Claude subscription).
os.environ["LW_CLAUDE_BIN"] = "/nonexistent/claude-blocked-in-tests"
# No BigQuery project, so cost tracking and spending checks never reach the real tables.
os.environ["BIGQUERY_PROJECT"] = ""
os.environ["GOOGLE_CLOUD_PROJECT"] = ""
# Never the real service account (the batch would otherwise default to gcloud-credentials.json).
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/nonexistent/letter-writer-test-credentials.json"
# The local decision model (Ollaya) is a service too: a closed port fails at once instead of
# waiting on a hostname that only resolves inside docker-compose.
os.environ["OLLAYA_BASE_URL"] = "http://127.0.0.1:9"
