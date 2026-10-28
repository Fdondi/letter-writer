"""Opportunity batch: ``python -m letter_writer.batch <command>`` (OPPORTUNITY_PIPELINE_PLAN.md §4.5).

Runs on the host (the ``claude`` CLI and its login live there), not in the backend container.

    daemon [--once] [--interval-hours 3] [--daily-cap 5] [--archive-days 3] [--dry-run]
                 [--vendors claude_code,openai] [--rewrite-rounds 0|1|2]
                 [--final-feedback | --no-final-feedback]
                                       the scheduled path: every wake archives rated jobs that
                                       never made it, extracts and fit-rates every captured job
                                       (-> rated), then drafts only the best rated ones up to a
                                       rolling 24h cap (default 5). --once runs a single cycle
                                       (the systemd timer calls it every LW_WAKE_INTERVAL_HOURS).
    run-captured [--max-jobs 3] [--vendors claude_code,openai] [--dry-run]
                 [--rewrite-rounds 0|1|2] [--final-feedback | --no-final-feedback]
                                       manual override: draft captured jobs right now, ignoring
                                       the rating and the cap
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

The daemon's knobs (flags or env): ``--interval-hours`` / ``LW_WAKE_INTERVAL_HOURS`` (default 3),
``--daily-cap`` / ``LW_DAILY_CAP`` (default 5: letters drafted per rolling 24 hours),
``--archive-days`` / ``LW_ARCHIVE_DAYS`` (default 3: a rated job not drafted within this window is
archived and left alone until the user re-enables it).
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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, cast

from . import fit_score as fit_scores
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

# The daemon's defaults: how often it wakes, how many letters it drafts per rolling 24 hours, and
# how long a rated job waits for a drafting slot before it is archived (flags/env override them).
DEFAULT_WAKE_INTERVAL_HOURS = 3.0
DEFAULT_DAILY_CAP = 5
DEFAULT_ARCHIVE_DAYS = 3.0
ROLLING_CAP_WINDOW = timedelta(hours=24)


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
    if previous and previous.get("capture_fingerprint") == fingerprint:
        # The same posting text as the stored state (the rating pass, or a retry): the extraction
        # and examples stay, so the new drafts match the kept ones and nothing is paid twice.
        for key in ("job_text", "metadata", "selected_top_docs", "search_result"):
            if key in previous:
                data[key] = copy.deepcopy(previous[key])
        common = data
        extraction = dict((data.get("metadata") or {}).get("common") or {})
        common["company_report_shared"] = next(
            (str(st.get("company_report")) for st in {**fallback, **kept}.values() if st.get("company_report")), ""
        )
    else:
        report("reading", [])
        with headless.headless_session(data, session_key) as sess:
            # HeadlessSession has the dict interface and session_key the server Session provides.
            extract = run_capture_extract(cast(Any, sess), visible_text=text, html=html, source_url=str(opp.get("url") or ""))
            sess["selected_top_docs"] = list(extract.get("top_docs") or [])
            common = dict(sess)
        extraction = extract.get("extraction") or {}
    if not str(common.get("company_report_shared") or "").strip():
        report("research", [])
        try:
            common["company_report_shared"] = _research_report(common, user_data, research_vendor)
        except Exception as exc:  # drafts are still useful without research
            logger.warning("company research failed for %s: %s", opp_id, exc)
            common["company_report_shared"] = ""

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


def _draft_claimed(
    store: ops.OpportunityStore,
    opp: Dict[str, Any],
    owner: str,
    user_id: str,
    *,
    cli_vendors: Optional[Sequence[str]] = None,
    settings: DraftSettings = DraftSettings(),
    research_vendor: str = "openai",
    spending_check: Optional[Callable[[str], Optional[str]]] = default_spending_check,
) -> Dict[str, Any]:
    """Draft one claimed (``drafting``, leased) job and end the lease: ``ready``, or ``failed``
    with each vendor's error. Never raises for a single job's failure."""
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
    return {"id": opp["id"], "status": status, "vendors_done": fields.get("vendors_done", []), "vendors_failed": fields.get("vendors_failed", {})}


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
    """Manual override: claim and draft up to ``max_jobs`` captured jobs, one after the other,
    ignoring the rating and the rolling cap (the daemon's :func:`run_cycle` is the scheduled path)."""
    if dry_run:
        waiting = store.list_by_status(ops.CAPTURED, user_id)
        return [{"id": o["id"], "title": o.get("title", ""), "vendors": requested_vendors(o, cli_vendors), "dry_run": True} for o in waiting[:max_jobs]]
    owner = owner or f"batch-{socket.gethostname()}-{os.getpid()}"
    report: List[Dict[str, Any]] = []
    for _ in range(max(0, max_jobs)):
        opp = store.claim_next_captured(owner, LEASE_S, user_id=user_id)
        if opp is None:
            break
        report.append(
            _draft_claimed(
                store, opp, owner, user_id,
                cli_vendors=cli_vendors, settings=settings,
                research_vendor=research_vendor, spending_check=spending_check,
            )
        )
    return report


# --- daemon: archive, rate, draft the best under the rolling cap ------------------------------


def _rate_failed(store: ops.OpportunityStore, opp: Dict[str, Any], user_id: str, reason: str) -> None:
    """A captured job the rating pass cannot extract becomes ``failed`` with the reason (the user
    retries it once the cause is fixed)."""
    try:
        store.set_status(opp["id"], ops.FAILED, from_states=[ops.CAPTURED], user_id=user_id, fields={"vendors_failed": {"batch": reason[:1000]}})
    except (ops.TransitionError, KeyError):
        pass  # another run moved the job on meanwhile


def rate_captured(
    store: ops.OpportunityStore,
    user_id: str,
    *,
    spending_check: Optional[Callable[[str], Optional[str]]] = default_spending_check,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Extract and fit-rate every ``captured`` job (oldest capture first), moving it to ``rated``
    with its ``fit_score`` (the weighted competence match the web intake shows) and ``fit_summary``.

    The extraction (competences, metadata, similar letters) is stored as the job's state, so the
    later drafting reuses it and pays for it once. A job that cannot be extracted (no CV, empty
    capture) becomes ``failed`` with the reason. When the spending limit blocks extraction, the jobs
    stay ``captured`` and are rated on a later wake.
    """
    from .firestore_store import get_user_data
    from letter_writer_server.api.extract_pipeline import run_capture_extract

    waiting = store.list_by_status(ops.CAPTURED, user_id)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    waiting.sort(key=lambda o: (ops.as_utc((o.get("capture") or {}).get("captured_at")) or ops.as_utc(o.get("updated_at")) or epoch))
    if spending_check is not None:
        blocked = spending_check(user_id)
        if blocked:
            return [{"id": o["id"], "status": ops.CAPTURED, "deferred": blocked} for o in waiting]
    report: List[Dict[str, Any]] = []
    for opp in waiting:
        opp_id = opp["id"]
        capture = opp.get("capture") or {}
        text, html = str(capture.get("text") or ""), str(capture.get("html") or "")
        if not text.strip() and not html.strip():
            _rate_failed(store, opp, user_id, "The job has no captured posting text.")
            report.append({"id": opp_id, "status": ops.FAILED, "error": "The job has no captured posting text."})
            continue
        try:
            user_data = get_user_data(user_id, use_cache=False) or {}
            data = headless.initial_session(user_id, user_data)
            if not str(data.get("cv_text") or "").strip():
                raise BatchError("No CV in the profile (personal_data.cv_revisions is empty).")
            fingerprint = capture_fingerprint(text, html)
            session_key = f"opportunity-{opp_id}"
            with headless.headless_session(data, session_key) as sess:
                extract = run_capture_extract(cast(Any, sess), visible_text=text, html=html, source_url=str(opp.get("url") or ""))
                sess["selected_top_docs"] = list(extract.get("top_docs") or [])
                state = dict(sess)
            extraction = extract.get("extraction") or {}
            state["capture_fingerprint"] = fingerprint
            state["vendors"] = {}
            score = fit_scores.fit_score(extraction.get("competences"))
            fields: Dict[str, Any] = {
                "fit_score": score,
                "fit_summary": fit_summary(extraction),
                "fit_rated_at": datetime.now(timezone.utc),
            }
            for field, key in (("title", "job_title"), ("company", "company_name"), ("location", "location")):
                if not str(opp.get(field) or "").strip() and extraction.get(key):
                    fields[field] = str(extraction[key]).strip()
            if dry_run:
                report.append({"id": opp_id, "status": ops.RATED, "fit_score": score, "dry_run": True})
                continue
            store.save_state(opp_id, headless.persistable_state(state))
            store.set_status(opp_id, ops.RATED, from_states=[ops.CAPTURED], user_id=user_id, fields=fields)
            report.append({"id": opp_id, "status": ops.RATED, "fit_score": score})
        except Exception as exc:
            logger.exception("rating %s failed", opp_id)
            _rate_failed(store, opp, user_id, f"{type(exc).__name__}: {exc}")
            report.append({"id": opp_id, "status": ops.FAILED, "error": str(exc)[:200]})
    return report


def archive_expired(
    store: ops.OpportunityStore,
    user_id: str,
    archive_days: float = DEFAULT_ARCHIVE_DAYS,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Rated jobs that were never drafted within ``archive_days`` go to ``archived`` — the desktop
    leaves them alone from then on, unless the user re-enables them (possibly with a new fit
    estimate)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=archive_days)
    out: List[Dict[str, Any]] = []
    for opp in store.list_by_status(ops.RATED, user_id):
        rated_at = ops.as_utc(opp.get("fit_rated_at")) or ops.as_utc(opp.get("updated_at")) or ops.as_utc(opp.get("created_at"))
        if not rated_at or rated_at > cutoff:
            continue
        try:
            store.set_status(
                opp["id"],
                ops.ARCHIVED,
                from_states=[ops.RATED],
                user_id=user_id,
                fields={"archived_at": now, "archive_reason": f"Not drafted within {archive_days:g} days."},
            )
        except (ops.TransitionError, KeyError):
            continue  # drafted or re-enabled between the list and the move
        out.append({"id": opp["id"], "status": ops.ARCHIVED, "fit_score": opp.get("fit_score")})
    return out


def processed_in_window(
    store: ops.OpportunityStore,
    user_id: str,
    *,
    window: timedelta = ROLLING_CAP_WINDOW,
    now: Optional[datetime] = None,
) -> int:
    """How many jobs the desktop sent to drafting within the rolling window (``processed_at`` is
    stamped when a rated or captured job is claimed for drafting)."""
    now = now or datetime.now(timezone.utc)
    start = now - window
    count = 0
    for opp in store.list_for_user(user_id):
        at = ops.as_utc(opp.get("processed_at"))
        if at is not None and start <= at <= now:
            count += 1
    return count


def select_for_drafting(
    store: ops.OpportunityStore,
    user_id: str,
    daily_cap: int = DEFAULT_DAILY_CAP,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """The best ``rated`` jobs under the rolling 24h cap: effective fit (the user's
    ``fit_score_user`` override wins over the computed ``fit_score``) descending, oldest rating
    first, jobs with no score last. Never more than ``daily_cap`` minus the jobs already drafted in
    the last 24 hours."""
    now = now or datetime.now(timezone.utc)
    slots = max(0, int(daily_cap) - processed_in_window(store, user_id, now=now))
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    rated = store.list_by_status(ops.RATED, user_id)
    rated.sort(
        key=lambda o: (
            fit_scores.effective_fit(o) is None,
            -(fit_scores.effective_fit(o) or 0.0),
            ops.as_utc(o.get("fit_rated_at")) or epoch,
            o["id"],
        )
    )
    return rated[:slots]


def run_cycle(
    store: ops.OpportunityStore,
    user_id: str,
    *,
    daily_cap: int = DEFAULT_DAILY_CAP,
    archive_days: float = DEFAULT_ARCHIVE_DAYS,
    cli_vendors: Optional[Sequence[str]] = None,
    settings: DraftSettings = DraftSettings(),
    research_vendor: str = "openai",
    spending_check: Optional[Callable[[str], Optional[str]]] = default_spending_check,
    owner: Optional[str] = None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """One wake of the daemon: archive expired rated jobs, extract and fit-rate every captured
    job, then draft the best rated ones under the rolling 24h cap. Returns what happened, for the
    routine's log."""
    now = now or datetime.now(timezone.utc)
    archived = archive_expired(store, user_id, archive_days, now=now)
    rated = rate_captured(store, user_id, spending_check=spending_check, dry_run=dry_run)
    picked = select_for_drafting(store, user_id, daily_cap, now=now)
    drafted: List[Dict[str, Any]] = []
    if not dry_run:
        owner = owner or f"batch-{socket.gethostname()}-{os.getpid()}"
        for opp in picked:
            claimed = store.claim_for_drafting(opp["id"], owner, LEASE_S, user_id=user_id)
            if claimed is None:
                continue  # another run took it between the pick and the claim
            drafted.append(
                _draft_claimed(
                    store, claimed, owner, user_id,
                    cli_vendors=cli_vendors, settings=settings,
                    research_vendor=research_vendor, spending_check=spending_check,
                )
            )
    return {
        "archived": archived,
        "rated": rated,
        "picked": [o["id"] for o in picked],
        "drafted": drafted,
        # A fresh "now": the claims of this cycle happened after the cycle's own start.
        "cap": {"daily_cap": int(daily_cap), "processed_last_24h": processed_in_window(store, user_id)},
    }


def run_daemon(
    store: ops.OpportunityStore,
    user_id: str,
    *,
    interval_hours: float = DEFAULT_WAKE_INTERVAL_HOURS,
    cycles: Optional[int] = None,
    sleep: Callable[[float], None] = time.sleep,
    **cycle_kwargs: Any,
) -> List[Dict[str, Any]]:
    """Wake every ``interval_hours`` and run one cycle; ``cycles`` bounds the loop (None: until
    interrupted). The first cycle runs at once, so a night missed while the machine was off
    collapses into one catch-up."""
    reports: List[Dict[str, Any]] = []
    cycle = 0
    while cycles is None or cycle < cycles:
        started = datetime.now(timezone.utc)
        try:
            report = run_cycle(store, user_id, **cycle_kwargs)
        except Exception:
            logger.exception("daemon cycle failed")
            report = {"error": "cycle failed"}
        reports.append(report)
        print(json.dumps(report), flush=True)
        cycle += 1
        if cycles is not None and cycle >= cycles:
            break
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        sleep(max(60.0, interval_hours * 3600.0 - elapsed))
    return reports


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
    if counts[ops.RATED]:
        parts.append(f"rated {counts[ops.RATED]}")
    if counts[ops.DRAFTING]:
        parts.append(f"drafting {counts[ops.DRAFTING]}")
    parts.append(f"ready {counts[ops.READY]}" + (f" ({questions} questions)" if questions else ""))
    if counts[ops.FAILED]:
        parts.append(f"failed {counts[ops.FAILED]}")
    if counts[ops.ARCHIVED]:
        parts.append(f"archived {counts[ops.ARCHIVED]}")
    processed = processed_in_window(store, user_id)
    if processed:
        parts.append(f"drafted last 24h {processed}/{DEFAULT_DAILY_CAP}")
    return " · ".join(parts)


def retry(store: ops.OpportunityStore, user_id: str, opp_id: str) -> Dict[str, Any]:
    return store.set_status(opp_id, ops.CAPTURED, from_states=[ops.FAILED, ops.READY], user_id=user_id, fields={"vendors_failed": {}})


# --- CLI ---------------------------------------------------------------------------------------


def _env_number(name: str, default: float, cast: Callable[[Any], Any] = float) -> Any:
    """A numeric env var, falling back to ``default`` when unset or malformed."""
    try:
        return cast(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


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
    dn = sub.add_parser("daemon", help="the scheduled path: wake on an interval, rate new jobs, draft the best under the rolling cap")
    dn.add_argument("--once", action="store_true", help="run a single cycle and exit (the systemd timer uses this)")
    dn.add_argument("--interval-hours", type=float, default=_env_number("LW_WAKE_INTERVAL_HOURS", DEFAULT_WAKE_INTERVAL_HOURS), help="how often the daemon wakes (default 3)")
    dn.add_argument("--daily-cap", type=int, default=_env_number("LW_DAILY_CAP", DEFAULT_DAILY_CAP, int), help="letters drafted per rolling 24 hours (default 5)")
    dn.add_argument("--archive-days", type=float, default=_env_number("LW_ARCHIVE_DAYS", DEFAULT_ARCHIVE_DAYS), help="a rated job not drafted within this many days is archived (default 3)")
    dn.add_argument("--vendors", help="comma-separated, e.g. claude_code,openai")
    dn.add_argument(
        "--rewrite-rounds", type=int, choices=range(0, MAX_REWRITE_ROUNDS + 1), default=1,
        help="comments → rewrite rounds for jobs that don't say (default 1)",
    )
    dn.add_argument(
        "--final-feedback", action=argparse.BooleanOptionalAction, default=True,
        help="comment the last version for jobs that don't say (default on)",
    )
    dn.add_argument("--research-vendor", default=os.environ.get("LW_RESEARCH_VENDOR", "openai"))
    dn.add_argument("--dry-run", action="store_true")
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
    elif args.command == "daemon":
        vendors = [v for v in (args.vendors or "").split(",") if v.strip()] or None
        cycle_kwargs = dict(
            daily_cap=args.daily_cap,
            archive_days=args.archive_days,
            cli_vendors=vendors,
            settings=DraftSettings(rewrite_rounds=args.rewrite_rounds, final_feedback=args.final_feedback),
            research_vendor=args.research_vendor,
            dry_run=args.dry_run,
        )
        if args.once:
            print(json.dumps(run_cycle(store, user_id, **cycle_kwargs)))
        else:
            run_daemon(store, user_id, interval_hours=args.interval_hours, **cycle_kwargs)
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
