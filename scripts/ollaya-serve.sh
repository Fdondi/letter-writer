#!/bin/bash
# Start Ollaya, then pull the laya router. The image serves only; it does not download weights.
# `ollaya pull` refuses to start when a pid file from a previous container is still on the volume.
set -eu

rm -f /home/ollaya/.ollaya/server.*.pid

ollaya serve &
server_pid=$!

ready=0
i=0
while [ "$i" -lt 90 ]; do
  if bash -c 'echo > /dev/tcp/127.0.0.1/11435' 2>/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "ollaya serve exited before the port opened" >&2
    exit 1
  fi
  i=$((i + 1))
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "Ollaya did not open port 11435" >&2
  exit 1
fi

ollaya pull laya
wait "$server_pid"
