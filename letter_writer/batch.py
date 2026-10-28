"""Opportunity batch: ``python -m letter_writer.batch <command>`` (OPPORTUNITY_PIPELINE_PLAN.md §4.5).

Runs on the host (the ``claude`` CLI and its login live there), not in the backend container.

    run-captured [--max-jobs 3] [--vendors claude_code,openai] [--dry-run]
                 [--rewrite-rounds 0|1|2] [--final-feedback | --no-final-feedback]
    status                             one line for the routine to report
    retry <opportunity_id>             failed (or ready) -> captured; the next run drafts only the
                                       vendors without a finished letter for the same posting
    seed --url <url> [--text-file f]   add a captured job by hand

    users                              the profiles in Firestore (find your LW_USER_ID)

Configuration: the backend's ``.env`` (vendor keys, Firestore project), plus ``LW_USER_ID`` (the
Google ``sub`` the app signs in with; optional when Firestore holds exactly one profile). Vendors,
rewrite rounds and final comments come with each job (the phone sends them); the flags above only
fill in for a job that has none, and a job with no vendors uses all of them. Anthropic always runs as
Claude Code here; the Anthropic API is for realtime calls (the phone, the web app). On the host the batch uses ``gcloud-credentials.json`` from the repository and
Ollaya on ``127.0.0.1:11435`` unless told otherwise (see :func:`apply_host_defaults`).
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, cast

from . import headless
from . import opportunity_store as ops
from .clients.base import ModelVendor

logger = logging.getLogger("letter_writer.batch")

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_OLLAYA_URL = "http://127.0.0.1:11435"

@dataclass(frozen=True)
class DraftSettings:
    """How far the desktop takes each vendor's letter: draft, then ``rewrite_rounds`` times
    comments → rewrite, then (``final_feedback``) comments on the last version for the apps.
    A job's ``rewrite_rounds`` / ``final_feedback`` fields set them; the CLI fills in the rest."""

    rewrite_rounds: int = 1
    final_feedback: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {"rewrite_rounds": self.rewrite_rounds, "final_feedback": self.final_feedback}

    def for_job(self, opp: Dict[str, Any]) -> "DraftSettings":
        rounds = opp.get("rewrite_rounds")
        final = opp.get("final_feedback")
        return DraftSettings(
            rewrite_rounds=max(0, min(MAX_REWRITE_ROUNDS, int(rounds))) if isinstance(rounds, (int, float)) and not isinstance(rounds, bool) else self.rewrite_rounds,
            final_feedback=final if isinstance(final, bool) else self.final_feedback,
        )

    @staticmethod
    def of_state(state: Dict[str, Any]) -> "DraftSettings":
        """The settings a stored vendor state was drafted with; states from before settings
        existed were drafted, commented and rewritten once."""
        raw = (state or {}).get("batch_settings")
        if not isinstance(raw, dict):
            return LEGACY_SETTINGS
        return DraftSettings(int(raw.get("rewrite_rounds", 1)), bool(raw.get("final_feedback", False)))

    def finished(self, state: Dict[str, Any]) -> bool:
        letter = "final_letter" if self.rewrite_rounds > 0 else "draft_letter"
        return bool(str((state or {}).get(letter) or "").strip())


# Every vendor, Anthropic as Claude Code: in the batch Anthropic runs on the subscription, never the API.
ALL_VENDORS = tuple(v.value for v in ModelVendor if v is not ModelVendor.ANTHROPIC)
MAX_REWRITE_ROUNDS = 2
LEGACY_SETTINGS = DraftSettings(rewrite_rounds=1, final_feedback=False)
# Keys the batch adds to a vendor's stored state: which text its comments are about
# (`draft_letter`, `final_letter`, or none) and the settings it was drafted with.
STATE_MARKERS = ("comments_on", "batch_settings")
SUBSCRIPTION_VENDORS = frozenset({ModelVendor.CLAUDE_CODE.value})
LEASE_S = 2 * 3600.0
STRONG_LEVELS = ("Professional", "Senior professional")
WEAK_LEVELS = ("Newbie", "Amateur")
IMPORTANT_NEEDS = ("critical", "necessary", "expected")
FEEDBACK_CATEGORIES = ("instruction", "accuracy", "precision", "company_fit", "goal_fit", "user_fit", "human")


class BatchError(Exception):
    """A job cannot be drafted (missing CV, empty capture, …); the message ends up on the job."""


# --- helpers ---------------------------------------------------------------------------------


def apply_host_defaults(env=None) -> None:
    """The batch runs on the host while the backend runs in docker-compose. Point at the
    host-side Ollaya port and the repository's service-account file unless already set.
    These must not live in ``.env``: compose substitutes ``.env`` into the container's
    environment, where Ollaya is ``http://ollaya:11435``."""
    env = os.environ if env is None else env
    if not env.get("OLLAYA_BASE_URL"):
        env["OLLAYA_BASE_URL"] = env.get("LW_OLLAYA_BASE_URL") or HOST_OLLAYA_URL
    creds = REPO_ROOT / "gcloud-credentials.json"
    if not env.get("GOOGLE_APPLICATION_CREDENTIALS") and creds.is_file():
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds)
    if not env.get("FIRESTORE_DATABASE"):
        env["FIRESTORE_DATABASE"] = "letter"


def list_profiles(collection=None) -> List[Dict[str, Any]]:
    """``personal_data`` documents (one per user; the document id is the Google ``sub``)."""
    if collection is None:
        from .firestore_store import get_personal_data_collection

        collection = get_personal_data_collection()
    out = []
    for snap in collection.stream():
        data = snap.to_dict() or {}
        revisions = data.get("cv_revisions") or []
        out.append({"id": snap.id, "cv_revisions": len(revisions) if isinstance(revisions, list) else 0, "updated_at": str(data.get("updated_at") or "")})
    return out


def user_id_from_env(explicit: Optional[str] = None, profiles: Optional[Callable[[], List[Dict[str, Any]]]] = None) -> str:
    """``--user-id``, else ``LW_USER_ID``, else the only profile in Firestore."""
    uid = (explicit or os.environ.get("LW_USER_ID") or "").strip()
    if uid:
        return uid
    found = (profiles or list_profiles)()
    if len(found) == 1:
        return str(found[0]["id"])
    raise SystemExit(
        "Set LW_USER_ID to your Google account id (the `sub` the app signs in with): "
        f"Firestore has {len(found)} profiles. List them with `python -m letter_writer.batch users`, "
        "or hover your name in the web app's header."
    )


def requested_vendors(opp: Dict[str, Any], cli_vendors: Optional[Sequence[str]]) -> List[str]:
    """The job's own choice (the phone sends it), else ``--vendors``, else :data:`ALL_VENDORS`: the
    desktop has no favourites of its own. ``anthropic`` runs as ``claude_code`` here (one vendor:
    the batch uses Claude Code, realtime calls use the API). Unknown names are dropped."""
    raw: Iterable[str] = opp.get("vendors_requested") or cli_vendors or ALL_VENDORS
    valid = {v.value for v in ModelVendor}
    out: List[str] = []
    for v in raw:
        key = str(v).strip().lower()
        if key == ModelVendor.ANTHROPIC.value:
            key = ModelVendor.CLAUDE_CODE.value
        if key in valid and key not in out:
            out.append(key)
    return out


def fit_summary(extraction: Dict[str, Any], limit: int = 8) -> Dict[str, List[str]]:
    """Matched skills (CV level Professional or above) and gaps (important need, weak level)."""
    comps = extraction.get("competences") or {}
    order = {need: i for i, need in enumerate(IMPORTANT_NEEDS)}
    items = sorted(
        ((skill, (c or {}).get("need", ""), (c or {}).get("level", "")) for skill, c in comps.items() if isinstance(c, dict)),
        key=lambda t: order.get(str(t[1]).lower(), len(order)),
    )
    matched = [s for s, _, level in items if level in STRONG_LEVELS][:limit]
    gaps = [s for s, need, level in items if str(need).lower() in IMPORTANT_NEEDS and level in WEAK_LEVELS][:limit]
    return {"matched": matched, "gaps": gaps}


def count_input_needed(vendors: Dict[str, Any]) -> int:
    """Open questions across vendors (feedback items in INPUT_NEEDED)."""
    total = 0
    for state in (vendors or {}).values():
        feedback = (state or {}).get("feedback") or {}
        for cat in FEEDBACK_CATEGORIES:
            for item in feedback.get(cat) or []:
                if isinstance(item, dict) and str(item.get("status", "")).upper() == "INPUT_NEEDED":
                    total += 1
    return total


def capture_fingerprint(text: str, html: str) -> str:
    """Identifies the posting a stored session was drafted from (``state.capture_fingerprint``)."""
    return hashlib.sha256(f"{text}\0{html}".encode("utf-8")).hexdigest()[:32]


def reusable_drafts(
    previous: Optional[Dict[str, Any]], fingerprint: str, settings: DraftSettings
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Finished vendor states stored for the same posting text, as (kept, fallback).

    ``kept`` were drafted with the job's current settings and are not drafted again. ``fallback``
    were drafted with other settings: they are drafted again, but stay if that attempt fails. Both
    include vendors the job no longer asks for, so a retry never loses a draft that succeeded
    (only successful vendors are ever stored, each as it finishes). New posting text, or a session
    without a fingerprint, is drafted again from scratch."""
    if not previous or previous.get("capture_fingerprint") != fingerprint:
        return {}, {}
    kept: Dict[str, Dict[str, Any]] = {}
    fallback: Dict[str, Dict[str, Any]] = {}
    for v, st in (previous.get("vendors") or {}).items():
        drafted_with = DraftSettings.of_state(st)
        if not drafted_with.finished(st):
            continue
        (kept if drafted_with == settings else fallback)[v] = st
    return kept, fallback


def _vendor_cost(state: Dict[str, Any]) -> float:
    try:
        return float((state or {}).get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --- run-captured --------------------------------------------------------------------------


def _research_report(session: Dict[str, Any], user_data: Dict[str, Any], research_vendor: str) -> str:
    """One company research for all vendors, as the web intake does (cached in ``companies``)."""
    from .research import perform_company_research

    common = (session.get("metadata") or {}).get("common") or {}
    company = str(common.get("company_name") or "").strip()
    if not company:
        return ""
    result = perform_company_research(
        company_name=company,
        models=[research_vendor],
        job_text=session.get("job_text", ""),
        additional_company_info=str(common.get("additional_company_info") or ""),
        search_instructions=session.get("search_instructions", ""),
        user_data=user_data,
    )
    for entry in (result.get("results") or {}).values():
        report = str((entry or {}).get("report") or "").strip()
        if report:
            return report
    return ""


def draft_vendor(vendor: str, sess: headless.HeadlessSession, *, user_id: str, settings: DraftSettings) -> None:
    """Background (shared report and examples) → plan (auto-approved) → draft, then
    ``rewrite_rounds`` times comments → rewrite, then comments on the last version when
    ``final_feedback``: the phase functions the web vendor flow calls. The vendor's stored state
    says which text its comments are about (``comments_on``) and the settings used."""
    from .phased_service import VendorPhaseState, advance_to_draft, advance_to_plan, advance_to_refinement, check_letter
    from .session_store import save_vendor_data

    key = sess.session_key
    v = ModelVendor(vendor)
    style = sess.get("style_instructions", "")
    rounds = settings.rewrite_rounds
    save_vendor_data(
        key,
        vendor,
        VendorPhaseState(top_docs=list(sess.get("selected_top_docs") or []), company_report=sess.get("company_report_shared", "")),
    )
    advance_to_plan(session_id=key, vendor=v, structure_instructions=sess.get("structure_instructions", ""), user_id=user_id)
    # The draft phase comments the draft; skipped when the draft is the result and nobody reads them.
    state = advance_to_draft(session_id=key, vendor=v, style_instructions=style, user_id=user_id, run_checks=rounds > 0 or settings.final_feedback)
    text = state.draft_letter
    for i in range(rounds):
        if i > 0:
            check_letter(session_id=key, vendor=v, letter=text, style_instructions=style, user_id=user_id)
        state = advance_to_refinement(session_id=key, vendor=v, draft_override=text, style_instructions=style, user_id=user_id)
        text = state.final_letter
    if rounds > 0 and settings.final_feedback:
        check_letter(session_id=key, vendor=v, letter=text, style_instructions=style, user_id=user_id)
    if settings.final_feedback:
        comments_on: Optional[str] = "final_letter" if rounds > 0 else "draft_letter"
    else:
        # The last comments (if any) are about the text before the last rewrite.
        comments_on = "draft_letter" if rounds > 0 else None
    vendors = dict(sess.get("vendors") or {})
    vendors[vendor] = {**(vendors.get(vendor) or {}), "comments_on": comments_on, "batch_settings": settings.as_dict()}
    sess["vendors"] = vendors


def _merge_input_clusters(session: Dict[str, Any], session_key: str, vendor: str) -> None:
    """Consistent ``input_cluster_key`` across vendors (the web app does this after each draft;
    parallel vendors only saw their own feedback)."""
    from .client import get_client
    from .feedback_review import merge_input_clusters_across_session_vendors
    from .session_store import load_session, save_vendor_data

    with headless.headless_session(session, session_key) as sess:
        state = load_session(session_key)
        merge_input_clusters_across_session_vendors(session=state, client=get_client(ModelVendor(vendor)))
        for name, vstate in state.vendors.items():
            save_vendor_data(session_key, name, vstate)
        session.update(sess)


def process_opportunity(
    store: ops.OpportunityStore,
    opp: Dict[str, Any],
    *,
    user_id: str,
    vendors: Sequence[str],
    settings: DraftSettings = DraftSettings(),
    research_vendor: str = "openai",
    spending_check: Optional[Callable[[str], Optional[str]]] = None,
    on_progress: Optional[Callable[[str, Sequence[str]], None]] = None,
) -> Dict[str, Any]:
    """Draft one claimed job. Returns the fields to write when the lease ends (including
    ``status``); never raises for a single vendor's failure. ``on_progress(step, vendors_done)``
    is told each step (``reading``, ``research``, ``drafting``) and each finished vendor."""
    report = on_progress or (lambda step, done: None)
    from .clients.claude_code import subscription_spend_usd
    from .firestore_store import get_user_data
    from letter_writer_server.api.extract_pipeline import run_capture_extract

    opp_id = opp["id"]
    capture = opp.get("capture") or {}
    text, html = str(capture.get("text") or ""), str(capture.get("html") or "")
    if not text.strip() and not html.strip():
        raise BatchError("The job has no captured posting text.")
    user_data = get_user_data(user_id, use_cache=False) or {}
    data = headless.initial_session(user_id, user_data)
    if not str(data.get("cv_text") or "").strip():
        raise BatchError("No CV in the profile (personal_data.cv_revisions is empty).")
    spend_before = subscription_spend_usd()
    fingerprint = capture_fingerprint(text, html)
    previous = store.load_state(opp_id)
    kept, fallback = reusable_drafts(previous, fingerprint, settings)

    session_key = f"opportunity-{opp_id}"
    if (kept or fallback) and previous:
        # A retry of the same posting: the last run's extraction, examples and research stay, so
        # the new drafts match the kept ones and nothing is paid twice.
        for key in ("job_text", "metadata", "selected_top_docs", "search_result"):
            if key in previous:
                data[key] = copy.deepcopy(previous[key])
        data["company_report_shared"] = next(
            (str(st.get("company_report")) for st in {**fallback, **kept}.values() if st.get("company_report")), ""
        )
        common = data
        extraction = dict((data.get("metadata") or {}).get("common") or {})
    else:
        report("reading", [])
        with headless.headless_session(data, session_key) as sess:
            # HeadlessSession has the dict interface and session_key the server Session provides.
            extract = run_capture_extract(cast(Any, sess), visible_text=text, html=html, source_url=str(opp.get("url") or ""))
            sess["selected_top_docs"] = list(extract.get("top_docs") or [])
            report("research", [])
            try:
                sess["company_report_shared"] = _research_report(sess, user_data, research_vendor)
            except Exception as exc:  # drafts are still useful without research
                logger.warning("company research failed for %s: %s", opp_id, exc)
                sess["company_report_shared"] = ""
            common = dict(sess)
        extraction = extract.get("extraction") or {}

    errors: Dict[str, str] = {}
    runnable = [v for v in vendors if v not in kept]
    if spending_check is not None and any(v not in SUBSCRIPTION_VENDORS for v in runnable):
        blocked = spending_check(user_id)
        if blocked:
            for v in [v for v in runnable if v not in SUBSCRIPTION_VENDORS]:
                errors[v] = blocked
            runnable = [v for v in runnable if v in SUBSCRIPTION_VENDORS]

    finished = [v for v in vendors if v in kept]
    report("drafting", list(finished))
    saved: Dict[str, Dict[str, Any]] = {**fallback, **kept}
    save_lock = threading.Lock()

    def vendor_finished(vendor: str, state: Optional[Dict[str, Any]]) -> None:
        # Each successful draft is stored at once, so a run that dies later (or a vendor that fails)
        # never costs the drafts already written; the next run keeps them (reusable_drafts).
        with save_lock:
            if state is not None:
                finished.append(vendor)
                saved[vendor] = state
                partial = dict(common)
                partial.pop("company_report_shared", None)
                partial["capture_fingerprint"] = fingerprint
                partial["vendors"] = dict(saved)
                try:
                    store.save_state(opp_id, headless.persistable_state(partial))
                except Exception:
                    logger.warning("saving %s's draft for %s failed; it is saved with the others at the end", vendor, opp_id, exc_info=True)
            done_now = list(finished)
        report("drafting", done_now)

    states, failed = headless.run_vendors_parallel(
        common,
        runnable,
        lambda vendor, s: draft_vendor(vendor, s, user_id=user_id, settings=settings),
        session_key,
        on_finished=vendor_finished,
    )
    errors.update(failed)
    # A vendor drafted again with new settings keeps its previous letter when the new attempt fails.
    states = {**fallback, **kept, **states}
    session = dict(common)
    session.pop("company_report_shared", None)
    session["capture_fingerprint"] = fingerprint
    headless.merge_vendor_states(session, states)
    done = headless.vendors_in_order(states, list(vendors))

    api_vendors_done = [v for v in done if v not in SUBSCRIPTION_VENDORS]
    if len(done) > 1 and api_vendors_done:
        try:
            _merge_input_clusters(session, session_key, api_vendors_done[0])
        except Exception as exc:
            logger.warning("cross-vendor input clustering failed for %s: %s", opp_id, exc)
        # Clustering re-saves states through VendorPhaseState, which has no fields for the markers.
        for v, st in states.items():
            if v in session["vendors"]:
                session["vendors"][v] = {**session["vendors"][v], **{k: st[k] for k in STATE_MARKERS if k in st}}

    store.save_state(opp_id, headless.persistable_state(session))

    # A kept Claude Code draft keeps the subscription estimate of the run that wrote it.
    prior_subscription = float(opp.get("cost_subscription_estimate_usd") or 0.0) if any(v in SUBSCRIPTION_VENDORS for v in kept) else 0.0
    fields: Dict[str, Any] = {
        "status": ops.READY if done else ops.FAILED,
        "vendors_requested": list(vendors),
        **settings.as_dict(),
        "vendors_done": done,
        "vendors_failed": errors,
        "input_needed_count": count_input_needed(session.get("vendors") or {}),
        "fit_summary": fit_summary(extraction),
        "cost_api_usd": round(sum(_vendor_cost(states[v]) for v in api_vendors_done), 4),
        "cost_subscription_estimate_usd": round(prior_subscription + subscription_spend_usd() - spend_before, 4),
    }
    for field, key in (("title", "job_title"), ("company", "company_name"), ("location", "location")):
        if not str(opp.get(field) or "").strip() and extraction.get(key):
            fields[field] = str(extraction[key]).strip()
    return fields


def default_spending_check(user_id: str) -> Optional[str]:
    from letter_writer_server.api.cost_utils import spending_limit_error

    blocked = spending_limit_error(user_id, {})
    return blocked[1] if blocked else None


def run_captured(
    store: ops.OpportunityStore,
    user_id: str,
    *,
    max_jobs: int = 3,
    cli_vendors: Optional[Sequence[str]] = None,
    settings: DraftSettings = DraftSettings(),
    dry_run: bool = False,
    research_vendor: str = "openai",
    spending_check: Optional[Callable[[str], Optional[str]]] = default_spending_check,
    owner: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Claim and draft up to ``max_jobs`` captured jobs, one after the other."""
    if dry_run:
        waiting = store.list_by_status(ops.CAPTURED, user_id)
        return [{"id": o["id"], "title": o.get("title", ""), "vendors": requested_vendors(o, cli_vendors), "dry_run": True} for o in waiting[:max_jobs]]
    owner = owner or f"batch-{socket.gethostname()}-{os.getpid()}"
    report: List[Dict[str, Any]] = []
    for _ in range(max(0, max_jobs)):
        opp = store.claim_next_captured(owner, LEASE_S, user_id=user_id)
        if opp is None:
            break
        vendors = requested_vendors(opp, cli_vendors)
        started = datetime.now(timezone.utc)

        def progress(step: str, done: Sequence[str], opp_id: str = opp["id"], total: int = len(vendors), started: datetime = started) -> None:
            try:
                store.report_progress(opp_id, owner, {"step": step, "vendors_done": list(done), "vendors_total": total, "started_at": started})
            except Exception:  # the apps just see less detail
                logger.warning("progress report for %s failed", opp_id, exc_info=True)

        try:
            fields = process_opportunity(
                store,
                opp,
                user_id=user_id,
                vendors=vendors,
                settings=settings.for_job(opp),
                research_vendor=research_vendor,
                spending_check=spending_check,
                on_progress=progress,
            )
        except Exception as exc:
            logger.exception("drafting %s failed", opp["id"])
            fields = {"status": ops.FAILED, "vendors_requested": vendors, "vendors_done": [], "vendors_failed": {"batch": f"{type(exc).__name__}: {exc}"[:1000]}}
        status = fields.pop("status")
        store.finish_drafting(opp["id"], owner, status, fields)
        report.append({"id": opp["id"], "status": status, "vendors_done": fields.get("vendors_done", []), "vendors_failed": fields.get("vendors_failed", {})})
    return report


# --- status / retry / seed -------------------------------------------------------------------


def status_line(store: ops.OpportunityStore, user_id: str) -> str:
    counts = {s: 0 for s in ops.STATUSES}
    questions = 0
    for item in store.list_for_user(user_id):
        status = item.get("status") or ""
        if status in counts:
            counts[status] += 1
        if status == ops.READY:
            questions += int(item.get("input_needed_count") or 0)
    parts = [f"proposed {counts[ops.PROPOSED]}", f"waiting for text {counts[ops.APPROVED]}", f"captured {counts[ops.CAPTURED]}"]
    if counts[ops.DRAFTING]:
        parts.append(f"drafting {counts[ops.DRAFTING]}")
    parts.append(f"ready {counts[ops.READY]}" + (f" ({questions} questions)" if questions else ""))
    if counts[ops.FAILED]:
        parts.append(f"failed {counts[ops.FAILED]}")
    return " · ".join(parts)


def retry(store: ops.OpportunityStore, user_id: str, opp_id: str) -> Dict[str, Any]:
    return store.set_status(opp_id, ops.CAPTURED, from_states=[ops.FAILED, ops.READY], user_id=user_id, fields={"vendors_failed": {}})


# --- CLI ---------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m letter_writer.batch", description=__doc__.split("\n")[0])
    p.add_argument("--user-id", help="defaults to LW_USER_ID")
    sub = p.add_subparsers(dest="command", required=True)
    rc = sub.add_parser("run-captured", help="draft letters for captured jobs")
    rc.add_argument("--max-jobs", type=int, default=3)
    rc.add_argument("--vendors", help="comma-separated, e.g. claude_code,openai")
    rc.add_argument(
        "--rewrite-rounds", type=int, choices=range(0, MAX_REWRITE_ROUNDS + 1), default=1,
        help="comments → rewrite rounds for jobs that don't say (default 1)",
    )
    rc.add_argument(
        "--final-feedback", action=argparse.BooleanOptionalAction, default=True,
        help="comment the last version for jobs that don't say (default on)",
    )
    rc.add_argument("--research-vendor", default=os.environ.get("LW_RESEARCH_VENDOR", "openai"))
    rc.add_argument("--dry-run", action="store_true")
    rc.add_argument(
        "--detach",
        action="store_true",
        help="start the drafting as its own process and return at once (log in temp/opportunities/); "
        "the routine uses this because drafting can outlast an agent's command time limit",
    )
    sub.add_parser("status", help="one-line summary")
    sub.add_parser("users", help="list the profiles in Firestore (to find LW_USER_ID)")
    rt = sub.add_parser("retry", help="queue a failed or ready job again")
    rt.add_argument("opportunity_id")
    sd = sub.add_parser("seed", help="add a captured job by hand")
    sd.add_argument("--url", default="")
    sd.add_argument("--text-file", type=Path)
    sd.add_argument("--title", default="")
    sd.add_argument("--company", default="")
    sd.add_argument("--vendors", help="comma-separated vendors for this job")
    return p


def detach_run_captured(argv: Sequence[str], popen=None) -> Dict[str, Any]:
    """Re-run this command without ``--detach`` in a new session, logging to temp/opportunities/."""
    import subprocess
    from datetime import datetime

    log_dir = REPO_ROOT / "temp" / "opportunities"
    log_dir.mkdir(parents=True, exist_ok=True)
    pid_file = log_dir / "batch.pid"
    running = _running_pid(pid_file)
    if running:
        return {"already_running": running}
    log_path = log_dir / f"batch-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    args = [a for a in argv if a != "--detach"]
    with open(log_path, "ab") as log:
        proc = (popen or subprocess.Popen)(
            [sys.executable, "-m", "letter_writer.batch", *args],
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    return {"detached": proc.pid, "log": str(log_path.relative_to(REPO_ROOT))}


def _running_pid(pid_file: Path) -> Optional[int]:
    """The pid in ``pid_file`` when that process is still alive."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def main(argv: Optional[Sequence[str]] = None, store: Optional[ops.OpportunityStore] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=os.environ.get("LW_BATCH_LOG_LEVEL", "WARNING"), stream=sys.stderr)
    apply_host_defaults()
    if args.command == "users":
        for profile in list_profiles():
            print(f"{profile['id']}  cv_revisions={profile['cv_revisions']}  updated_at={profile['updated_at'] or '-'}")
        return 0
    user_id = user_id_from_env(args.user_id)
    store = store or ops.OpportunityStore()
    if args.command == "run-captured" and args.detach:
        print(json.dumps(detach_run_captured(list(argv if argv is not None else sys.argv[1:]))))
    elif args.command == "run-captured":
        vendors = [v for v in (args.vendors or "").split(",") if v.strip()] or None
        report = run_captured(
            store,
            user_id,
            max_jobs=args.max_jobs,
            cli_vendors=vendors,
            settings=DraftSettings(rewrite_rounds=args.rewrite_rounds, final_feedback=args.final_feedback),
            dry_run=args.dry_run,
            research_vendor=args.research_vendor,
        )
        print(json.dumps(report))
    elif args.command == "status":
        print(status_line(store, user_id))
    elif args.command == "retry":
        retry(store, user_id, args.opportunity_id)
        print(f"{args.opportunity_id} queued for the next run")
    elif args.command == "seed":
        text = args.text_file.read_text(encoding="utf-8") if args.text_file else ""
        vendors = [v for v in (args.vendors or "").split(",") if v.strip()]
        opp_id, status, message = store.capture(
            user_id, url=args.url, text=text, via="manual", title=args.title, company=args.company, vendors_requested=vendors
        )
        print(json.dumps({"id": opp_id, "status": status, "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
