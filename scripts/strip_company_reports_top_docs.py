#!/usr/bin/env python3
"""One-off maintenance: remove persisted ``reports.*.top_docs`` from Firestore company docs.

Run from repo root with PYTHONPATH set, e.g.:

  PYTHONPATH=. python scripts/strip_company_reports_top_docs.py

Dry-run by default; pass --apply to write updates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

# Repo root: scripts/ -> parent
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from letter_writer.firestore_store import strip_top_docs_from_all_company_research_docs

app = typer.Typer(add_completion=False)


@app.command()
def main(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Perform Firestore updates. Without this flag, only prints a dry-run summary.",
    ),
) -> None:
    result = strip_top_docs_from_all_company_research_docs(dry_run=not apply)
    print(json.dumps(result, indent=2, default=str))
    if apply:
        typer.echo("Updates applied.", err=True)
    else:
        typer.echo("Dry run only. Re-run with --apply to write changes.", err=True)


if __name__ == "__main__":
    app()
