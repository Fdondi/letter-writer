"""Deterministic parsers for job-alert mail (plain-text bodies as Gmail's PLAIN_TEXT returns them).

OPPORTUNITY_PIPELINE_PLAN.md §4.4. Mail is data: nothing here follows links or interprets
instructions; an unknown sender is reported as unparsed, never guessed at.

One mail is ``{message_id, sender, subject, date, body}``; the result lists job proposals and
application events (LinkedIn "application sent" and "viewed"). Mail from any other sender is left
to :mod:`experimental.email.application_tracking`, which reads it with a model.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from email.utils import parseaddr
from typing import Any, Callable, Dict, List, Optional

from experimental.email.application_tracking import ApplicationEvent
from letter_writer.opportunity_store import canonical_key


@dataclass
class JobProposal:
    url: str
    title: str = ""
    company: str = ""
    location: str = ""


@dataclass
class AlertResult:
    message_id: str
    parser: str
    proposals: List[JobProposal] = field(default_factory=list)
    events: List[ApplicationEvent] = field(default_factory=list)
    reason: str = ""

    @property
    def unparsed(self) -> bool:
        return self.parser == "unparsed"


_SEPARATOR = re.compile(r"^-{5,}")
_LINKEDIN_VIEW_LINE = re.compile(r"^View job:\s*(https?://\S+)")
_LINKEDIN_HEADERS = (
    "your job alert for",
    "new jobs match your preferences",
    "new jobs from your other alerts",
    "view similar jobs you may be interested in",
    "your application was sent to",
    "apply to your saved jobs",
)
_APPLIED = re.compile(r"your application was sent to\s+(.+?)\s*$", re.I | re.M)
_VIEWED = re.compile(r"your application was viewed by\s+(.+?)\s*$", re.I | re.M)
# "Your application to <title> at <company>": an update whose plain text says only "Your update from
# <company>"; the kind is in LinkedIn's tracking parameter (email_jobs_application_rejected_01, …).
_UPDATE_SUBJECT = re.compile(r"^\s*your application to\s+(.+)\s+at\s+(.+?)\s*$", re.I)
_UPDATE_KIND = re.compile(r"email_jobs_application_([a-z]+?)_\d+", re.I)
_UPDATE_KINDS = {"rejected": "rejection", "viewed": "viewed", "sent": "applied"}
_APPLICATION_SUBJECT = re.compile(r"\b(your application|ihre bewerbung|deine bewerbung|votre candidature)\b", re.I)
_JOBS_CH_LINE = re.compile(r"^(?P<title>.+?)\s+-\s+(?P<url>https?://(?:www\.)?(?:jobs\.ch|jobup\.ch|jobscout24\.ch)/\S*/detail/\S+)\s*$")
_SWISSDEVJOBS_URL = re.compile(r"https?://(?:www\.)?swissdevjobs\.ch/jobs/[^\s?#]+(?:\?\S*)?")


def _clean(text: str) -> str:
    """Unescaped, tag-free, emoji-free text with collapsed spaces."""
    text = re.sub(r"<[^>]+>", "", html.unescape(text or ""))
    text = "".join(c for c in text if unicodedata.category(c) not in ("So", "Cf"))
    return " ".join(text.split())


def _sender_address(sender: str) -> str:
    return (parseaddr(sender or "")[1] or sender or "").strip().lower()


def _lines(body: str) -> List[str]:
    return html.unescape(body or "").replace("\r\n", "\n").split("\n")


def _dedupe(proposals: List[JobProposal]) -> List[JobProposal]:
    seen, out = set(), []
    for p in proposals:
        key = canonical_key(p.url)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _linkedin_blocks(body: str, *, limit: Optional[int] = None) -> List[JobProposal]:
    """Each ``View job: <url>`` line closes a block whose first three text lines are title,
    company and location (badges such as "Fast growing" follow them)."""
    lines = _lines(body)
    out: List[JobProposal] = []
    for i, line in enumerate(lines):
        m = _LINKEDIN_VIEW_LINE.match(line.strip())
        if not m:
            continue
        block: List[str] = []
        j = i - 1
        while j >= 0:
            prev = lines[j].strip()
            low = prev.lower()
            if _SEPARATOR.match(prev) or "http" in low or prev.startswith("<") or low.startswith(_LINKEDIN_HEADERS):
                break
            if prev:
                block.append(prev)
            j -= 1
        block.reverse()
        if not block or "/jobs/view/" not in m.group(1):
            continue
        texts = [_clean(b) for b in block]
        out.append(
            JobProposal(
                url=m.group(1),
                title=texts[0] if len(texts) > 0 else "",
                company=texts[1] if len(texts) > 1 else "",
                location=texts[2] if len(texts) > 2 else "",
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def parse_jobs_ch(mail: Dict[str, Any]) -> AlertResult:
    """``Title - <detail url>`` followed by ``Company, City``."""
    lines = _lines(mail.get("body", ""))
    proposals: List[JobProposal] = []
    for i, line in enumerate(lines):
        m = _JOBS_CH_LINE.match(line.strip())
        if not m:
            continue
        company = location = ""
        nxt = next((l.strip() for l in lines[i + 1 : i + 3] if l.strip()), "")
        if nxt and "http" not in nxt:
            company, _, location = nxt.rpartition(", ")
            if not company:
                company, location = location, ""
        proposals.append(JobProposal(url=m.group("url"), title=_clean(m.group("title")), company=_clean(company), location=_clean(location)))
    return AlertResult(str(mail.get("message_id", "")), "jobs.ch", _dedupe(proposals))


def parse_linkedin_alert(mail: Dict[str, Any]) -> AlertResult:
    """Job alert digests: every job of every alert in the mail."""
    return AlertResult(str(mail.get("message_id", "")), "linkedin", _dedupe(_linkedin_blocks(mail.get("body", ""))))


def parse_linkedin_jobs_mail(mail: Dict[str, Any]) -> AlertResult:
    """``jobs-noreply``: "your application was sent to" / "was viewed by" are application events
    about the first job in the mail (the "similar jobs" below it are ignored); saved-job
    reminders and "is hiring" mails list jobs like an alert."""
    body = mail.get("body", "")
    subject = mail.get("subject", "")
    message_id = str(mail.get("message_id", ""))
    update = _UPDATE_SUBJECT.match(subject or "")
    if update:
        marker = _UPDATE_KIND.search(body or "")
        kind = _UPDATE_KINDS.get(marker.group(1).lower(), "") if marker else ""
        if not kind:  # an update LinkedIn does not label: let the classifier read it
            return AlertResult(message_id, "unparsed", reason="LinkedIn application update without a known kind")
        company = _clean(update.group(2))
        event = ApplicationEvent(kind=kind, company=company, job_title=_clean(update.group(1)), summary=f"LinkedIn: {kind} by {company}.")
        return AlertResult(message_id, f"linkedin_{kind}", events=[event])
    for pattern, kind in ((_APPLIED, "applied"), (_VIEWED, "viewed")):
        m = pattern.search(subject) or pattern.search(html.unescape(body))
        if m:
            first = _linkedin_blocks(body, limit=1)
            job = first[0] if first else None
            company = _clean(m.group(1)) or (job.company if job else "")
            event = ApplicationEvent(
                kind=kind,
                company=company,
                job_title=job.title if job else "",
                job_url=job.url if job else "",
                summary=f"LinkedIn: application {'sent to' if kind == 'applied' else 'viewed by'} {company}.",
            )
            return AlertResult(message_id, f"linkedin_{kind}", events=[event])
    return AlertResult(message_id, "linkedin_jobs", _dedupe(_linkedin_blocks(body)))


def parse_swissdevjobs(mail: Dict[str, Any]) -> AlertResult:
    """``Title - Company`` above each job link, location on the line below."""
    lines = _lines(mail.get("body", ""))
    proposals: List[JobProposal] = []
    for i, line in enumerate(lines):
        m = _SWISSDEVJOBS_URL.search(line)
        if not m or "unsubscribe" in line.lower():
            continue
        above = next((l.strip() for l in reversed(lines[max(0, i - 2) : i]) if l.strip()), "")
        below = next((l.strip() for l in lines[i + 1 : i + 2] if l.strip()), "")
        title, _, company = above.rpartition(" - ") if " - " in above else (above, "", "")
        proposals.append(JobProposal(url=m.group(0), title=_clean(title), company=_clean(company), location=_clean(below.split(",")[0])))
    return AlertResult(str(mail.get("message_id", "")), "swissdevjobs", _dedupe(proposals))


Parser = Callable[[Dict[str, Any]], AlertResult]


def parser_for(sender: str) -> Optional[Parser]:
    address = _sender_address(sender)
    if address in ("info@jobs.ch", "info@jobup.ch"):
        return parse_jobs_ch
    if address == "jobalerts-noreply@linkedin.com":
        return parse_linkedin_alert
    if address == "jobs-noreply@linkedin.com":
        return parse_linkedin_jobs_mail
    if address.endswith("@swissdevjobs.ch"):
        return parse_swissdevjobs
    return None


def parse_alert(mail: Dict[str, Any]) -> AlertResult:
    message_id = str(mail.get("message_id", ""))
    parser = parser_for(str(mail.get("sender", "")))
    # Job boards also mail about your applications (e.g. "Your application at Scalera AG"):
    # those go to the classifier, not the alert parser. LinkedIn's are handled by its parser.
    if parser in (parse_jobs_ch, parse_swissdevjobs) and _APPLICATION_SUBJECT.search(str(mail.get("subject") or "")):
        return AlertResult(message_id, "unparsed", reason="job board mail about an application")
    if parser is None:
        return AlertResult(message_id, "unparsed", reason=f"unknown sender {_sender_address(str(mail.get('sender', '')))!r}")
    try:
        return parser(mail)
    except Exception as exc:  # a malformed mail must not stop the others
        return AlertResult(message_id, "unparsed", reason=f"{parser.__name__} failed: {exc}")
