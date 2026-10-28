#!/usr/bin/env bash
# Runs firebase/tests/*.test.mjs (the rules tests and the extension's direct-Firestore path)
# against a local Firestore emulator (demo project, no cloud access).
# The emulator is started directly: `firebase emulators:exec` rewrites the child's node flags and breaks node:test.
set -euo pipefail
cd "$(dirname "$0")/../../firebase"
(cd tests && npm install --no-audit --no-fund --silent)
mkdir -p ../temp/firebase
log=../temp/firebase/emulator.log
# setsid: the trap must kill the java child too, not just the firebase CLI wrapper.
setsid firebase emulators:start --only firestore --project demo-letter-writer-rules >"$log" 2>&1 &
emulator=$!
trap 'kill -- -"$emulator" 2>/dev/null; wait "$emulator" 2>/dev/null || true' EXIT
for _ in $(seq 1 120); do
  if curl -s -o /dev/null http://127.0.0.1:8085/; then break; fi
  if ! kill -0 "$emulator" 2>/dev/null; then cat "$log"; exit 1; fi
  sleep 0.5
done
# One emulator for all files: run them sequentially (each file clears and reseeds).
(cd tests && node --test --test-concurrency=1)
