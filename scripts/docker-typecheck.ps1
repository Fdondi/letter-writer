# Run mypy inside the backend image with workspace source mounted (matches Python 3.13 in Dockerfile.backend).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $env:SKIP_DOCKER_BUILD) {
  docker compose build backend
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
# No pyproject.toml or repo-root bind: those break under pre-commit + Windows Docker. Keep flags in sync with pyproject.toml [tool.mypy]; pip pins with [dependency-groups] dev.
docker compose run --rm --no-deps `
  -v "${root}/letter_writer:/app/letter_writer:ro" `
  -v "${root}/letter_writer_server:/app/letter_writer_server:ro" `
  backend `
  sh -c "pip install -q 'mypy>=1.8.0' 'types-redis>=4.6.0' && python -m mypy --python-version 3.13 --ignore-missing-imports --implicit-optional --show-error-codes --warn-unused-ignores letter_writer letter_writer_server"
exit $LASTEXITCODE
