#!/usr/bin/env python3
"""Print LinkedIn JobDetails regions and jobs.ch grid-area snippets."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "extensions" / "job-capture" / "examples"


class RegionParser(HTMLParser):
    def __init__(self, wanted_ids: set[str], wanted_classes: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.wanted_ids = wanted_ids
        self.wanted_classes = wanted_classes
        self.stack: list[tuple[str, str | None, set[str], int]] = []
        self.capture: list[str] | None = None
        self.depth = 0
        self.regions: dict[str, str] = {}
        self.h1s: list[str] = []
        self._h1: list[str] | None = None
        self.aria: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: v or "" for k, v in attrs}
        eid = ad.get("id") or None
        classes = set((ad.get("class") or "").split())
        if ad.get("aria-label"):
            self.aria.append((tag, ad["aria-label"][:120]))
        self.stack.append((tag, eid, classes, self.depth))
        if self.capture is not None:
            self.depth += 1
        elif eid and eid in self.wanted_ids:
            self.capture = [f"[{eid}] "]
            self.depth = 1
        elif classes & self.wanted_classes:
            hit = next(iter(classes & self.wanted_classes))
            self.capture = [f"[{hit}] "]
            self.depth = 1
        if tag == "h1":
            self._h1 = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._h1 is not None:
            text = re.sub(r"\s+", " ", "".join(self._h1)).strip()
            if text:
                self.h1s.append(text[:200])
            self._h1 = None
        if self.capture is not None:
            self.depth -= 1
            if self.depth <= 0:
                key = self.capture[0]
                self.regions[key] = re.sub(r"\s+", " ", "".join(self.capture)).strip()[:800]
                self.capture = None
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.capture is not None:
            self.capture.append(data)
        if self._h1 is not None:
            self._h1.append(data)


def dump_linkedin() -> None:
    html = (EXAMPLES / "LinkedIn.html").read_text(encoding="utf-8", errors="replace")
    p = RegionParser(
        {
            "JobDetails_AboutTheJob_4418521487",
            "JobDetails_AboutTheCompany_4418521487",
            "JobDetails_ManageJobBanner_4418521487",
        },
        set(),
    )
    p.feed(html)
    print("=== LinkedIn h1 ===")
    for t in p.h1s:
        print(" ", t)
    print("=== LinkedIn aria-label (first 40) ===")
    for item in p.aria[:40]:
        print(" ", item)
    print("=== LinkedIn regions ===")
    for k, v in p.regions.items():
        print(k, v[:600])
        print("---")


def dump_jobsch_grid() -> None:
    html = (EXAMPLES / "jobs.ch.html").read_text(encoding="utf-8", errors="replace")
    p = RegionParser(set(), {"grid-area_title", "grid-area_description", "grid-area_company", "grid-area_contact"})
    p.feed(html)
    print("=== jobs.ch grid areas ===")
    for k, v in p.regions.items():
        print(k, v[:700])
        print("---")
    print("=== jobs.ch h1 ===", p.h1s)


if __name__ == "__main__":
    dump_linkedin()
    dump_jobsch_grid()
