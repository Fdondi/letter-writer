#!/usr/bin/env bash
# One run of the opportunity pipeline (the systemd timer from install.sh calls it every 15 minutes):
# extract and draft letters for jobs captured from the phone, the extension or the web app.
# No Claude agent is involved: the batch calls Claude Code (and the API vendors) itself, and a run
# with nothing captured only reads Firestore. Mail reading is experimental (experimental/email/).
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo"
logdir=temp/opportunities
mkdir -p "$logdir"
log="$logdir/routine.log"

{
  status=0
  .venv/bin/python -m letter_writer.batch run-captured --max-jobs "${LW_ROUTINE_MAX_JOBS:-3}" || status=$?
  echo "=== $(date -Is) exit $status: $(.venv/bin/python -m letter_writer.batch status 2>&1)"
} >>"$log" 2>&1
