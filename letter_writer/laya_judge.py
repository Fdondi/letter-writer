"""Local Laya judgments for RAG similarity and feedback comments.

Laya (https://huggingface.co/convaiinnovations/laya) returns calibrated
probabilities. It does not write the similarity bullets; the language model
still does that. The numeric RAG score and the valid/invalid comment judgment
come from Laya when the package is installed.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional

from .laya_device import resolve_laya_device, torch, torch_directml

logger = logging.getLogger(__name__)

# Optional. A missing install must not stop the server from importing.
try:
    from laya import Router
except (ImportError, OSError):
    Router = None  # type: ignore[assignment,misc]

os.environ.setdefault("USE_TF", "0")

PredictFn = Callable[[Any, Dict[str, Any]], Dict[str, Any]]

RAG_SIMILARITY_QUESTION: Dict[str, Any] = {
    "similarity": {
        "type": "score",
        "instructions": (
            "How similar is the candidate job to the target job in role focus and day-to-day tasks?"
        ),
        "criteria": [
            "only the most basic tools or duties overlap",
            "some overlap, but the jobs are significantly different",
            "partial overlap of the key tasks",
            "most key tasks match, with one major difference",
            "nearly identical in both focus and tasks",
        ],
    }
}

FEEDBACK_GROUNDED_QUESTION: Dict[str, Any] = {
    "grounded": {
        "type": "noul",
        "instructions": (
            "Is this feedback comment a genuine issue or observation that the letter text "
            "and quoted span actually support? Answer no when the comment invents a problem, "
            "contradicts the letter, or is not about the text it cites."
        ),
    }
}

_RUNTIME_LOCK = threading.Lock()
_RUNTIME: Optional["_LayaRuntime"] = None
_UNAVAILABLE: Optional[str] = None


class LayaUnavailable(RuntimeError):
    """Laya cannot run in this process. The message is safe to show in the UI."""


def comment_is_laya_hidden(item: Mapping[str, Any]) -> bool:
    """True when Laya marked a comment invalid and the user has not restored it."""
    if item.get("laya_restored") is True:
        return False
    return str(item.get("laya_verdict") or "").strip().lower() == "invalid"


def map_similarity_score(expected: float) -> int:
    """Map Laya's 0..4 similarity expectation onto the existing 1..10 rubric.

    The five criteria line up with rubric scores 2, 4, 6, 8, and 10.
    """
    clamped = min(4.0, max(0.0, float(expected)))
    return max(1, min(10, int(round(2.0 + clamped * 2.0))))


def verdict_from_noul(
    probability: float,
    confidence: float,
    *,
    valid_min: float,
    confidence_min: float,
) -> str:
    """Hide a comment only when Laya is confident it is ungrounded.

    A low probability with low confidence stays visible. Hiding a real critique
    is worse than leaving a doubtful one in the open list.
    """
    if float(probability) >= valid_min or float(confidence) < confidence_min:
        return "valid"
    return "invalid"


def feedback_valid_min() -> float:
    return _env_float("LAYA_FEEDBACK_VALID_MIN", 0.40)


def feedback_confidence_min() -> float:
    return _env_float("LAYA_FEEDBACK_INVALID_MIN_CONFIDENCE", 0.55)


def rag_state(target_job: str, company: str, candidate_job: str) -> str:
    """Prefix kept by Laya's truncator: both openings, candidate first."""
    return (
        f"Candidate company: {company}\n"
        f"Candidate job opening:\n{(candidate_job or '')[:800]}\n\n"
        f"Target job opening:\n{(target_job or '')[:800]}"
    )


def feedback_state(letter: str, item: Mapping[str, Any], category: str) -> str:
    quote = str(item.get("matched_text") or item.get("quote") or "").strip()
    observation = str(item.get("observation") or "").strip()
    window = _letter_window(letter or "", quote)
    return (
        f"Feedback comment:\n{observation[:800]}\n\n"
        f"Quoted span:\n{quote[:500]}\n\n"
        f"Topic: {category}\n\n"
        f"Letter text:\n{window[:1500]}"
    )


def apply_laya_rag_scores(
    job_text: str,
    retrieved_docs: Mapping[str, Mapping[str, Any]],
    reranked: MutableMapping[str, dict],
    *,
    predict: Optional[PredictFn] = None,
) -> Dict[str, Any]:
    """Rescore each reranked job with Laya. Language-model bullets stay as they are.

    ``details['score']`` becomes the Laya score when a judgment succeeds.
    ``llm_score`` always keeps the language-model score. On failure the language-model
    score stays in ``score`` and ``laya_error`` says why.
    """
    for details in reranked.values():
        details["llm_score"] = int(details["score"])

    status = _runtime_status(predict)
    if not status["available"]:
        _stamp_rag_failure(reranked, status)
        logger.warning("Laya RAG scoring unavailable: %s", status["detail"])
        return status

    runner = predict or _runtime().predict
    for company, details in reranked.items():
        candidate = str((retrieved_docs.get(company) or {}).get("job_text") or "")
        state = rag_state(job_text, company, candidate)
        try:
            result = _call_predict(runner, state, RAG_SIMILARITY_QUESTION)
            expected, confidence, routed = _score_answer(result)
        except Exception as exc:
            details["score_source"] = "llm"
            details["laya_error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("Laya RAG score failed for %s: %s", company, details["laya_error"])
            continue
        details["score"] = map_similarity_score(expected)
        details["laya_score"] = details["score"]
        details["laya_confidence"] = confidence
        details["score_source"] = "laya"
        details["laya_device"] = str(result.get("laya_device") or status["device"])
        details["laya_model"] = routed
    return status


def annotate_feedback_validity(
    feedback: MutableMapping[str, list],
    letter: str,
    *,
    predict: Optional[PredictFn] = None,
) -> Dict[str, Any]:
    """Mark PLEASE_FIX comments valid or invalid. Invalid ones stay on the item."""
    status = _runtime_status(predict)
    if not status["available"]:
        _stamp_feedback_unscored(feedback, status["detail"])
        logger.warning("Laya feedback scoring unavailable: %s", status["detail"])
        return status

    runner = predict or _runtime().predict
    valid_min = feedback_valid_min()
    confidence_min = feedback_confidence_min()
    for category, items in feedback.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").upper() != "PLEASE_FIX":
                continue
            if not str(item.get("observation") or "").strip():
                continue
            if item.get("laya_restored") is True:
                continue
            state = feedback_state(letter, item, str(category))
            try:
                result = _call_predict(runner, state, FEEDBACK_GROUNDED_QUESTION)
                probability, confidence, routed = _noul_answer(result)
            except Exception as exc:
                item["laya_verdict"] = "unscored"
                item["laya_error"] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Laya feedback score failed for %s: %s",
                    item.get("id"),
                    item["laya_error"],
                )
                continue
            item["laya_verdict"] = verdict_from_noul(
                probability,
                confidence,
                valid_min=valid_min,
                confidence_min=confidence_min,
            )
            item["laya_valid_probability"] = probability
            item["laya_confidence"] = confidence
            item["laya_model"] = routed
            item["laya_device"] = str(result.get("laya_device") or status["device"])
    return status


class _LayaRuntime:
    def __init__(self) -> None:
        if Router is None:
            raise LayaUnavailable(
                "laya is not installed. See docs/LAYA_LOCAL.md for Windows and Linux installs."
            )
        kind, detail = resolve_laya_device()
        self.device_kind = kind
        self.detail = detail
        self.device_label = detail
        if kind != (os.environ.get("LAYA_DEVICE") or "auto").strip().lower() and (
            os.environ.get("LAYA_DEVICE") or "auto"
        ).strip().lower() not in ("", "auto"):
            logger.warning("Laya device: %s", detail)
        router_device = "cpu" if kind == "directml" else kind
        self._router = Router(device=router_device, max_loaded=1)
        self._moved: set[str] = set()
        self._directml_error = ""
        self._infer_lock = threading.Lock()
        logger.info("Laya runtime ready on %s (%s)", kind, detail)

    def predict(
        self,
        state: Any,
        questions: Dict[str, Any],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._infer_lock:
            decision = self._router.route(state, questions, model=model)
            agent = self._router.load(decision["model"])
            self._place(agent, decision["model"])
            try:
                result = agent.system_one(state, questions)
            except Exception as exc:
                if self.device_kind != "directml":
                    raise
                self._directml_error = f"{type(exc).__name__}: {exc}"
                self.device_kind = "cpu"
                self.device_label = f"cpu (DirectML inference failed: {self._directml_error})"
                logger.warning("Laya left DirectML for CPU: %s", self._directml_error)
                self._move_agent_to_cpu(agent)
                result = agent.system_one(state, questions)
            result["routing"] = dict(decision)
            result["laya_device"] = self.device_label
            return result

    def _move_agent_to_cpu(self, agent: Any) -> None:
        if torch is None:
            return
        agent.dtype = torch.float32
        agent.device = torch.device("cpu")
        agent.model.to(agent.device).eval()

    def _place(self, agent: Any, key: str) -> None:
        if self.device_kind != "directml" or key in self._moved or self._directml_error:
            return
        if torch is None or torch_directml is None:
            self._directml_error = "torch-directml is not importable"
            self.device_kind = "cpu"
            self.device_label = f"cpu ({self._directml_error})"
            logger.warning("Laya DirectML move skipped: %s", self._directml_error)
            return
        try:
            device = torch_directml.device()
            agent.dtype = torch.float32
            agent.model.to(device).eval()
            agent.device = device
        except Exception as exc:
            self._directml_error = f"{type(exc).__name__}: {exc}"
            self.device_kind = "cpu"
            self.device_label = f"cpu (DirectML failed: {self._directml_error})"
            logger.warning("Laya stayed on CPU after DirectML failed: %s", self._directml_error)
            return
        self._moved.add(key)
        name = self.detail
        self.device_label = f"directml:{name}" if name else "directml"


def _runtime() -> _LayaRuntime:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = _LayaRuntime()
        return _RUNTIME


def _runtime_status(predict: Optional[PredictFn]) -> Dict[str, Any]:
    global _UNAVAILABLE
    if predict is not None:
        return {"available": True, "device": "test", "detail": "injected predictor"}
    if _UNAVAILABLE is not None:
        return {"available": False, "device": "", "detail": _UNAVAILABLE}
    try:
        runtime = _runtime()
    except LayaUnavailable as exc:
        _UNAVAILABLE = str(exc)
        return {"available": False, "device": "", "detail": _UNAVAILABLE}
    return {
        "available": True,
        "device": runtime.device_label,
        "detail": runtime.detail,
    }


def _call_predict(runner: PredictFn, state: Any, questions: Dict[str, Any]) -> Dict[str, Any]:
    model = _model_override()
    if model:
        return runner(state, questions, model=model)  # type: ignore[call-arg]
    return runner(state, questions)


def _model_override() -> Optional[str]:
    raw = (os.environ.get("LAYA_MODEL") or "").strip()
    return raw or None


def _stamp_rag_failure(reranked: MutableMapping[str, dict], status: Mapping[str, Any]) -> None:
    for details in reranked.values():
        details["score_source"] = "llm"
        details["laya_error"] = str(status.get("detail") or "Laya unavailable")


def _stamp_feedback_unscored(feedback: Mapping[str, list], detail: str) -> None:
    for items in feedback.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").upper() != "PLEASE_FIX":
                continue
            if item.get("laya_verdict"):
                continue
            item["laya_verdict"] = "unscored"
            item["laya_error"] = detail


def _score_answer(result: Mapping[str, Any]) -> tuple[float, float, str]:
    answer = (result.get("answers") or {}).get("similarity") or {}
    if "score" not in answer:
        raise LayaUnavailable(f"Laya similarity answer missing score: {answer!r}")
    routed = str(((result.get("routing") or {}).get("model")) or "")
    return float(answer["score"]), float(answer.get("confidence") or 0.0), routed


def _noul_answer(result: Mapping[str, Any]) -> tuple[float, float, str]:
    answer = (result.get("answers") or {}).get("grounded") or {}
    if "noul" not in answer:
        raise LayaUnavailable(f"Laya grounded answer missing noul: {answer!r}")
    routed = str(((result.get("routing") or {}).get("model")) or "")
    return float(answer["noul"]), float(answer.get("confidence") or 0.0), routed


def _letter_window(letter: str, quote: str) -> str:
    if not letter:
        return ""
    if quote:
        at = letter.find(quote)
        if at >= 0:
            start = max(0, at - 400)
            end = min(len(letter), at + len(quote) + 800)
            return letter[start:end]
    return letter[:1500]


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r is not a float; using %s", name, raw, default)
        return default
