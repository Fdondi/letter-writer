#!/bin/sh
# Remove Docker build leftovers (stopped one-off containers, dangling images, build cache).
# Running compose services and their images are kept unless --all is passed.
set -e

all=0
volumes=0
while [ $# -gt 0 ]; do
  case "$1" in
    --all) all=1 ;;
    --volumes) volumes=1 ;;
    -h|--help)
      echo "Usage: $0 [--all] [--volumes]"
      echo "  default   stopped containers, dangling (<none>) images, build cache"
      echo "  --all     also remove images not used by any container (next build re-pulls/rebuilds)"
      echo "  --volumes also remove unused volumes (data loss; old Qdrant volumes, etc.)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

echo "=== Before ==="
docker system df

echo "=== Pruning stopped containers ==="
docker container prune -f

echo "=== Pruning dangling images ==="
docker image prune -f

echo "=== Pruning unused build cache ==="
docker builder prune -af

if [ "$all" -eq 1 ]; then
  echo "=== Pruning all unused images (running containers keep their images) ==="
  docker image prune -a -f
fi

if [ "$volumes" -eq 1 ]; then
  echo "=== Pruning unused volumes ==="
  docker volume prune -f
fi

echo "=== After ==="
docker system df
