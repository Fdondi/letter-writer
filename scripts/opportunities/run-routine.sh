#!/usr/bin/env bash
# One wake of the opportunity pipeline (the systemd timer from install.sh calls it every
# LW_WAKE_INTERVAL_HOURS, default 3): archive rated jobs that never made it, extract and
# fit-rate every captured job, then draft only the best rated ones up to the rolling 24h cap
# (LW_DAILY_CAP, default 5). No Claude agent is involved: the batch calls Claude Code (and the
# API vendors) itself, and a wake with nothing captured only reads Firestore. Mail reading is
# experimental (experimental/email/).
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo"
logdir=temp/opportunities
mkdir -p "$logdir"
log="$logdir/routine.log"

{
  status=0
  .venv/bin/python -m letter_writer.batch daemon --once || status=$?
  echo "=== $(date -Is) exit $status: $(.venv/bin/python -m letter_writer.batch status 2>&1)"
} >>"$log" 2>&1
