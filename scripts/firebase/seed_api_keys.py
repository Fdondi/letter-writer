"""Copy vendor API keys from .env into personal_data/{user_id}/secrets/api_keys.

The Android app reads its keys from that owner-only document (see firebase/firestore.rules).
Uses the same Firestore credentials as the desktop backend (ADC / GOOGLE_APPLICATION_CREDENTIALS).

    temp/venv/bin/python scripts/firebase/seed_api_keys.py --user-id <google sub> [--dry-run]

Only keys present in .env are written; existing fields not in .env are kept (merge).
Values are never printed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from letter_writer.firestore_store import get_personal_data_document  # noqa: E402

# Field in secrets/api_keys -> variable in .env
FIELDS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google_translate": "GOOGLE_TRANSLATE_API_KEY",
    "decision_model": "DECISION_MODEL_API_KEY",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True, help="Google sub (personal_data document id)")
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = dotenv_values(args.env_file)
    values = {field: env[var].strip() for field, var in FIELDS.items() if (env.get(var) or "").strip()}
    missing = [var for field, var in FIELDS.items() if field not in values]

    profile = get_personal_data_document(args.user_id)
    if not profile.get().exists:
        print(f"personal_data/{args.user_id} does not exist; refusing to create secrets for an unknown user")
        return 1

    print("Writing:", ", ".join(sorted(values)) or "(nothing)")
    if missing:
        print("Not in .env (left unchanged):", ", ".join(missing))
    if args.dry_run or not values:
        return 0
    profile.collection("secrets").document("api_keys").set(values, merge=True)
    print(f"Updated personal_data/{args.user_id}/secrets/api_keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
