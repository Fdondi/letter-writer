#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v podman >/dev/null 2>&1; then
  COMPOSE=(podman compose)
else
  echo "Need docker compose or podman compose" >&2
  exit 1
fi
"${COMPOSE[@]}" -f docker-compose.yml up -d --build "$@"
echo "Harness SPA: http://127.0.0.1:3010/?fixture=vendor-draft-notes"
echo "API:         http://127.0.0.1:3011/api/harness/info/"
echo "CDP:         http://127.0.0.1:9222"
echo "Watch (noVNC): http://127.0.0.1:7900/vnc.html"
