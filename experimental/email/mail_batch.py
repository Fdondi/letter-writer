"""Mail commands for the opportunity pipeline (experimental; README.md in this folder).

    python -m experimental.email.mail_batch propose --mail-file <path.jsonl> [--dry-run [--classify]]
    python -m experimental.email.mail_batch unseen <id>[:<sender>] …
    python -m experimental.email.mail_batch outcomes

One mail per line of the file: ``{message_id, sender, subject, date, body}``. Configuration as for
``python -m letter_writer.batch`` (``LW_USER_ID``, ``.env``).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from google.cloud.firestore import FieldFilter

from experimental.email import mail_store
from experimental.email.alert_parsing import parse_alert
from experimental.email.application_tracking import (
    ApplicationEvent,
    ApplicationHistory,
    classify_mail,
    companies_match,
    company_key,
    letter_outcome,
    outcome_summary,
    summarize,
    title_tokens,
    titles_similar,
)
from experimental.email.mail_store import MailOpportunityStore
from letter_writer import opportunity_store as ops
from letter_writer.batch import apply_host_defaults, user_id_from_env
from letter_writer.clients.base import ModelVendor

logger = logging.getLogger("experimental.email.mail_batch")

# Mail that is not a known alert or LinkedIn notice is kept here for manual review unless a
# classifier is given (--classify): templates first, intelligence only where they fall short.
REVIEW_DIR = Path(__file__).resolve().parent / "review"


def save_for_review(mail: Dict[str, Any], reason: str, review_dir: Optional[Path] = None) -> Path:
    folder = review_dir or REVIEW_DIR
    folder.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c for c in str(mail.get("message_id") or "unknown") if c.isalnum() or c in "-_")[:80]
    path = folder / f"{safe_id}.json"
    path.write_text(json.dumps({"reason": reason, **mail}, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def read_mail_file(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    mails, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            mail = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(mail, dict) and mail.get("message_id"):
            mails.append(mail)
        else:
            bad += 1
    return mails, bad


def preview_proposals(mails: Sequence[Dict[str, Any]], classifier: Optional["Classifier"] = None) -> List[Dict[str, Any]]:
    """What ``propose`` would do, without reading or writing Firestore. With ``classifier``, mail
    that is not an alert is classified too (a model call per mail)."""
    out: List[Dict[str, Any]] = []
    for mail in mails:
        result = parse_alert(mail)
        for p in result.proposals:
            out.append({"mail": mail.get("message_id"), "action": "propose", "key": ops.canonical_key(p.url), "title": p.title, "company": p.company, "location": p.location})
        for e in result.events:
            out.append({"mail": mail.get("message_id"), "action": e.kind, "key": ops.canonical_key(e.job_url) if e.job_url else "", "title": e.job_title, "company": e.company})
        if result.unparsed:
            row: Dict[str, Any] = {"mail": mail.get("message_id"), "action": "classify", "sender": mail.get("sender", ""), "subject": mail.get("subject", "")}
            if classifier is not None:
                try:
                    event = classifier(mail)
                    row["classified"] = "not_application" if event is None else {k: v for k, v in vars(event).items() if v}
                except Exception as exc:
                    row["classified"] = f"error: {exc}"[:300]
            out.append(row)
    return out


Classifier = Callable[[Dict[str, Any]], Optional[ApplicationEvent]]


def load_letters(user_id: str, collection=None) -> List[Dict[str, Any]]:
    """Your saved letters (``documents``), only the fields the history needs."""
    if collection is None:
        from .firestore_store import get_collection

        collection = get_collection()
    query = collection.where(filter=FieldFilter("user_id", "==", user_id)).select(["company_name", "role", "source_url", "created_at"])
    out = []
    for snap in query.stream():
        data = snap.to_dict() or {}
        data["id"] = snap.id
        out.append(data)
    return out


def default_classifier() -> Classifier:
    """Mail classification on ``LW_MAIL_CLASSIFIER_VENDOR``; default Claude Code when its CLI is
    installed (subscription), else OpenAI. One tool-less call per mail."""
    from .client import get_client
    from .clients.claude_code import claude_binary

    vendor = os.environ.get("LW_MAIL_CLASSIFIER_VENDOR") or ("claude_code" if claude_binary() else "openai")
    clients: List[Any] = []

    def classify(mail: Dict[str, Any]) -> Optional[ApplicationEvent]:
        if not clients:  # built on first use, so a missing key fails one mail, not the run
            clients.append(get_client(ModelVendor(vendor)))
        return classify_mail(mail, clients[0])

    return classify


def _event_key(event: ApplicationEvent) -> str:
    """Key for an application known only from mail: its posting link, else company + title (or reference)."""
    if event.job_url:
        return ops.canonical_key(event.job_url)
    what = " ".join(sorted(title_tokens(event.job_title))) or event.job_reference.lower() or "unknown position"
    return f"application:{company_key(event.company) or 'unknown company'}:{what}"


def _target_for_event(event: ApplicationEvent, jobs: List[Dict[str, Any]], history: ApplicationHistory) -> Dict[str, Any]:
    """Which job an application mail is about: the same posting, else the same company with a
    similar title (a single job at that company when the mail names no title), else a saved letter,
    else a new job keyed by company and title."""
    if event.job_url:
        key = ops.canonical_key(event.job_url)
        for job in jobs:
            if job.get("canonical_key") == key:
                return {"opp_id": job["id"]}
    if company_key(event.company):
        at_company = [j for j in jobs if companies_match(event.company, str(j.get("company") or "")) and j.get("status") != ops.SKIPPED]
        if event.job_title:
            for job in at_company:
                if titles_similar(event.job_title, str(job.get("title") or "")):
                    return {"opp_id": job["id"]}
        elif len(at_company) == 1:
            return {"opp_id": at_company[0]["id"]}
    match = history.match(company=event.company, title=event.job_title, key=ops.canonical_key(event.job_url) if event.job_url else "")
    if match and match.entry.source == "letter":
        return {"key": match.entry.canonical_key or _event_key(event), "letter_id": match.entry.id}
    return {"key": _event_key(event)}


def propose(
    store: MailOpportunityStore,
    user_id: str,
    mails: Sequence[Dict[str, Any]],
    *,
    letters: Optional[List[Dict[str, Any]]] = None,
    classifier: Optional[Classifier] = None,
    letters_collection=None,
    review_dir: Optional[Path] = None,
) -> Dict[str, int]:
    """Alert mail becomes proposed jobs, unless the history shows you already applied (same
    posting: ``applied``; same company and a similar title: ``skipped`` with the reason, so it can be
    restored). Any other mail is classified; application news updates (or creates) the job and its
    outcome, and the saved letter's outcome when there is one."""
    stats = {"mails": 0, "skipped_seen": 0, "new": 0, "seen_again": 0, "already_applied": 0, "application_events": 0, "ignored": 0, "unparsed": 0, "for_review": 0}
    jobs = store.list_for_user(user_id)
    if letters is None:
        letters = load_letters(user_id, letters_collection)
    history = ApplicationHistory.build(jobs, letters)

    def note_job(job: Dict[str, Any]) -> None:
        for i, j in enumerate(jobs):
            if j.get("id") == job.get("id"):
                jobs[i] = job
                break
        else:
            jobs.append(job)
        history.entries[:] = ApplicationHistory.build(jobs, letters).entries

    for mail in mails:
        message_id = str(mail.get("message_id"))
        if store.alert_processed(user_id, message_id):
            stats["skipped_seen"] += 1
            continue
        stats["mails"] += 1
        result = parse_alert(mail)
        ids: List[str] = []
        parser, reason = result.parser, result.reason
        for p in result.proposals:
            key = ops.canonical_key(p.url)
            status = ops.PROPOSED
            extra: Dict[str, Any] = {}
            if not any(j.get("canonical_key") == key for j in jobs):
                match = history.match(company=p.company, title=p.title, key=key)
                if match and match.exact:
                    status = ops.APPLIED
                    extra = {"document_id": match.entry.id} if match.entry.source == "letter" else {}
                elif match:
                    status, extra = ops.SKIPPED, {"skip_reason": match.reason, "auto_skipped": True}
                else:
                    earlier = history.same_company(p.company)
                    if earlier:
                        last = max(earlier, key=lambda e: e.when)
                        extra = {"history_note": f"You applied to {last.company} before" + (f" ({last.title}, {last.when[:10]})" if last.title else "") + "."}
            opp_id, created = store.upsert_proposed(
                user_id, url=p.url, title=p.title, company=p.company, location=p.location, alert_message_id=message_id, status=status, extra=extra
            )
            ids.append(opp_id)
            if created and status != ops.PROPOSED:
                stats["already_applied"] += 1
            else:
                stats["new" if created else "seen_again"] += 1
            if created:
                note_job(store.get(opp_id) or {"id": opp_id})

        events = list(result.events)
        if result.unparsed and classifier is None:
            save_for_review(mail, result.reason or "no template matched", review_dir)
            parser, reason = "review", result.reason or "no template matched"
            stats["for_review"] += 1
        elif result.unparsed:
            classify = classifier
            try:
                event = classify(mail)
            except Exception as exc:  # one bad mail must not stop the run
                event = None
                parser, reason = "unparsed", f"classification failed: {exc}"[:300]
            else:
                if event is None:
                    parser, reason = "ignored", "not about an application"
                else:
                    parser, reason = f"application:{event.kind}", ""
                    events.append(event)
        for event in events:
            target = _target_for_event(event, jobs, history)
            opp_id, job = store.record_application_event(
                user_id,
                event,
                mail_id=message_id,
                at=str(mail.get("date") or ""),
                sender=str(mail.get("sender") or ""),
                opp_id=target.get("opp_id"),
                key=target.get("key"),
                letter_id=target.get("letter_id"),
            )
            ids.append(opp_id)
            note_job(job)
            stats["application_events"] += 1
            _mirror_outcome_to_letter(job, letters_collection)

        if parser == "unparsed":
            stats["unparsed"] += 1
            logger.warning("unparsed mail %s: %s", message_id, reason)
        elif parser == "ignored":
            stats["ignored"] += 1
        store.record_alert(user_id, message_id, parser=parser, opportunity_ids=ids, reason=reason, sender=str(mail.get("sender") or ""))
    return stats


def unseen_ids(store: MailOpportunityStore, user_id: str, items: Sequence[str]) -> Tuple[List[str], int]:
    """Message ids worth fetching from ``id`` or ``id:sender`` items: not processed yet, and not from
    a noise sender (learned, or listed in ``LW_MAIL_IGNORE_SENDERS``). Returns (ids, left out as noise)."""
    noise = store.noise_senders(user_id) | {
        mail_store.sender_address(s) for s in (os.environ.get("LW_MAIL_IGNORE_SENDERS") or "").split(",") if s.strip()
    }
    out: List[str] = []
    dropped = 0
    for item in dict.fromkeys(items):
        message_id, _, sender = item.partition(":")
        if sender and mail_store.sender_address(sender) in noise:
            dropped += 1
            continue
        if message_id not in out and not store.alert_processed(user_id, message_id):
            out.append(message_id)
    return out, dropped


def _mirror_outcome_to_letter(job: Dict[str, Any], collection=None) -> None:
    """The saved letter keeps its application's outcome (stage, result, praise) for later analysis."""
    doc_id = job.get("document_id")
    outcome = job.get("outcome")
    if not doc_id or not outcome:
        return
    if collection is None:
        from .firestore_store import get_collection

        collection = get_collection()
    try:
        collection.document(str(doc_id)).set({"application_outcome": letter_outcome(outcome)}, merge=True)
    except Exception as exc:
        logger.warning("could not copy the outcome to letter %s: %s", doc_id, exc)


def outcomes_report(store: MailOpportunityStore, user_id: str) -> Dict[str, Any]:
    """Every application with its outcome, and how far applications with and without a letter got."""
    rows = [j for j in store.list_for_user(user_id) if j.get("status") in (ops.APPLIED, ops.DONE) or (j.get("outcome") or {}).get("events")]
    return {
        "summary": summarize(rows),
        "applications": [
            {
                "id": j["id"],
                "company": j.get("company") or "",
                "title": j.get("title") or "",
                "letter": bool(j.get("document_id")),
                "outcome": outcome_summary(j.get("outcome")) or "applied",
                "feedback": list((j.get("outcome") or {}).get("feedback_quotes") or []),
            }
            for j in rows
        ],
    }




def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m experimental.email.mail_batch", description=__doc__.split("\n")[0])
    p.add_argument("--user-id", help="defaults to LW_USER_ID")
    sub = p.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("propose", help="turn alert mail into proposed jobs, replies into application outcomes")
    pr.add_argument("--mail-file", required=True, type=Path)
    pr.add_argument("--dry-run", action="store_true", help="print what would be proposed; touch nothing")
    pr.add_argument(
        "--classify",
        action="store_true",
        help="classify mail that matches no template (one model call each); without it such mail is saved to review/",
    )
    un = sub.add_parser("unseen", help="print which of these Gmail messages to fetch (not processed yet, not from a noise sender)")
    un.add_argument("message_ids", nargs="+", metavar="ID[:SENDER]")
    sub.add_parser("outcomes", help="applications and how far they got (with and without a letter)")
    return p


def main(argv: Optional[Sequence[str]] = None, store: Optional[MailOpportunityStore] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=os.environ.get("LW_BATCH_LOG_LEVEL", "WARNING"), stream=sys.stderr)
    apply_host_defaults()
    if args.command == "propose" and args.dry_run:
        mails, bad = read_mail_file(args.mail_file)
        for row in preview_proposals(mails, default_classifier() if args.classify else None):
            print(json.dumps(row, ensure_ascii=False))
        print(json.dumps({"mails": len(mails), "bad_lines": bad, "dry_run": True}))
        return 0
    user_id = user_id_from_env(args.user_id)
    store = store or MailOpportunityStore()
    if args.command == "propose":
        mails, bad = read_mail_file(args.mail_file)
        stats = propose(store, user_id, mails, classifier=default_classifier() if args.classify else None)
        stats["bad_lines"] = bad
        print(json.dumps(stats))
    elif args.command == "outcomes":
        outcomes = outcomes_report(store, user_id)
        for row in outcomes["applications"]:
            letter = "letter" if row["letter"] else "      "
            print(f"{letter}  {row['outcome']:<28}  {row['company'][:30]:<30}  {row['title'][:60]}")
        print(json.dumps(outcomes["summary"]))
    elif args.command == "unseen":
        ids, dropped = unseen_ids(store, user_id, args.message_ids)
        for message_id in ids:
            print(message_id)
        if dropped:
            print(f"{dropped} message(s) from noise senders left out", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
