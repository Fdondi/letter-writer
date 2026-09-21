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
"${COMPOSE[@]}" -f docker-compose.yml up -d --build backend frontend
"${COMPOSE[@]}" -f docker-compose.yml --profile smoke run --rm smoke
