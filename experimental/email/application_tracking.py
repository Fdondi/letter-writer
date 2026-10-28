"""Applications after they leave: what you already applied to, and what the companies answered.

Three uses, all fed by a mail scan (experimental; see README.md in this folder):

* **History** (:class:`ApplicationHistory`): previous letters (``documents``) and recorded
  applications (``opportunities``), so a job you already applied to is not proposed again.
* **Mail events** (:func:`classify_mail`): a tool-less model call reads one email (data, never
  instructions) and says whether it is about an application and what happened.
* **Outcome** (:func:`apply_event`): the furthest stage reached (a sign of job fit), the result, and
  specific praise (a sign of letter quality), kept on the opportunity and its saved letter.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from pathlib import Path

from letter_writer import prompts
from letter_writer.clients.base import BaseClient, ModelRole

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")

# Furthest-stage order. "forwarded" is an agency passing the application to its client.
STAGES = ("applied", "received", "viewed", "forwarded", "screening", "interview", "final", "offer")
STAGE_RANK = {s: i for i, s in enumerate(STAGES)}
RESULTS = ("rejected", "offer", "withdrawn")
KINDS = ("applied", "received", "viewed", "forwarded", "screening", "interview", "final", "offer", "rejection", "withdrawn", "other")
_KIND_STAGE = {"applied": "applied", "received": "received", "viewed": "viewed", "forwarded": "forwarded", "screening": "screening",
               "interview": "interview", "final": "final", "offer": "offer"}

MAIL_SCHEMA: Dict[str, Any] = json.loads(_prompt("application_mail.json"))
_MAX_BODY_CHARS = 12_000


@dataclass
class ApplicationEvent:
    """Something that happened to one application, from one email."""

    kind: str  # one of KINDS
    company: str = ""
    job_title: str = ""
    job_url: str = ""
    agency: str = ""
    job_reference: str = ""
    positive_feedback: bool = False
    feedback_quote: str = ""
    summary: str = ""

    @property
    def stage(self) -> Optional[str]:
        return _KIND_STAGE.get(self.kind)


# --- names and titles ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = re.compile(
    r"\b(ag|sa|gmbh|sàrl|sarl|ltd|inc|llc|plc|s\.a\.|a\.g\.|group|holding|schweiz|switzerland|suisse|international)\b\.?", re.I
)
_TITLE_NOISE = re.compile(
    r"\((?:[mwfdxh]\s*/\s*)+[mwfdxh]\)|\b[mwfdxh]\s*/\s*[mwfdxh](?:\s*/\s*[mwfdxh])?\b|\d+\s*(?:-|–|bis|to)?\s*\d*\s*%|\bin\b|/in\b|:in\b|\*in\b",
    re.I,
)
_TITLE_STOPWORDS = frozenset({"and", "und", "et", "the", "der", "die", "das", "for", "a", "at", "of", "de", "la", "le", "contract", "temporary", "befristet"})


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def company_key(name: str) -> str:
    """Company name without legal suffixes, accents, punctuation or case."""
    s = _COMPANY_SUFFIXES.sub(" ", _fold(name))
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def companies_match(a: str, b: str) -> bool:
    """Same company: equal names once normalized, or one name is the start of the other
    ("Stadler" / "Stadler Rail") when the shorter one has at least 4 characters."""
    ka, kb = company_key(a).split(), company_key(b).split()
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    short, long = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    return len(" ".join(short)) >= 4 and long[: len(short)] == short


def title_tokens(title: str) -> frozenset:
    """Words of a job title without gender markers, workload percentages or filler words."""
    s = _TITLE_NOISE.sub(" ", _fold(title))
    words = re.sub(r"[^\w+#]+", " ", s).split()
    return frozenset(w for w in words if w not in _TITLE_STOPWORDS and not w.isdigit())


def titles_similar(a: str, b: str) -> bool:
    """Same job, judging by the title: one title's words contain the other's, or most words overlap."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    if ta <= tb or tb <= ta:
        return True
    return len(ta & tb) / len(ta | tb) >= 0.6


# --- history ------------------------------------------------------------------------------------


@dataclass
class HistoryEntry:
    source: str  # "letter" (a saved document) or "application" (an opportunity past proposing)
    id: str
    company: str
    title: str
    when: str
    status: str = ""
    canonical_key: str = ""


@dataclass
class HistoryMatch:
    entry: HistoryEntry
    exact: bool  # same posting (same link) rather than same company and a similar title

    @property
    def reason(self) -> str:
        what = "Letter" if self.entry.source == "letter" else "Application"
        when = f" on {self.entry.when[:10]}" if self.entry.when else ""
        title = f" for “{self.entry.title}”" if self.entry.title else ""
        return f"Already applied? {what} to {self.entry.company}{title}{when}."


# Opportunity states that mean you acted on the job (a proposal does not count).
_ACTED_STATES = frozenset({"applied", "done"})


@dataclass
class ApplicationHistory:
    entries: List[HistoryEntry] = field(default_factory=list)

    @classmethod
    def build(cls, opportunities: Iterable[Dict[str, Any]], documents: Iterable[Dict[str, Any]]) -> "ApplicationHistory":
        from letter_writer.opportunity_store import canonical_key

        entries: List[HistoryEntry] = []
        for o in opportunities:
            if o.get("status") in _ACTED_STATES or (o.get("outcome") or {}).get("events"):
                entries.append(
                    HistoryEntry(
                        "application",
                        str(o.get("id", "")),
                        str(o.get("company") or ""),
                        str(o.get("title") or ""),
                        str(o.get("updated_at") or o.get("created_at") or ""),
                        str(o.get("status") or ""),
                        str(o.get("canonical_key") or ""),
                    )
                )
        for d in documents:
            url = str(d.get("source_url") or "").strip()
            entries.append(
                HistoryEntry(
                    "letter",
                    str(d.get("id", "")),
                    str(d.get("company_name") or ""),
                    str(d.get("role") or d.get("job_title") or ""),
                    str(d.get("created_at") or ""),
                    canonical_key=canonical_key(url) if url else "",
                )
            )
        return cls(entries)

    def match(self, *, company: str = "", title: str = "", key: str = "") -> Optional[HistoryMatch]:
        """An exact match (same posting) first, else the same company with a similar title."""
        if key:
            for e in self.entries:
                if e.canonical_key and e.canonical_key == key:
                    return HistoryMatch(e, exact=True)
        for e in self.entries:
            if companies_match(company, e.company) and titles_similar(title, e.title):
                return HistoryMatch(e, exact=False)
        return None

    def same_company(self, company: str) -> List[HistoryEntry]:
        return [e for e in self.entries if companies_match(company, e.company)]


# --- mail classification -----------------------------------------------------------------------


class ClassificationError(RuntimeError):
    pass


def _clip(value: Any, n: int) -> str:
    return " ".join(str(value or "").split())[:n]


def parse_classification(raw: str) -> Optional[ApplicationEvent]:
    """The model's JSON as an event, or None for ``not_application``. Raises on unusable output."""
    text = (raw or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ClassificationError(f"no JSON in classifier output: {text[:200]!r}")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise ClassificationError(f"bad JSON in classifier output: {exc}") from exc
    if not isinstance(data, dict):
        raise ClassificationError("classifier output is not an object")
    kind = str(data.get("kind") or "").strip().lower()
    if kind == "not_application":
        return None
    if kind not in KINDS or kind == "applied":
        raise ClassificationError(f"unknown kind {kind!r}")
    positive = data.get("positive_feedback") is True
    return ApplicationEvent(
        kind=kind,
        company=_clip(data.get("company"), 120),
        job_title=_clip(data.get("job_title"), 200),
        job_url=_clip(data.get("job_url"), 2000) if str(data.get("job_url") or "").startswith(("http://", "https://")) else "",
        agency=_clip(data.get("agency"), 120),
        job_reference=_clip(data.get("job_reference"), 60),
        positive_feedback=positive,
        feedback_quote=_clip(data.get("feedback_quote"), 200) if positive else "",
        summary=_clip(data.get("summary"), 160),
    )


def classify_mail(mail: Dict[str, Any], client: BaseClient) -> Optional[ApplicationEvent]:
    """One tool-less model call on one email. None when it is not about an application."""
    user = prompts.fill(
        _prompt("application_user.txt"),
        "application_user.txt",
        sender=_clip(mail.get("sender"), 200),
        subject=_clip(mail.get("subject"), 300),
        date=_clip(mail.get("date"), 40),
        body=str(mail.get("body") or "")[:_MAX_BODY_CHARS],
    )
    raw = client.call(ModelRole.EXTRACTION, _prompt("application_system.txt"), [user], response_format=MAIL_SCHEMA)
    return parse_classification(raw)


# --- outcome ------------------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_event(outcome: Optional[Dict[str, Any]], event: ApplicationEvent, *, mail_id: str, at: str = "", sender: str = "") -> Dict[str, Any]:
    """The outcome after ``event``. Idempotent per mail id; stages only move forward."""
    out: Dict[str, Any] = dict(outcome or {})
    events: List[Dict[str, Any]] = [dict(e) for e in out.get("events") or [] if isinstance(e, dict)]
    if mail_id and any(e.get("mail_id") == mail_id for e in events):
        return out
    events.append(
        {
            "mail_id": mail_id,
            "at": at or _now_iso(),
            "kind": event.kind,
            "from": _clip(sender, 120),
            "summary": event.summary,
        }
    )
    events.sort(key=lambda e: str(e.get("at") or ""))
    out["events"] = events[-50:]

    stage = event.stage
    if stage and STAGE_RANK[stage] > STAGE_RANK.get(str(out.get("stage") or ""), -1):
        out["stage"] = stage
    if event.kind in ("interview", "final"):
        out["interviews"] = int(out.get("interviews") or 0) + 1
    if event.kind == "rejection":
        out["result"] = "rejected"
        out["rejected_at_stage"] = out.get("stage") or "applied"
    elif event.kind == "offer":
        out["result"] = "offer"
    elif event.kind == "withdrawn":
        out["result"] = "withdrawn"
    if event.positive_feedback:
        out["positive_feedback"] = True
        quotes = [q for q in out.get("feedback_quotes") or [] if isinstance(q, str)]
        if event.feedback_quote and event.feedback_quote not in quotes:
            quotes.append(event.feedback_quote)
        out["feedback_quotes"] = quotes[-5:]
    out.setdefault("stage", "applied")
    out["updated_at"] = _now_iso()
    return out


def outcome_summary(outcome: Optional[Dict[str, Any]]) -> str:
    """"interview ×2 · rejected · praised" style one-liner."""
    o = outcome or {}
    if not o:
        return ""
    parts = [str(o.get("stage") or "applied")]
    if int(o.get("interviews") or 0) > 1:
        parts[0] += f" ×{o['interviews']}"
    if o.get("result"):
        parts.append(str(o["result"]))
    if o.get("positive_feedback"):
        parts.append("praised")
    return " · ".join(parts)


def letter_outcome(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """What a saved letter keeps of its application's outcome (no mail text besides praise)."""
    return {
        "stage": outcome.get("stage") or "applied",
        "result": outcome.get("result"),
        "interviews": int(outcome.get("interviews") or 0),
        "positive_feedback": bool(outcome.get("positive_feedback")),
        "feedback_quotes": list(outcome.get("feedback_quotes") or []),
        "updated_at": outcome.get("updated_at") or _now_iso(),
    }


def summarize(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts for ``batch outcomes``: with and without a letter from this app."""
    def bucket(items):
        n = len(items)
        reached = lambda s: sum(1 for o in items if STAGE_RANK.get(str((o.get("outcome") or {}).get("stage") or "applied"), 0) >= STAGE_RANK[s])
        return {
            "applications": n,
            "screening_or_further": reached("screening"),
            "interview_or_further": reached("interview"),
            "offers": sum(1 for o in items if (o.get("outcome") or {}).get("result") == "offer"),
            "rejected": sum(1 for o in items if (o.get("outcome") or {}).get("result") == "rejected"),
            "praised": sum(1 for o in items if (o.get("outcome") or {}).get("positive_feedback")),
        }

    with_letter = [r for r in rows if r.get("document_id")]
    without = [r for r in rows if not r.get("document_id")]
    return {"with_letter": bucket(with_letter), "without_letter": bucket(without)}
