"""Firestore ``opportunities``: the bus between the mail routine, the batch, the web app and the phone.

See OPPORTUNITY_PIPELINE_PLAN.md §3 and §4.3. Keys and document ids must match the Android app
(``app/app/src/main/java/io/github/fdondi/letterwriter/data/OpportunityKeys.kt``); both sides are
tested against ``letter_writer/tests/fixtures/opportunity_keys.json``.

Drafts live in the subdocument ``opportunities/{id}/state/session`` (the cookie-session dict without
``cv_text``), so the parent stays small and cheap to list.
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from google.cloud import firestore

from .firestore_store import firestore_safe_for_write, get_firestore_client

logger = logging.getLogger(__name__)

COLLECTION = "opportunities"
STATE_COLLECTION = "state"
STATE_DOC = "session"

PROPOSED = "proposed"
SKIPPED = "skipped"
APPROVED = "approved"
CAPTURED = "captured"
DRAFTING = "drafting"
READY = "ready"
FAILED = "failed"
DONE = "done"
APPLIED = "applied"
STATUSES = (PROPOSED, SKIPPED, APPROVED, CAPTURED, DRAFTING, READY, FAILED, DONE, APPLIED)

# Every move any writer (batch, web API, phone) may make. The phone's rules in OpportunityStore.kt
# are a subset of this table.
ALLOWED_TRANSITIONS: Dict[str, frozenset] = {
    PROPOSED: frozenset({APPROVED, SKIPPED, CAPTURED, DONE, APPLIED}),
    SKIPPED: frozenset({PROPOSED, APPROVED, CAPTURED, DONE, APPLIED}),
    APPROVED: frozenset({PROPOSED, SKIPPED, CAPTURED, DONE, APPLIED}),
    CAPTURED: frozenset({APPROVED, SKIPPED, DRAFTING, DONE, APPLIED}),
    DRAFTING: frozenset({READY, FAILED, CAPTURED}),
    READY: frozenset({CAPTURED, SKIPPED, DONE, APPLIED}),
    FAILED: frozenset({CAPTURED, SKIPPED, DONE, APPLIED}),
    DONE: frozenset({APPLIED}),
    APPLIED: frozenset(),
}

# States in which new posting text replaces the capture and queues the job for drafting.
RECAPTURABLE = frozenset({PROPOSED, APPROVED, SKIPPED, CAPTURED, FAILED})

# Status order for "never downgrade" when a proposal is seen again.
_STATUS_RANK = {s: i for i, s in enumerate((PROPOSED, SKIPPED, APPROVED, CAPTURED, DRAFTING, FAILED, READY, DONE, APPLIED))}


class TransitionError(Exception):
    """The opportunity is not in a state that allows the requested move."""


class OwnershipError(PermissionError):
    """The opportunity belongs to another user."""


# --- keys -----------------------------------------------------------------------------------

TRACKING_PARAMS = frozenset({"source", "uid", "mid", "trk", "refid", "trackingid", "gclid", "fbclid"})
_UUID_IN_PATH = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
_LINKEDIN_VIEW = re.compile(r"/jobs/view/(?:[^/]*?-)?([0-9]+)(?:/|$)")
_SWISSDEVJOBS_PATH = re.compile(r"^/jobs/([^/]+)")
_JOBCLOUD_HOSTS = ("jobs.ch", "jobup.ch", "jobscout24.ch")

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_ILLEGAL_ASCII = set(' "<>\\^`{|}')
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_IPV4 = re.compile(r"^(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])(\.(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])){3}$")
_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?$")
# Java's `\s` (Kotlin `Regex("\\s+")`) is ASCII whitespace only.
_ASCII_WS = re.compile(r"[ \t\n\x0b\f\r]+")


@dataclass(frozen=True)
class _Uri:
    scheme: str
    host: str  # as written
    port: int  # -1 when absent
    raw_path: str
    raw_query: Optional[str]


def _illegal_char(c: str) -> bool:
    o = ord(c)
    if o < 0x80:
        return o < 0x20 or o == 0x7F or c in _ILLEGAL_ASCII
    # java.net.URI "other": not an ISO control and not a space char.
    return unicodedata.category(c) in ("Cc", "Zs", "Zl", "Zp")


def _java_hostname_ok(host: str) -> bool:
    if host.startswith("["):
        return host.endswith("]") and len(host) > 2
    if _IPV4.match(host):
        return True
    labels = host[:-1].split(".") if host.endswith(".") else host.split(".")
    if not labels or not all(_LABEL.match(label) for label in labels):
        return False
    # A qualified hostname's rightmost label must start with a letter.
    return len(labels) == 1 or labels[-1][0].isalpha()


def _parse_uri(url: str) -> Optional[_Uri]:
    """What ``java.net.URI(url)`` yields for scheme/host/port/rawPath/rawQuery, or None where the
    Kotlin side gets an exception, a null scheme or a null (registry-based) host."""
    if any(_illegal_char(c) for c in url) or _BAD_ESCAPE.search(url):
        return None
    m = _SCHEME.match(url)
    if not m:
        return None
    scheme, rest = m.group(1), url[m.end():]
    fragment_at = rest.find("#")
    if fragment_at >= 0:
        if "#" in rest[fragment_at + 1:]:
            return None
        rest = rest[:fragment_at]
    if not rest.startswith("//"):
        return None
    rest = rest[2:]
    end = min([i for i in (rest.find("/"), rest.find("?")) if i >= 0] or [len(rest)])
    authority, rest = rest[:end], rest[end:]
    raw_path, sep, query = rest.partition("?")
    if "[" in raw_path or "]" in raw_path or "[" in query or "]" in query:
        return None
    hostport = authority.rpartition("@")[2]
    if hostport.startswith("["):
        close = hostport.find("]")
        if close < 0:
            return None
        host, port_part = hostport[: close + 1], hostport[close + 1:]
    else:
        host, _, port_text = hostport.partition(":")
        port_part = ":" + port_text if ":" in hostport else ""
    if not host or not _java_hostname_ok(host):
        return None
    port = -1
    if port_part:
        digits = port_part[1:]
        if not port_part.startswith(":") or (digits and not digits.isdigit()) or not digits.isascii():
            return None
        port = int(digits) if digits else -1
    return _Uri(scheme=scheme, host=host, port=port, raw_path=raw_path, raw_query=query if sep else None)


def _query_params(uri: _Uri) -> List[Tuple[str, str]]:
    out = []
    for part in (uri.raw_query or "").split("&"):
        if part:
            name, sep, value = part.partition("=")
            out.append((name, value if sep else ""))
    return out


def _is_tracking(name: str) -> bool:
    n = name.lower()
    return n.startswith("utm_") or n in TRACKING_PARAMS


def _normalized_url(uri: _Uri, host: str) -> str:
    scheme = (uri.scheme or "https").lower()
    path = uri.raw_path
    if len(path) > 1:
        path = path.rstrip("/")
    kept = sorted((kv for kv in _query_params(uri) if not _is_tracking(kv[0])), key=lambda kv: (kv[0], kv[1]))
    query = ("?" + "&".join(k if not v else f"{k}={v}" for k, v in kept)) if kept else ""
    port = f":{uri.port}" if uri.port > 0 else ""
    return f"{scheme}://{host}{port}{path}{query}"


def _key_host(uri: _Uri) -> str:
    host = uri.host.lower()
    return host[4:] if host.startswith("www.") else host


def _on_host(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def canonical_key(raw_url: str) -> str:
    """jobs.ch / jobup.ch / JobScout24 by vacancy UUID (``jobs.ch:<uuid>``), LinkedIn by job id,
    swissdevjobs by slug; anything else ``url:`` + scheme, host, path and non-tracking query, lowercased."""
    url = (raw_url or "").strip()
    uri = _parse_uri(url)
    if uri is None:
        return "url:" + url.lower()
    host = _key_host(uri)
    path = uri.raw_path
    if any(_on_host(host, h) for h in _JOBCLOUD_HOSTS):
        m = _UUID_IN_PATH.search(path.lower())
        if m:
            return f"jobs.ch:{m.group(1)}"
    if _on_host(host, "linkedin.com"):
        m = _LINKEDIN_VIEW.search(path)
        if m:
            return f"linkedin:{m.group(1)}"
        for name, value in _query_params(uri):
            if name.lower() == "currentjobid" and value and value.isdecimal():
                return f"linkedin:{value}"
    if _on_host(host, "swissdevjobs.ch"):
        m = _SWISSDEVJOBS_PATH.search(path)
        if m:
            return f"swissdevjobs:{m.group(1).lower()}"
    return "url:" + _normalized_url(uri, host).lower()


def clean_url(raw_url: str) -> str:
    """The URL as stored on the opportunity: tracking parameters and fragment removed, case kept."""
    url = (raw_url or "").strip()
    uri = _parse_uri(url)
    return url if uri is None else _normalized_url(uri, uri.host)


def text_key(text: str) -> str:
    """Key for a posting with no link: ``text:`` + sha256 of its whitespace-collapsed text, 16 hex chars."""
    words = [w for w in _ASCII_WS.split((text or "").strip()) if w]
    return "text:" + _sha256(" ".join(words))[:16]


def document_id(user_id: str, key: str) -> str:
    """``opportunities`` document id: sha256 of ``"<user_id>\\n<canonical_key>"``, first 32 hex chars."""
    return _sha256(f"{user_id}\n{key}")[:32]


def source_of(key: str) -> str:
    prefix = key.split(":", 1)[0]
    return prefix if prefix in ("jobs.ch", "linkedin", "swissdevjobs") else "manual"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- store ----------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def check_transition(current: str, target: str, from_states: Optional[Iterable[str]] = None) -> None:
    if from_states is not None and current not in set(from_states):
        raise TransitionError(f"Opportunity is '{current}', expected one of {sorted(set(from_states))}")
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise TransitionError(f"Cannot move an opportunity from '{current}' to '{target}'")


# The capture lives on the parent document (1 MiB limit, streamed by every list): long text is
# cut, and HTML too large to keep is dropped (extraction then works from the text).
MAX_CAPTURE_TEXT_CHARS = 100_000
MAX_CAPTURE_HTML_CHARS = 300_000


def capture_payload(text: str, via: str, html: Optional[str] = None, at: Optional[datetime] = None) -> Dict[str, Any]:
    kept_html = html if html and len(html) <= MAX_CAPTURE_HTML_CHARS else None
    return {"text": (text or "").strip()[:MAX_CAPTURE_TEXT_CHARS], "html": kept_html, "captured_at": at or _now(), "via": via}


class OpportunityStore:
    """All reads and writes of ``opportunities``. Status changes run in transactions."""

    def __init__(self, db: Optional[firestore.Client] = None, collection: str = COLLECTION) -> None:
        self._db = db
        self._collection_name = collection

    @property
    def db(self) -> firestore.Client:
        if self._db is None:
            self._db = get_firestore_client()
        return self._db

    def _col(self):
        return self.db.collection(self._collection_name)

    def _ref(self, opp_id: str):
        return self._col().document(opp_id)

    @staticmethod
    def _to_dict(snap) -> Dict[str, Any]:
        data = dict(snap.to_dict() or {})
        data["id"] = snap.id
        return data

    @staticmethod
    def _check_owner(data: Dict[str, Any], user_id: Optional[str], opp_id: str) -> None:
        if user_id is not None and data.get("user_id") != user_id:
            raise OwnershipError(f"Opportunity {opp_id} belongs to a different user")

    # reads

    def get(self, opp_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        snap = self._ref(opp_id).get()
        if not snap.exists:
            return None
        data = self._to_dict(snap)
        self._check_owner(data, user_id, opp_id)
        return data

    def list_for_user(self, user_id: str, statuses: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Most recently changed first."""
        query = self._col().where(filter=firestore.FieldFilter("user_id", "==", user_id))
        items = [self._to_dict(s) for s in query.stream()]
        if statuses:
            wanted = set(statuses)
            items = [i for i in items if i.get("status") in wanted]
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        items.sort(key=lambda i: (_as_utc(i.get("updated_at")) or _as_utc(i.get("created_at")) or epoch, i["id"]), reverse=True)
        return items

    def list_by_status(self, status: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = self._col().where(filter=firestore.FieldFilter("status", "==", status))
        items = [self._to_dict(s) for s in query.stream()]
        return [i for i in items if user_id is None or i.get("user_id") == user_id]

    def find_by_key(self, user_id: str, key: str) -> Optional[Dict[str, Any]]:
        return self.get(document_id(user_id, key), user_id)

    # creation

    def upsert_proposed(
        self,
        user_id: str,
        *,
        url: str,
        title: str = "",
        company: str = "",
        location: str = "",
        alert_message_id: Optional[str] = None,
        source: Optional[str] = None,
        status: str = PROPOSED,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, bool]:
        """Create a job in ``status`` (``proposed``; ``applied`` or ``skipped`` when the history says
        you already applied) with ``extra`` fields, or merge into the existing one with the same key
        (fills empty fields, adds the alert id, never changes the status). Returns (id, created)."""
        key = canonical_key(url)
        opp_id = document_id(user_id, key)
        ref = self._ref(opp_id)
        now = _now()

        @firestore.transactional
        def run(tx) -> bool:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                tx.set(
                    ref,
                    {
                        "user_id": user_id,
                        "canonical_key": key,
                        "source": source or source_of(key),
                        "url": clean_url(url),
                        "title": (title or "").strip(),
                        "company": (company or "").strip(),
                        "location": (location or "").strip(),
                        "status": status,
                        "skip_reason": None,
                        "alert_message_ids": [alert_message_id] if alert_message_id else [],
                        "capture": None,
                        "created_at": now,
                        "updated_at": now,
                        **(extra or {}),
                    },
                )
                return True
            data = snap.to_dict() or {}
            self._check_owner(data, user_id, opp_id)
            update: Dict[str, Any] = {}
            for field, value in (("title", title), ("company", company), ("location", location), ("url", clean_url(url))):
                if value and not str(data.get(field) or "").strip():
                    update[field] = value.strip()
            if alert_message_id and alert_message_id not in (data.get("alert_message_ids") or []):
                update["alert_message_ids"] = firestore.ArrayUnion([alert_message_id])
            if update:
                update["updated_at"] = now
                tx.update(ref, update)
            return False

        return opp_id, run(self.db.transaction())

    def capture(
        self,
        user_id: str,
        *,
        url: str = "",
        text: str = "",
        html: Optional[str] = None,
        via: str,
        title: str = "",
        company: str = "",
        vendors_requested: Optional[Sequence[str]] = None,
    ) -> Tuple[str, str, str]:
        """Same rules as the phone's ``OpportunityRules.planCapture``: a new job is ``captured`` with
        text or ``approved`` with only a link; an existing one gets the text unless it is drafting,
        ready or done. Returns (id, status, message)."""
        url, text = (url or "").strip(), (text or "").strip()
        if not url and not text:
            raise ValueError("Paste the job text or a link first.")
        key = canonical_key(url) if url else text_key(text)
        opp_id = document_id(user_id, key)
        ref = self._ref(opp_id)
        now = _now()
        cap = capture_payload(text, via, html, now) if text else None
        vendors = list(dict.fromkeys(vendors_requested or []))

        @firestore.transactional
        def run(tx) -> Tuple[str, str]:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                status = CAPTURED if cap else APPROVED
                fields: Dict[str, Any] = {
                    "user_id": user_id,
                    "canonical_key": key,
                    "source": source_of(key),
                    "url": clean_url(url) if url else "",
                    "title": (title or "").strip(),
                    "company": (company or "").strip(),
                    "location": "",
                    "status": status,
                    "skip_reason": None,
                    "alert_message_ids": [],
                    "capture": cap,
                    "created_at": now,
                    "updated_at": now,
                }
                if vendors:
                    fields["vendors_requested"] = vendors
                tx.set(ref, fields)
                return status, ("Saved. The desktop drafts it on its next run." if cap else "Link saved. Paste the posting text when you have it.")
            data = snap.to_dict() or {}
            self._check_owner(data, user_id, opp_id)
            return self._plan_update(tx, ref, data, cap, url, vendors, now)

        status, message = run(self.db.transaction())
        return opp_id, status, message

    def attach_capture(self, opp_id: str, user_id: str, *, text: str, via: str, html: Optional[str] = None) -> Tuple[str, str]:
        """Attach posting text to an existing job and queue it. Returns (status, message)."""
        if not (text or "").strip():
            raise ValueError("Paste the posting text first.")
        ref = self._ref(opp_id)
        now = _now()

        @firestore.transactional
        def run(tx) -> Tuple[str, str]:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise KeyError(f"Job {opp_id} no longer exists.")
            data = snap.to_dict() or {}
            self._check_owner(data, user_id, opp_id)
            return self._plan_update(tx, ref, data, capture_payload(text, via, html, now), "", [], now)

        return run(self.db.transaction())

    @staticmethod
    def _plan_update(tx, ref, data, cap, url, vendors, now) -> Tuple[str, str]:
        current = data.get("status") or ""
        if current == DRAFTING:
            return current, "The desktop is drafting this job right now."
        if current == READY:
            return current, "Drafts for this job are already ready."
        if current in (DONE, APPLIED):
            return current, "This job is already done."
        if cap is None:
            if current not in (PROPOSED, SKIPPED):
                return current, "This job is already in the pipeline."
            tx.update(ref, {"status": APPROVED, "skip_reason": None, "updated_at": now})
            return APPROVED, "Approved. Paste the posting text when you have it."
        fields: Dict[str, Any] = {"status": CAPTURED, "capture": cap, "skip_reason": None, "updated_at": now}
        if vendors:
            fields["vendors_requested"] = vendors
        if not (data.get("url") or "") and url:
            fields["url"] = clean_url(url)
        tx.update(ref, fields)
        verb = "replaced" if current == CAPTURED else "attached"
        return CAPTURED, f"Posting text {verb}. The desktop drafts it on its next run."

    # status changes

    def set_status(
        self,
        opp_id: str,
        to_state: str,
        *,
        from_states: Optional[Iterable[str]] = None,
        user_id: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Move ``opp_id`` to ``to_state`` in a transaction; raises :class:`TransitionError` when the
        job is not in ``from_states`` or the move is not in :data:`ALLOWED_TRANSITIONS`."""
        ref = self._ref(opp_id)
        allowed_from = list(from_states) if from_states is not None else None

        @firestore.transactional
        def run(tx) -> None:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise KeyError(f"Opportunity {opp_id} not found")
            data = snap.to_dict() or {}
            self._check_owner(data, user_id, opp_id)
            check_transition(data.get("status") or "", to_state, allowed_from)
            update = dict(fields or {})
            update["status"] = to_state
            update["updated_at"] = _now()
            tx.update(ref, update)

        run(self.db.transaction())
        return self.get(opp_id) or {}

    def update_fields(self, opp_id: str, fields: Dict[str, Any]) -> None:
        """Plain field update (no status change); for batch bookkeeping such as costs."""
        self._ref(opp_id).update({**fields, "updated_at": _now()})

    def claim_next_captured(
        self,
        owner: str,
        lease_s: float = 3600.0,
        *,
        user_id: Optional[str] = None,
        exclude: Iterable[str] = (),
    ) -> Optional[Dict[str, Any]]:
        """Take one ``captured`` job (oldest capture first), or a ``drafting`` one whose lease has
        expired (a crashed run), and mark it ``drafting`` under ``owner``'s lease."""
        skip = set(exclude)
        now = _now()
        candidates = [c for c in self.list_by_status(CAPTURED, user_id) if c["id"] not in skip]
        candidates += [
            c
            for c in self.list_by_status(DRAFTING, user_id)
            if c["id"] not in skip and (_as_utc((c.get("lease") or {}).get("until")) or now) <= now
        ]
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        candidates.sort(key=lambda c: (_as_utc((c.get("capture") or {}).get("captured_at")) or _as_utc(c.get("updated_at")) or epoch))
        for cand in candidates:
            if self._try_claim(cand["id"], owner, lease_s):
                return self.get(cand["id"])
        return None

    def _try_claim(self, opp_id: str, owner: str, lease_s: float) -> bool:
        ref = self._ref(opp_id)

        @firestore.transactional
        def run(tx) -> bool:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            now = _now()
            status = data.get("status")
            lease_until = _as_utc((data.get("lease") or {}).get("until"))
            if status == CAPTURED:
                pass
            elif status == DRAFTING and (lease_until is None or lease_until <= now):
                logger.info("Reclaiming %s: lease of %s expired", opp_id, (data.get("lease") or {}).get("owner"))
            else:
                return False
            tx.update(
                ref,
                {
                    "status": DRAFTING,
                    "lease": {"owner": owner, "until": now + timedelta(seconds=lease_s)},
                    "updated_at": now,
                },
            )
            return True

        return run(self.db.transaction())

    def finish_drafting(self, opp_id: str, owner: str, to_state: str, fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """End ``owner``'s lease, moving the job to ``ready`` or ``failed`` (or back to ``captured``)."""
        if to_state not in ALLOWED_TRANSITIONS[DRAFTING]:
            raise TransitionError(f"Drafting cannot end in '{to_state}'")
        ref = self._ref(opp_id)

        @firestore.transactional
        def run(tx) -> None:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise KeyError(f"Opportunity {opp_id} not found")
            data = snap.to_dict() or {}
            if data.get("status") != DRAFTING or (data.get("lease") or {}).get("owner") != owner:
                raise TransitionError(f"Opportunity {opp_id} is no longer leased to {owner}")
            update = dict(fields or {})
            update.update({"status": to_state, "lease": None, "progress": None, "updated_at": _now()})
            tx.update(ref, update)

        run(self.db.transaction())
        return self.get(opp_id) or {}

    def report_progress(self, opp_id: str, owner: str, progress: Dict[str, Any]) -> bool:
        """How far a drafting job got (``progress``: step, vendors done, started), for the apps.
        Written only while ``owner`` still holds the lease; returns whether it was written."""
        ref = self._ref(opp_id)

        @firestore.transactional
        def run(tx) -> bool:
            snap = ref.get(transaction=tx)
            data = (snap.to_dict() or {}) if snap.exists else None
            if not data or data.get("status") != DRAFTING or (data.get("lease") or {}).get("owner") != owner:
                return False
            tx.update(ref, {"progress": progress})
            return True

        return run(self.db.transaction())

    # drafts

    def _state_ref(self, opp_id: str):
        return self._ref(opp_id).collection(STATE_COLLECTION).document(STATE_DOC)

    def save_state(self, opp_id: str, session: Dict[str, Any]) -> None:
        """Store the session dict (never ``cv_text``) as ``state/session``."""
        data = {k: v for k, v in dict(session).items() if k != "cv_text"}
        self._state_ref(opp_id).set(firestore_safe_for_write(data))

    def load_state(self, opp_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if user_id is not None and self.get(opp_id, user_id) is None:
            return None
        snap = self._state_ref(opp_id).get()
        return dict(snap.to_dict() or {}) if snap.exists else None
