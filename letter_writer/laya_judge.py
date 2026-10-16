"""Laya judgments for RAG similarity and feedback comments.

Scores come from an Ollaya server (https://github.com/ollaya-dev/ollaya),
the container in docker-compose.yml. Laya returns calibrated probabilities.
It does not write the similarity bullets; the language model still does that.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional

import httpx

from . import prompts

logger = logging.getLogger(__name__)

PredictFn = Callable[[Any, Dict[str, Any]], Dict[str, Any]]

_DEFAULT_OLLAYA_URL = "http://ollaya:11435"
_DECIDE_TIMEOUT_S = 360.0
_CONNECT_TIMEOUT_S = 5.0

_QUESTIONS: Dict[str, Any] = prompts.load_json("decision_model/questions.json")
RAG_SIMILARITY_QUESTION: Dict[str, Any] = _QUESTIONS["rag"]
FEEDBACK_GROUNDED_QUESTION: Dict[str, Any] = _QUESTIONS["feedback"]

_RUNTIME_LOCK = threading.Lock()
_RUNTIME: Optional["_OllayaClient"] = None


class LayaUnavailable(RuntimeError):
    """Ollaya could not score this request. The message is safe to show in the UI."""


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


def ollaya_base_url() -> str:
    raw = (os.environ.get("OLLAYA_BASE_URL") or _DEFAULT_OLLAYA_URL).strip().rstrip("/")
    return raw or _DEFAULT_OLLAYA_URL


def ollaya_model_name(raw: Optional[str] = None) -> str:
    """Model name sent to Ollaya. Older local names map onto Ollaya tags."""
    if raw is None:
        raw = os.environ.get("LAYA_MODEL") or ""
    name = raw.strip() or "laya"
    return {
        "english": "laya:en",
        "multilingual": "laya:multilingual",
        "typed-decisions": "laya:typed-decisions",
    }.get(name, name)


def decide_payload(state: Any, questions: Mapping[str, Any], model: str) -> Dict[str, Any]:
    return {
        "model": model,
        "state": state,
        "questions": dict(questions),
        "extras": ["laya"],
    }


class _OllayaClient:
    """Talks to the Ollaya container. The model stays loaded there, not in this process."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.detail = f"Ollaya at {self.base_url}, model {self.model}"
        self.device_label = ""
        self._api_key = api_key
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(_DECIDE_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S),
        )
        self._lock = threading.Lock()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def probe(self) -> None:
        try:
            response = self._http.get(f"{self.base_url}/", headers=self._headers())
        except httpx.HTTPError as exc:
            raise LayaUnavailable(
                f"Ollaya is not reachable at {self.base_url}. "
                f"Start the ollaya container ({type(exc).__name__}: {exc})."
            ) from exc
        if response.status_code >= 400:
            raise LayaUnavailable(_http_error(response))
        logger.info("Ollaya reachable at %s", self.base_url)

    def predict(
        self,
        state: Any,
        questions: Dict[str, Any],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        chosen = ollaya_model_name(model) if model else self.model
        payload = decide_payload(state, questions, chosen)
        with self._lock:
            try:
                response = self._http.post(
                    f"{self.base_url}/api/decide",
                    json=payload,
                    headers=self._headers(),
                )
            except httpx.HTTPError as exc:
                raise LayaUnavailable(
                    f"Ollaya request to {self.base_url} failed ({type(exc).__name__}: {exc})."
                ) from exc
            if response.status_code >= 400:
                raise LayaUnavailable(_http_error(response))
            try:
                result = response.json()
            except ValueError as exc:
                raise LayaUnavailable(f"Ollaya returned a non-JSON decision: {exc}") from exc
            if not isinstance(result, dict):
                raise LayaUnavailable("Ollaya decision response was not a JSON object.")
            result["laya_device"] = self._device_label()
            return result

    def _headers(self) -> Dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    def _device_label(self) -> str:
        if self.device_label:
            return self.device_label
        try:
            response = self._http.get(f"{self.base_url}/api/ps", headers=self._headers())
            payload = response.json() if response.status_code < 400 else {}
        except (httpx.HTTPError, ValueError):
            return "ollaya"
        models = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and item.get("device"):
                    self.device_label = str(item["device"])
                    return self.device_label
        return "ollaya"


def _runtime() -> _OllayaClient:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            client = _OllayaClient(
                base_url=ollaya_base_url(),
                model=ollaya_model_name(),
                api_key=(os.environ.get("OLLAYA_API_KEY") or "").strip(),
            )
            try:
                client.probe()
            except LayaUnavailable:
                client.close()
                raise
            _RUNTIME = client
        return _RUNTIME


def _runtime_status(predict: Optional[PredictFn]) -> Dict[str, Any]:
    if predict is not None:
        return {"available": True, "device": "test", "detail": "injected predictor"}
    try:
        runtime = _runtime()
    except LayaUnavailable as exc:
        return {"available": False, "device": "", "detail": str(exc)}
    return {
        "available": True,
        "device": runtime.device_label or "ollaya",
        "detail": runtime.detail,
    }


def _call_predict(runner: PredictFn, state: Any, questions: Dict[str, Any]) -> Dict[str, Any]:
    model = _model_override()
    if model:
        return runner(state, questions, model=model)  # type: ignore[call-arg]
    return runner(state, questions)


def _model_override() -> Optional[str]:
    raw = (os.environ.get("LAYA_MODEL") or "").strip()
    if not raw:
        return None
    return ollaya_model_name(raw)


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
    routed = str(((result.get("routing") or {}).get("model")) or result.get("model") or "")
    return float(answer["score"]), _answer_confidence(answer), routed


def _noul_answer(result: Mapping[str, Any]) -> tuple[float, float, str]:
    answer = (result.get("answers") or {}).get("grounded") or {}
    if "noul" not in answer:
        raise LayaUnavailable(f"Laya grounded answer missing noul: {answer!r}")
    routed = str(((result.get("routing") or {}).get("model")) or result.get("model") or "")
    return float(answer["noul"]), _answer_confidence(answer), routed


def _answer_confidence(answer: Mapping[str, Any]) -> float:
    """Prefer Laya's own confidence from ``extras: ["laya"]``.

    Ollaya's noul answers have no top-level confidence. Score answers do, but that
    number is TypeSafe's spread across options, not the confidence the thresholds use.
    """
    extra = answer.get("laya")
    if isinstance(extra, Mapping) and extra.get("confidence") is not None:
        return float(extra["confidence"])
    if answer.get("confidence") is not None:
        return float(answer["confidence"])
    return 0.0


def _http_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        message = str(body.get("error") or f"HTTP {response.status_code}")
        code = str(body.get("code") or "").strip()
        if code:
            return f"{code}: {message}"
        return message
    return f"Ollaya HTTP {response.status_code}"


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
