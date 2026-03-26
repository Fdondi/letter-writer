#!/bin/sh
set -e
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
# On Git Bash/MSYS, convert /c/... paths to C:/... so Docker Desktop mounts host sources.
docker_root="$root"
if command -v cygpath >/dev/null 2>&1; then
  docker_root="$(cygpath -m "$root")"
fi
# Skip rebuild when set (e.g. pre-commit): use existing backend image; run `docker compose build backend` if stale.
if [ -z "${SKIP_DOCKER_BUILD:-}" ]; then
  docker compose build backend
fi
# No pyproject.toml or repo-root bind: those break under pre-commit + Windows Docker. Keep flags in sync with pyproject.toml [tool.mypy]; pip pins with [dependency-groups] dev.
docker compose run --rm --no-deps \
  -v "$docker_root/letter_writer:/app/letter_writer:ro" \
  -v "$docker_root/letter_writer_server:/app/letter_writer_server:ro" \
  backend \
  sh -c "pip install -q 'mypy>=1.8.0' 'types-redis>=4.6.0' && python -m mypy --python-version 3.13 --ignore-missing-imports --implicit-optional --show-error-codes --warn-unused-ignores letter_writer letter_writer_server"
