podman rm -f letter-writer-frontend letter-writer-backend || echo "=== Failed to remove containers ==="
podman rmi -f localhost/letter-writer_backend:latest localhost/letter-writer_frontend:latest || echo "=== Failed to remove images ==="
podman-compose build --no-cache frontend backend && podman-compose up -d frontend backend && echo "=== Started containers ===" || echo "=== Failed to start containers ==="
