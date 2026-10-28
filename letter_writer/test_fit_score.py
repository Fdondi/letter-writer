"""The fit score the desktop rates jobs with: a port of the web intake's weighted match.

``IntakePage.jsx`` averages each competence's CV level weighted by the job's need for it; the
scales are ``letter_writer_web/src/utils/competenceScales.js``. These tests pin the port against
hand-computed values (the fake LLM's extraction is rated 3.5 in ``test_batch.py``).
"""
import math

import pytest

from letter_writer import fit_score


def _log_importance(x):
    # The JS logScaleImportance, re-derived: y = a·ln(1+x) + b with a = 4/ln3, b = 1 − a·ln2.
    a = 4 / math.log(3)
    b = 1 - a * math.log(2)
    return max(1.0, min(5.0, a * math.log(1 + x) + b))


def test_single_competence_scores_its_cv_level():
    assert fit_score.fit_score({"Python": {"need": "critical", "level": "Professional"}}) == 4.0
    assert fit_score.fit_score({"Python": {"need": "nice to have", "level": "Newbie"}}) == 1.0


def test_weighted_average_over_needs():
    # critical/Professional (4×5) against nice to have/Newbie (1×2): 22/7 ≈ 3.1.
    comps = {
        "FixtureStack": {"need": "critical", "level": "Professional"},
        "HobbyTool": {"need": "nice to have", "level": "Newbie"},
    }
    assert fit_score.fit_score(comps) == pytest.approx(22 / 7, abs=0.05)


def test_expected_need_is_log_scaled():
    # The fake extraction: critical/Professional plus expected/Brief experience.
    expected_importance = _log_importance(4)
    comps = {
        "FixtureStack": {"need": "critical", "level": "Professional"},
        "FixtureLang": {"need": "expected", "level": "Brief experience"},
    }
    want = (4 * 5 + 3 * expected_importance) / (5 + expected_importance)
    assert fit_score.fit_score(comps) == pytest.approx(round(want, 1), abs=1e-9)
    # Without the log scale ("expected" linear at 4) the score would be lower.
    assert fit_score.fit_score(comps) < (4 * 5 + 3 * 4) / (5 + 4) + 0.05


def test_labels_are_case_insensitive_and_unknown_labels_are_skipped():
    comps = {
        "Python": {"need": "Critical", "level": "professional"},
        "Mystery": {"need": "sometimes", "level": "Professional"},
        "AlsoMystery": {"need": "critical", "level": "Wizard"},
        "NotADict": "nope",
    }
    assert fit_score.fit_score(comps) == 4.0


def test_no_usable_competences_scores_none():
    assert fit_score.fit_score(None) is None
    assert fit_score.fit_score({}) is None
    assert fit_score.fit_score({"Python": {"need": "critical"}}) is None


def test_normalize_score_clamps_and_clears():
    assert fit_score.normalize_score(4.26) == 4.3
    assert fit_score.normalize_score(0) == 1.0
    assert fit_score.normalize_score(9) == 5.0
    assert fit_score.normalize_score(None) is None
    assert fit_score.normalize_score("abc") is None
    assert fit_score.normalize_score(True) is None


def test_effective_fit_prefers_the_user_override():
    assert fit_score.effective_fit({"fit_score": 3.5, "fit_score_user": 4.5}) == 4.5
    assert fit_score.effective_fit({"fit_score": 3.5}) == 3.5
    assert fit_score.effective_fit({"fit_score_user": 2}) == 2.0
    assert fit_score.effective_fit({}) is None
