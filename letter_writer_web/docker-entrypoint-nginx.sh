#!/bin/sh
set -e
echo "[entrypoint] Checking /etc/nginx/certs/ ..."
ls -la /etc/nginx/certs/ || true
if [ ! -f /etc/nginx/certs/localhost+1.pem ] || [ ! -f /etc/nginx/certs/localhost+1-key.pem ]; then
  echo "[entrypoint] ERROR: Missing localhost+1.pem or localhost+1-key.pem in /etc/nginx/certs/. Mount ./certs (with mkcert certs) as /etc/nginx/certs."
  exit 1
fi
echo "[entrypoint] Testing nginx config..."
nginx -t
exec nginx -g "daemon off;"
