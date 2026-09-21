#!/bin/bash
set -euo pipefail
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 -ac >/tmp/xvfb.log 2>&1 &
sleep 0.4
fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display :99 -forever -shared -nopw -listen 0.0.0.0 -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 7900 localhost:5900 >/tmp/novnc.log 2>&1 &
CHROME=""
if python3 -c "from playwright.sync_api import sync_playwright" >/dev/null 2>&1; then
  CHROME=$(python3 -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print(p.chromium.executable_path); p.stop()")
fi
if [ -z "$CHROME" ]; then
  CHROME=$(find /ms-playwright -name chrome -type f 2>/dev/null | head -1 || true)
fi
if [ -z "$CHROME" ]; then
  echo "Chromium executable not found" >&2
  exit 1
fi
exec "$CHROME" --no-sandbox --disable-gpu --disable-dev-shm-usage --remote-debugging-address=0.0.0.0 --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir=/tmp/harness-profile --no-first-run --no-default-browser-check "${HARNESS_START_URL:-http://frontend:5173}"
