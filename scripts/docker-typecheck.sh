#!/bin/sh
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
# Skip rebuild when set (e.g. pre-commit): use existing backend image; run `docker compose build backend` if stale.
if [ -z "${SKIP_DOCKER_BUILD:-}" ]; then
  docker compose build backend
fi
# No pyproject.toml or repo-root bind: those break under pre-commit + Windows Docker. Keep flags in sync with pyproject.toml [tool.mypy]; pip pins with [dependency-groups] dev.
docker compose run --rm --no-deps \
  -v "$root/letter_writer:/app/letter_writer:ro" \
  -v "$root/letter_writer_server:/app/letter_writer_server:ro" \
  backend \
  sh -c "pip install -q 'mypy>=1.8.0' 'types-redis>=4.6.0' && python -m mypy --python-version 3.13 --ignore-missing-imports --implicit-optional --show-error-codes --warn-unused-ignores letter_writer letter_writer_server"
