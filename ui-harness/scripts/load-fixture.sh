#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ID="${1:-}"
if [ -z "$ID" ]; then
  echo "Usage: load-fixture.sh <fixture-id>" >&2
  echo "Catalog: empty-intake intake-filled vendor-plan vendor-draft-notes vendor-draft-empty-feedback vendor-assembly agentic-mid-loop agentic-done error-generate" >&2
  exit 1
fi
echo "Open http://127.0.0.1:3010/?fixture=${ID}"
if command -v curl >/dev/null 2>&1; then
  curl -sS "http://127.0.0.1:3011/api/harness/fixtures/" || true
  echo
fi
