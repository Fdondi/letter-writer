#!/usr/bin/env python3
"""Dump JSON-LD JobPosting, data-cy/data-test, and headings from saved capture examples."""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "extensions" / "job-capture" / "examples"


class DumpParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.data_cy: set[str] = set()
        self.data_test: set[str] = set()
        self.ids: list[str] = []
        self.json_ld: list[str] = []
        self._in_ld = False
        self._ld_chunks: list[str] = []
        self.headings: list[tuple[str, str]] = []
        self._heading_tag: str | None = None
        self._heading_chunks: list[str] = []
        self.interesting_classes: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: v or "" for k, v in attrs}
        if ad.get("data-cy"):
            self.data_cy.add(ad["data-cy"])
        if ad.get("data-test"):
            self.data_test.add(ad["data-test"])
        if ad.get("id"):
            self.ids.append(ad["id"])
        cls = ad.get("class") or ""
        for token in cls.split():
            low = token.lower()
            if any(k in low for k in ("job", "vacancy", "title", "descrip", "company", "salary", "detail")):
                self.interesting_classes.add(token)
        if tag == "script" and "ld+json" in (ad.get("type") or ""):
            self._in_ld = True
            self._ld_chunks = []
        if tag in {"h1", "h2", "h3"}:
            self._heading_tag = tag
            self._heading_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ld:
            self.json_ld.append("".join(self._ld_chunks))
            self._in_ld = False
            self._ld_chunks = []
        if tag == self._heading_tag:
            text = re.sub(r"\s+", " ", "".join(self._heading_chunks)).strip()
            if text:
                self.headings.append((tag, text[:180]))
            self._heading_tag = None
            self._heading_chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_ld:
            self._ld_chunks.append(data)
        if self._heading_tag:
            self._heading_chunks.append(data)


def summarize_ld(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"parse_error": raw[:80]}
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        t = item.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            desc = item.get("description") or ""
            out.append(
                {
                    "title": item.get("title"),
                    "org": (item.get("hiringOrganization") or {}).get("name")
                    if isinstance(item.get("hiringOrganization"), dict)
                    else item.get("hiringOrganization"),
                    "url": item.get("url"),
                    "desc_len": len(str(desc)),
                    "desc_start": re.sub(r"<[^>]+>", " ", str(desc))[:160],
                    "contact": item.get("applicationContact"),
                    "location": item.get("jobLocation"),
                    "salary": item.get("baseSalary"),
                }
            )
    return {"job_postings": out, "types": [i.get("@type") for i in items if isinstance(i, dict)]}


def main() -> int:
    files = [
        EXAMPLES / "jobs.ch.html",
        EXAMPLES / "swissdevjobs.ch.html",
        EXAMPLES / "LinkedIn.html",
    ]
    for path in files:
        print("=" * 80)
        print(path.name, "bytes=", path.stat().st_size)
        html = path.read_text(encoding="utf-8", errors="replace")
        p = DumpParser()
        p.feed(html)
        print("data-cy:", sorted(p.data_cy)[:80], "count=", len(p.data_cy))
        print("data-test:", sorted(p.data_test)[:40], "count=", len(p.data_test))
        print("ids with job/vacancy:", [i for i in p.ids if re.search(r"job|vacancy|detail", i, re.I)][:40])
        print("interesting classes:", sorted(p.interesting_classes)[:60])
        print("headings:")
        for tag, text in p.headings[:25]:
            print(f"  {tag}: {text}")
        print("json-ld blocks:", len(p.json_ld))
        for i, raw in enumerate(p.json_ld):
            print(f"  ld[{i}]:", summarize_ld(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
