"""The fit score the desktop rates a job with: the weighted competence match the web intake shows.

``IntakePage.jsx`` ("How good is your fit? Key competences weighted match") averages each key
competence's CV level (presence, 1–5) weighted by the job's need for it (importance, 1–5, with
"expected" log-scaled); the scales live in ``letter_writer_web/src/utils/competenceScales.js``.
The batch needs the same number to rank the rated queue, so this is a port of that formula — the
rating the user sees in the apps is the rating the desktop sorts by. The user can override it per
job (``opportunities.fit_score_user``); the override wins over the computed ``fit_score``.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

# competenceScales.js DEFAULT_NEED / DEFAULT_LEVEL (keys lowercased for tolerant matching).
DEFAULT_NEED = {
    "critical": 5,
    "nice to have": 2,
    "expected": 4,
    "useful": 3,
    "necessary": 4,
    "marginally useful": 1,
}
DEFAULT_LEVEL = {
    "newbie": 1,
    "amateur": 2,
    "brief experience": 3,
    "professional": 4,
    "senior professional": 5,
}
# DEFAULT_NEED_SCALE: "expected" is log-scaled, every other need linear.
LOG_SCALED_NEEDS = frozenset({"expected"})

MIN_SCORE = 1.0
MAX_SCORE = 5.0


def _log_scale_importance(x: float) -> float:
    """Port of ``logScaleImportance``: map x in [1,5] to [1,5] via log(1+x)."""
    a = 4 / math.log(3)
    b = 1 - a * math.log(2)
    return max(1.0, min(5.0, a * math.log(1 + x) + b))


def normalize_score(value: Any) -> Optional[float]:
    """A user-typed fit estimate as a 1–5 float with one decimal, or None when cleared/invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return round(max(MIN_SCORE, min(MAX_SCORE, score)), 1)


def fit_score(competences: Optional[Dict[str, Any]]) -> Optional[float]:
    """Importance-weighted average CV level over the extracted competences, 1–5 with one decimal.

    ``competences`` is the extraction's ``{skill: {"need": label, "level": label}}``. Skills whose
    need or level label is unknown are skipped; None when nothing usable was extracted.
    """
    total_weighted = 0.0
    total_weight = 0.0
    for comp in (competences or {}).values():
        if not isinstance(comp, dict):
            continue
        need = str(comp.get("need") or "").strip().lower()
        presence = DEFAULT_LEVEL.get(str(comp.get("level") or "").strip().lower())
        importance = DEFAULT_NEED.get(need)
        if presence is None or importance is None:
            continue
        if need in LOG_SCALED_NEEDS:
            importance = _log_scale_importance(importance)
        total_weighted += presence * importance
        total_weight += importance
    if total_weight <= 0:
        return None
    return round(total_weighted / total_weight, 1)


def effective_fit(opp: Dict[str, Any]) -> Optional[float]:
    """The rating a job is sorted and capped by: the user's override, else the computed score."""
    return normalize_score(opp.get("fit_score_user")) if opp.get("fit_score_user") is not None else normalize_score(opp.get("fit_score"))
