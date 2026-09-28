"""Laya scoring decisions against the Ollaya HTTP API, without a live server."""

import json

import httpx

from letter_writer.feedback_checks import normalize_feedback_value
from letter_writer.laya_judge import (
    LayaUnavailable,
    _OllayaClient,
    _answer_confidence,
    apply_laya_rag_scores,
    annotate_feedback_validity,
    comment_is_laya_hidden,
    decide_payload,
    map_similarity_score,
    ollaya_model_name,
    verdict_from_noul,
)
from letter_writer.rewrite import _rewrite_dimension_text


def test_ollaya_model_names():
    assert ollaya_model_name("") == "laya"
    assert ollaya_model_name("laya") == "laya"
    assert ollaya_model_name("english") == "laya:en"
    assert ollaya_model_name("multilingual") == "laya:multilingual"
    assert ollaya_model_name("typed-decisions") == "laya:typed-decisions"
    assert ollaya_model_name("laya:en") == "laya:en"


def test_noul_confidence_comes_from_laya_extra():
    assert _answer_confidence({"noul": 0.1, "confidence": 0.8}) == 0.8
    assert _answer_confidence({"noul": 0.1, "laya": {"confidence": 0.66}}) == 0.66
    assert _answer_confidence({"score": 1.0, "confidence": 0.98, "laya": {"confidence": 0.4}}) == 0.4
    assert _answer_confidence({"noul": 0.1}) == 0.0


def test_ollaya_decide_sends_laya_extra_and_reads_device():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/decide":
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "model": "laya:en",
                    "answers": {"similarity": {"score": 2.0, "confidence": 0.4}},
                    "routing": {"model": "laya:en", "route": "english"},
                },
            )
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "laya:en", "device": "cpu"}]})
        return httpx.Response(404, json={"error": "missing", "code": "NOT_FOUND"})

    client = _OllayaClient(
        base_url="http://ollaya:11435",
        model="laya",
        api_key="",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.predict("a job opening", {"similarity": {"type": "score", "criteria": ["a", "b"]}})
    assert seen["body"] == decide_payload(
        "a job opening",
        {"similarity": {"type": "score", "criteria": ["a", "b"]}},
        "laya",
    )
    assert result["laya_device"] == "cpu"
    assert result["routing"]["model"] == "laya:en"


def test_ollaya_missing_model_is_an_error_not_a_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": 'model "laya" not found, try pulling it first',
                "code": "MODEL_NOT_FOUND",
            },
        )

    client = _OllayaClient(
        base_url="http://ollaya:11435",
        model="laya",
        api_key="",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    try:
        client.predict("state", {"similarity": {"type": "score"}})
    except LayaUnavailable as exc:
        message = str(exc)
    else:
        raise AssertionError("missing model should fail")
    assert "MODEL_NOT_FOUND" in message
    assert "try pulling it first" in message


def test_similarity_rubric_mapping():
    assert map_similarity_score(0) == 2
    assert map_similarity_score(1) == 4
    assert map_similarity_score(2) == 6
    assert map_similarity_score(3) == 8
    assert map_similarity_score(4) == 10
    assert map_similarity_score(1.5) == 5


def test_invalid_only_when_confident():
    assert verdict_from_noul(0.1, 0.9, valid_min=0.4, confidence_min=0.55) == "invalid"
    assert verdict_from_noul(0.1, 0.2, valid_min=0.4, confidence_min=0.55) == "valid"
    assert verdict_from_noul(0.8, 0.9, valid_min=0.4, confidence_min=0.55) == "valid"


def test_rag_score_replaces_sort_key_and_keeps_model_score():
    def predict(state, questions):
        expected = 4.0 if "Acme" in state else 0.0
        return {
            "answers": {"similarity": {"score": expected, "confidence": 0.7}},
            "routing": {"model": "english"},
            "laya_device": "cpu",
        }

    reranked = {
        "Acme": {"score": 3, "comment": "", "similarities": [], "differences": []},
        "Other": {"score": 9, "comment": "", "similarities": [], "differences": []},
    }
    status = apply_laya_rag_scores(
        "target role",
        {"Acme": {"job_text": "a"}, "Other": {"job_text": "b"}},
        reranked,
        predict=predict,
    )
    assert status["available"] is True
    assert reranked["Acme"]["score"] == 10
    assert reranked["Acme"]["llm_score"] == 3
    assert reranked["Acme"]["score_source"] == "laya"
    assert reranked["Other"]["score"] == 2
    assert reranked["Other"]["llm_score"] == 9


def test_rag_failure_keeps_language_model_score():
    def predict(state, questions):
        raise RuntimeError("weights missing")

    reranked = {"Acme": {"score": 6, "comment": "", "similarities": [], "differences": []}}
    apply_laya_rag_scores("target", {"Acme": {"job_text": "a"}}, reranked, predict=predict)
    assert reranked["Acme"]["score"] == 6
    assert reranked["Acme"]["score_source"] == "llm"
    assert "weights missing" in reranked["Acme"]["laya_error"]


def test_feedback_invalid_is_hidden_until_restored_and_skipped_on_rewrite():
    def predict(state, questions):
        probability = 0.05 if "invented certificate" in state else 0.9
        return {
            "answers": {"grounded": {"noul": probability, "confidence": 0.92}},
            "routing": {"model": "multilingual"},
        }

    feedback = {
        "accuracy": [
            {"id": "real", "type": "PLEASE_FIX", "observation": "The letter says fluent German."},
            {"id": "fake", "type": "PLEASE_FIX", "observation": "invented certificate"},
            {"id": "good", "type": "ALREADY_GOOD", "observation": "Tone is fine."},
        ]
    }
    annotate_feedback_validity(feedback, "I write in German.", predict=predict)
    by_id = {item["id"]: item for item in feedback["accuracy"]}
    assert by_id["real"]["laya_verdict"] == "valid"
    assert by_id["fake"]["laya_verdict"] == "invalid"
    assert "laya_verdict" not in by_id["good"]
    assert comment_is_laya_hidden(by_id["fake"]) is True

    rewritten = _rewrite_dimension_text(feedback["accuracy"])
    assert "fluent German" in rewritten
    assert "invented certificate" not in rewritten

    by_id["fake"]["laya_restored"] = True
    assert comment_is_laya_hidden(by_id["fake"]) is False
    assert "invented certificate" in _rewrite_dimension_text(feedback["accuracy"])

    normalized = normalize_feedback_value(feedback["accuracy"], category_key="accuracy")
    restored = next(item for item in normalized if item["id"] == "fake")
    assert restored["laya_verdict"] == "invalid"
    assert restored["laya_restored"] is True
