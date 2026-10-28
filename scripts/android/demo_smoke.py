#!/usr/bin/env python3
"""Walk the Android app through demo mode on a device or emulator and fail on any crash.

    python3 scripts/android/demo_smoke.py [--serial emulator-5590] [--apk PATH] [--fresh] [--out temp/android-smoke]

Demo mode needs no account and calls no service, so this runs anywhere adb reaches: enter demo
("Try the demo" on the sign-in screen, else the adb flag) -> a letter from scratch (read, research,
plan, draft, checks, rewrite, save) -> Job pipeline -> Ready -> "Open the drafts" -> "Leave demo"
-> back in via the adb flag -> restart (demo is remembered) -> leave.

Safe on your own phone: demo data is separate and starts afresh, and the app is left signed in as
before. --apk installs that APK first; --fresh clears the app's data and grants the notification
permission (emulators). Screenshots go to --out. Exit code 1 on a crash or a missing screen.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PKG = "io.github.fdondi.letterwriter"
DEMO_EXTRA = f"{PKG}.DEMO"
REPO = Path(__file__).resolve().parents[2]


class Smoke:
    def __init__(self, serial: str | None, out: Path) -> None:
        self.base = ["adb"] + (["-s", serial] if serial else [])
        self.out = out
        out.mkdir(parents=True, exist_ok=True)

    def adb(self, *args: str, check: bool = True) -> str:
        return subprocess.run(self.base + list(args), check=check, capture_output=True, text=True).stdout

    def nodes(self) -> list[ET.Element]:
        self.adb("shell", "uiautomator", "dump", "/sdcard/lw_ui.xml", check=False)
        raw = self.adb("exec-out", "cat", "/sdcard/lw_ui.xml", check=False)
        try:
            return list(ET.fromstring(raw).iter("node"))
        except ET.ParseError:
            return []

    def find(self, label: str, exact: bool = False) -> ET.Element | None:
        for node in self.nodes():
            for attr in ("text", "content-desc"):
                value = node.get(attr) or ""
                if (value == label) if exact else (label in value):
                    return node
        return None

    def wait_gone(self, label: str, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.find(label) is None:
                return
            self.check_no_crash()
            time.sleep(0.7)
        self.shot("still-" + re.sub(r"\W+", "-", label)[:30])
        raise SystemExit(f"FAIL: '{label}' still shown after {timeout:.0f}s")

    def swipe(self, down: bool) -> None:
        size = re.findall(r"(\d+)x(\d+)", self.adb("shell", "wm", "size"))
        w, h = map(int, size[-1]) if size else (1080, 2400)
        y1, y2 = (int(h * 0.75), int(h * 0.35)) if down else (int(h * 0.35), int(h * 0.75))
        self.adb("shell", "input", "swipe", str(w // 2), str(y1), str(w // 2), str(y2), "300")
        time.sleep(0.4)

    def wait(self, label: str, timeout: float = 20.0, exact: bool = False) -> ET.Element:
        """Waits for ``label``, scrolling down the page and back up (only what is on screen is in the dump)."""
        deadline = time.monotonic() + timeout
        step = 0
        while time.monotonic() < deadline:
            node = self.find(label, exact)
            if node is not None:
                return node
            self.check_no_crash()
            self.swipe(down=step % 12 < 6)
            step += 1
        self.shot("missing-" + re.sub(r"\W+", "-", label)[:30])
        raise SystemExit(f"FAIL: '{label}' did not appear within {timeout:.0f}s (screenshot in {self.out})")

    def tap(self, label: str, exact: bool = False, timeout: float = 20.0) -> None:
        self.tap_node(self.wait(label, timeout, exact))

    def tap_node(self, node: ET.Element) -> None:
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds") or "[0,0][0,0]"))
        self.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        time.sleep(0.8)

    def find_scrolling(self, matches, swipes: int = 12) -> ET.Element | None:
        """First node whose text ``matches`` (a predicate), scrolling down then back up once."""
        for step in range(swipes + 1):
            for node in self.nodes():
                if matches(node.get("text") or node.get("content-desc") or ""):
                    return node
            if step < swipes:
                self.swipe(down=step < swipes // 2)
        return None

    def shot(self, name: str) -> None:
        png = subprocess.run(self.base + ["exec-out", "screencap", "-p"], capture_output=True).stdout
        (self.out / f"{name}.png").write_bytes(png)

    def check_no_crash(self) -> None:
        crash = self.adb("logcat", "-d", "-b", "crash", check=False)
        if PKG in crash or "FATAL EXCEPTION" in crash:
            (self.out / "crash.txt").write_text(crash, encoding="utf-8")
            raise SystemExit(f"FAIL: the app crashed; see {self.out / 'crash.txt'}")

    def launch(self, *extra: str) -> None:
        self.adb("shell", "am", "start", "-n", f"{PKG}/.MainActivity", *extra)
        time.sleep(2)


def write_from_scratch(s: Smoke) -> None:
    """Job text -> read -> research -> plan -> draft -> checks -> rewrite -> final -> save, all on fixtures."""
    s.tap("Job offer text or link")
    s.adb("shell", "input", "text", "FAKE%sFixture%sEngineer%sat%sFAKE%sFixture%sWorks.%sFixtureStack%sand%sFixtureLang.")
    s.adb("shell", "input", "keyevent", "KEYCODE_BACK")  # close the keyboard
    s.tap("Draft here")
    s.tap("Research the company", timeout=40)
    s.wait("Research again", timeout=40)
    s.tap("Write the letters")
    s.tap("Approve and draft", timeout=40)
    if s.find("Check this draft", exact=True) is not None:
        s.tap("Check this draft", exact=True)
    s.wait("Check again", timeout=60)
    # The rewrite waits until every comment is approved and every question answered or skipped.
    # Comments are grouped by category; "CV accuracy · 1" still has one open.
    pending_category = re.compile(r".+ · \d+$")
    for _ in range(30):
        node = s.find_scrolling(lambda t: t in ("Skip, no answer", "Approve"))
        if node is None:
            node = s.find_scrolling(lambda t: bool(pending_category.match(t)))
        if node is None:
            break
        s.tap_node(node)
    s.tap("Approve draft", exact=True, timeout=60)
    s.tap("Use this letter", timeout=60)
    s.tap("Save", exact=True, timeout=30)
    s.wait("Save again", timeout=30)
    s.shot("01b-saved-letter")
    print("ok: a letter written from scratch in demo mode (fixtures) and saved")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--serial")
    parser.add_argument("--apk", type=Path, help="install this APK first")
    parser.add_argument("--fresh", action="store_true", help="clear the app's data first (emulators: this signs you out)")
    parser.add_argument("--out", type=Path, default=REPO / "temp/android-smoke")
    args = parser.parse_args()

    s = Smoke(args.serial, args.out)
    if args.apk:
        print("install", s.adb("install", "-r", str(args.apk)).strip().splitlines()[-1])
    if args.fresh:
        s.adb("shell", "pm", "clear", PKG)
        # The keep-alive notification asks once; answer it up front like a user would.
        s.adb("shell", "pm", "grant", PKG, "android.permission.POST_NOTIFICATIONS", check=False)
    s.adb("logcat", "-c")

    s.launch("--ez", DEMO_EXTRA, "false")
    if s.find("Try the demo") is not None:
        s.tap("Try the demo")
        print("ok: demo mode from the sign-in screen")
    else:
        s.launch("--ez", DEMO_EXTRA, "true")
        print("ok: demo mode from the adb flag (already signed in)")
    s.wait("Demo mode")
    s.shot("01-demo-write")

    write_from_scratch(s)

    s.tap("Menu", exact=True)
    s.tap("Job pipeline")
    s.wait("Ready")
    s.shot("02-pipeline")
    s.tap("Ready")
    s.tap("Open the drafts")
    s.wait("Claude Code")
    s.shot("03-desktop-drafts")
    print("ok: a ready job opens with the desktop drafts")
    # Paragraph review: redraft one paragraph now (a fixture reply in demo mode).
    node = s.find_scrolling(lambda t: t in ("Redraft", "Try another version"))
    if node is None:
        raise SystemExit("FAIL: the paragraph review offers no redraft")
    s.tap_node(node)
    s.wait("Redrafted", timeout=60)
    s.shot("03b-paragraph-redrafted")
    print("ok: a desktop paragraph is redrafted on the phone")

    s.tap("Leave demo")
    s.wait_gone("Demo mode")
    s.shot("04-left-demo")
    print("ok: leaving demo returns to the real account (or sign-in)")

    s.launch("--ez", DEMO_EXTRA, "true")
    s.wait("Demo mode")
    s.wait("Job offer text or link")  # a new demo starts without the previous demo's letter
    s.adb("shell", "am", "force-stop", PKG)
    s.launch()
    s.wait("Demo mode")
    s.shot("05-demo-after-restart")
    print("ok: adb flag enters demo, and demo survives a restart")

    s.launch("--ez", DEMO_EXTRA, "false")
    s.wait_gone("Demo mode")
    s.check_no_crash()
    print(f"PASS (screenshots in {s.out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
