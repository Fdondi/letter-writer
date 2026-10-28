"""Mail-only additions to the opportunity store: the log of processed messages, application
events from replies, and noise senders. The core store (``letter_writer.opportunity_store``) has
none of this; email integration is optional (README.md in this folder)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from google.cloud import firestore

from letter_writer.opportunity_store import (
    ALLOWED_TRANSITIONS,
    APPLIED,
    COLLECTION,
    OpportunityStore,
    TransitionError,
    _sha256,
    clean_url,
    document_id,
    source_of,
)

ALERTS_COLLECTION = "alert_messages"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MailOpportunityStore(OpportunityStore):
    def __init__(self, db: Optional[firestore.Client] = None, collection: str = COLLECTION) -> None:
        super().__init__(db, collection)
        # Tests give each store its own collection; its alert log follows it.
        self._alerts_name = ALERTS_COLLECTION if collection == COLLECTION else f"{collection}_{ALERTS_COLLECTION}"

    def mark_applied_by_company(self, user_id: str, company: str, *, alert_message_id: Optional[str] = None) -> List[str]:
        """An "application sent to <Company>" mail: every open job at that company becomes ``applied``."""
        wanted = _company_key(company)
        if not wanted:
            return []
        changed = []
        for item in self.list_for_user(user_id):
            if _company_key(item.get("company") or "") != wanted:
                continue
            if APPLIED not in ALLOWED_TRANSITIONS.get(item.get("status") or "", frozenset()):
                continue
            fields: Dict[str, Any] = {}
            if alert_message_id:
                fields["alert_message_ids"] = firestore.ArrayUnion([alert_message_id])
            try:
                self.set_status(item["id"], APPLIED, from_states=[str(item.get("status") or "")], user_id=user_id, fields=fields)
                changed.append(item["id"])
            except TransitionError:
                continue
        return changed

    def record_application_event(
        self,
        user_id: str,
        event: Any,
        *,
        mail_id: str,
        at: str = "",
        sender: str = "",
        opp_id: Optional[str] = None,
        key: Optional[str] = None,
        letter_id: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Apply an :class:`~letter_writer.application_tracking.ApplicationEvent` to job ``opp_id``
        (or the job with ``key``), creating it as ``applied`` when it does not exist: an application
        made elsewhere is never proposed again. ``letter_id`` links a saved letter (``documents``).
        Returns (id, the job after the update)."""
        from experimental.email.application_tracking import apply_event

        if opp_id is None:
            if not key:
                raise ValueError("record_application_event needs opp_id or key")
            opp_id = document_id(user_id, key)
        ref = self._ref(opp_id)
        now = _now()

        @firestore.transactional
        def run(tx) -> None:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                if not key:
                    raise KeyError(f"Opportunity {opp_id} not found")
                tx.set(
                    ref,
                    {
                        "user_id": user_id,
                        "canonical_key": key,
                        "source": "mail" if not key.startswith(("jobs.ch:", "linkedin:", "swissdevjobs:")) else source_of(key),
                        "url": clean_url(event.job_url) if event.job_url else "",
                        "title": event.job_title,
                        "company": event.company,
                        "location": "",
                        "status": APPLIED,
                        "skip_reason": None,
                        "alert_message_ids": [mail_id] if mail_id else [],
                        "capture": None,
                        "document_id": letter_id,
                        "outcome": apply_event(None, event, mail_id=mail_id, at=at, sender=sender),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                return
            data = snap.to_dict() or {}
            self._check_owner(data, user_id, opp_id)
            update: Dict[str, Any] = {
                "outcome": apply_event(data.get("outcome"), event, mail_id=mail_id, at=at, sender=sender),
                "updated_at": now,
            }
            status = data.get("status") or ""
            if status != APPLIED and APPLIED in ALLOWED_TRANSITIONS.get(status, frozenset()):
                update["status"] = APPLIED
            for field, value in (("company", event.company), ("title", event.job_title)):
                if value and not str(data.get(field) or "").strip():
                    update[field] = value
            if letter_id and not data.get("document_id"):
                update["document_id"] = letter_id
            if mail_id:
                update["alert_message_ids"] = firestore.ArrayUnion([mail_id])
            tx.update(ref, update)

        run(self.db.transaction())
        return opp_id, self.get(opp_id) or {}

    # mail log (so the routine needs only read-only Gmail)

    def _alert_ref(self, user_id: str, message_id: str):
        return self.db.collection(self._alerts_name).document(_sha256(f"{user_id}\n{message_id}")[:32])

    def alert_processed(self, user_id: str, message_id: str) -> bool:
        return self._alert_ref(user_id, message_id).get().exists

    def record_alert(
        self, user_id: str, message_id: str, *, parser: str, opportunity_ids: Sequence[str], reason: str = "", sender: str = ""
    ) -> None:
        self._alert_ref(user_id, message_id).set(
            {
                "user_id": user_id,
                "message_id": message_id,
                "processed_at": _now(),
                "parser": parser,
                "opportunity_ids": list(opportunity_ids),
                "reason": reason,
                "sender": sender_address(sender),
            }
        )

    def noise_senders(self, user_id: str, min_ignored: int = 2) -> set:
        """Senders whose last ``min_ignored`` or more mails were all "not about an application"
        and none ever was: their mail is no longer fetched or classified."""
        ignored: Dict[str, int] = {}
        useful: set = set()
        query = self.db.collection(self._alerts_name).where(filter=firestore.FieldFilter("user_id", "==", user_id))
        for snap in query.stream():
            data = snap.to_dict() or {}
            sender = str(data.get("sender") or "")
            if not sender:
                continue
            if data.get("parser") == "ignored":
                ignored[sender] = ignored.get(sender, 0) + 1
            elif data.get("parser") != "unparsed":
                useful.add(sender)
        return {s for s, n in ignored.items() if n >= min_ignored and s not in useful}


_COMPANY_SUFFIXES = re.compile(r"\b(ag|sa|gmbh|sàrl|sarl|ltd|inc|llc|plc|s\.a\.|a\.g\.|group|holding|schweiz|switzerland|suisse)\b\.?", re.I)


def sender_address(sender: str) -> str:
    """The bare, lowercased address of a ``From`` value ("Jobs <a@b.ch>" -> "a@b.ch")."""
    from email.utils import parseaddr

    return (parseaddr(sender or "")[1] or sender or "").strip().lower()


def _company_key(name: str) -> str:
    """Company name without legal suffixes, punctuation or case, for matching applied mails."""
    s = _COMPANY_SUFFIXES.sub(" ", (name or "").lower())
    return " ".join(re.sub(r"[^\w]+", " ", s).split())
