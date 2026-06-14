# Remove Docker build leftovers (stopped one-off containers, dangling images, build cache).
# Running compose services and their images are kept unless -All is passed.
param(
  [switch]$All,
  [switch]$Volumes
)

$ErrorActionPreference = "Stop"

function Invoke-DockerGcStep {
  param([string]$Label, [scriptblock]$Command)
  Write-Host "=== $Label ==="
  & $Command
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "=== Before ==="
docker system df
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Invoke-DockerGcStep "Pruning stopped containers" { docker container prune -f }
Invoke-DockerGcStep "Pruning dangling images" { docker image prune -f }
Invoke-DockerGcStep "Pruning unused build cache" { docker builder prune -af }

if ($All) {
  Invoke-DockerGcStep "Pruning all unused images (running containers keep their images)" { docker image prune -a -f }
}

if ($Volumes) {
  Invoke-DockerGcStep "Pruning unused volumes" { docker volume prune -f }
}

Write-Host "=== After ==="
docker system df
exit $LASTEXITCODE
