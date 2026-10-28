---
name: letter-opportunities
description: Draft letters for the jobs captured from the phone, the extension or the web app (letter-writer opportunity pipeline)
allowed-tools: Bash(.venv/bin/python -m letter_writer.batch *)
---
You run the drafting step of the letter-writer opportunity pipeline in the letter-writer repository.
Run only the commands below.

1. Run `.venv/bin/python -m letter_writer.batch run-captured --max-jobs 3 --detach`. It returns at
   once; extraction and drafting continue in the background (log under `temp/opportunities/`).
2. Run `.venv/bin/python -m letter_writer.batch status` and reply with its line, nothing else.

On Linux the timer from `scripts/opportunities/install.sh timer` does this without Claude; this
skill is for running it by hand (`/letter-opportunities`) or from Claude Code Desktop.
