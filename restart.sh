podman stop letter-writer-frontend letter-writer-backend &&echo "=== Stopped containers ===" || echo "=== Failed to stop containers ==="
podman rm letter-writer-frontend letter-writer-backend && echo "=== Removed frontend ===" || echo "=== Failed to remove frontend ==="
# podman rm letter-writer-backend && echo "=== Removed backend ===" || echo "=== Failed to remove backend ==="
podman-compose up -d frontend backend --build && echo "=== Started containers ===" || echo "=== Failed to start containers ==="
