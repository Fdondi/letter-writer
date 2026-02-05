#!/bin/sh
# Start N Gunicorn workers each on a different port; Nginx in front routes by session cookie (sticky).
set -e
WORKERS=${GUNICORN_WORKERS:-3}
TIMEOUT=${GUNICORN_TIMEOUT:-300}
THREADS=${GUNICORN_THREADS:-2}
PORT_START=8001

# Generate Nginx upstream with one server per worker port
mkdir -p /etc/nginx/conf.d
cat > /etc/nginx/conf.d/sticky.conf << 'NGINX_UPSTREAM'
upstream backend_workers {
    hash $cookie_letter_writer_session consistent;
NGINX_UPSTREAM
i=0
while [ "$i" -lt "$WORKERS" ]; do
    port=$((PORT_START + i))
    echo "    server 127.0.0.1:${port};" >> /etc/nginx/conf.d/sticky.conf
    i=$((i + 1))
done
cat >> /etc/nginx/conf.d/sticky.conf << 'NGINX_SERVER'
}
server {
    listen 8000;
    server_name _;
    location / {
        proxy_pass http://backend_workers;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_connect_timeout 60s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }
}
NGINX_SERVER

i=0
while [ "$i" -lt "$WORKERS" ]; do
    port=$((PORT_START + i))
    gunicorn letter_writer_server.wsgi:application \
        --bind "127.0.0.1:${port}" \
        --workers 1 \
        --threads "$THREADS" \
        --timeout "$TIMEOUT" \
        --daemon
    i=$((i + 1))
done

exec nginx -g "daemon off;"
