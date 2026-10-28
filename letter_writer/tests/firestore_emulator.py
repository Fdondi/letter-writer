"""A local Cloud Firestore emulator for tests: no network, no real project.

Uses ``FIRESTORE_EMULATOR_HOST`` when already set; otherwise starts the emulator jar that the
Firebase CLI downloaded (``~/.cache/firebase/emulators``, or ``FIRESTORE_EMULATOR_JAR``) with a
small heap. Tests skip when neither Java nor the jar is available.
"""
from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

PROJECT = "demo-letter-writer-test"
# FIRESTORE_EMULATOR_HOST values that only block real Firestore (conftest), not a running emulator.
BLOCKED_HOSTS: set = set()


def _running_host() -> Optional[str]:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST")
    return host if host and host not in BLOCKED_HOSTS else None


def _jar() -> Optional[str]:
    explicit = os.environ.get("FIRESTORE_EMULATOR_JAR")
    if explicit and Path(explicit).is_file():
        return explicit
    jars = sorted(glob.glob(str(Path.home() / ".cache/firebase/emulators/cloud-firestore-emulator-*.jar")))
    return jars[-1] if jars else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_up(host: str, timeout_s: float = 40.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://{host}/", timeout=1).read()
            return True
        except Exception:
            time.sleep(0.3)
    return False


def unavailable_reason() -> Optional[str]:
    if _running_host():
        return None
    if not shutil.which("java"):
        return "java not installed"
    if not _jar():
        return "Firestore emulator jar not found (run `firebase setup:emulators:firestore`)"
    return None


@contextmanager
def running_emulator() -> Iterator[str]:
    """Yields ``host:port`` with ``FIRESTORE_EMULATOR_HOST`` set for the duration."""
    existing = _running_host()
    if existing:
        yield existing
        return
    previous = os.environ.get("FIRESTORE_EMULATOR_HOST")
    port = _free_port()
    host = f"127.0.0.1:{port}"
    proc = subprocess.Popen(
        ["java", "-Xmx384m", "-jar", str(_jar()), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_up(host):
            raise RuntimeError("Firestore emulator did not start")
        os.environ["FIRESTORE_EMULATOR_HOST"] = host
        yield host
    finally:
        if previous is None:
            os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
        else:
            os.environ["FIRESTORE_EMULATOR_HOST"] = previous
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def client():
    from google.cloud import firestore

    return firestore.Client(project=PROJECT)
