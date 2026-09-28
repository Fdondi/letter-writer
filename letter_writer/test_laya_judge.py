"""Laya scoring decisions without downloading the checkpoint."""

from letter_writer.feedback_checks import normalize_feedback_value
from letter_writer.laya_device import choose_laya_device
from letter_writer.laya_judge import (
    apply_laya_rag_scores,
    annotate_feedback_validity,
    comment_is_laya_hidden,
    map_similarity_score,
    verdict_from_noul,
)
from letter_writer.rewrite import _rewrite_dimension_text


def test_device_priority_cuda_then_directml_then_cpu():
    kind, detail = choose_laya_device(
        "auto",
        cuda_available=True,
        cuda_name="NVIDIA",
        directml_available=True,
        directml_name="Radeon",
    )
    assert kind == "cuda"
    assert detail == "NVIDIA"

    kind, detail = choose_laya_device(
        "auto",
        cuda_available=False,
        directml_available=True,
        directml_name="AMD Radeon Graphics",
    )
    assert kind == "directml"
    assert "Radeon" in detail

    kind, detail = choose_laya_device(
        "auto",
        cuda_available=False,
        directml_available=False,
    )
    assert kind == "cpu"
    assert "7735HS" in detail


def test_requested_cuda_without_a_device_says_so():
    kind, detail = choose_laya_device("cuda", cuda_available=False, directml_available=False)
    assert kind == "cpu"
    assert "LAYA_DEVICE=cuda" in detail


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
