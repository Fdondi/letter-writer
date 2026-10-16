"""Render every shared prompt for fixed inputs and write (or check) golden output.

Usage (from repo root):
    python scripts/prompts/capture_golden.py          # rewrite expected.json
    python scripts/prompts/capture_golden.py --check  # fail if output differs

Inputs live in letter_writer/prompts/golden/inputs.json. The Android app's unit
tests render the same cases and compare against expected.json, so desktop and
phone prompts cannot drift apart silently.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from letter_writer.clients.base import BaseClient, ModelRole  # noqa: E402
from letter_writer.feedback_checks import (  # noqa: E402
    accuracy_check,
    company_fit_check,
    get_phased_feedback_checker_prompts,
    goal_fit_check,
    human_check,
    instruction_check,
    precision_check,
    run_suggest_additional_feedback_context,
    user_fit_check,
)
from letter_writer.feedback_review import (  # noqa: E402
    FEEDBACK_CATEGORY_KEYS,
    _build_justification_context,
    _stage12_batch,
    _stage3_duplicate_groups,
    _stage4_input_clusters,
)
from letter_writer.instructions import company_research  # noqa: E402
from letter_writer.job_extraction import (  # noqa: E402
    extract_job_metadata_no_requirements,
    extract_key_competences,
    grade_competence_cv_match,
)
from letter_writer.language_settings import (  # noqa: E402
    build_language_system_prefix,
    build_translation_system_message,
)
from letter_writer.laya_judge import (  # noqa: E402
    FEEDBACK_GROUNDED_QUESTION,
    RAG_SIMILARITY_QUESTION,
    feedback_state,
    rag_state,
)
from letter_writer.letter_generation import (  # noqa: E402
    fancy_letter,
    generate_letter,
    generate_letter_plan,
)
from letter_writer.retrieval import rerank_documents  # noqa: E402
from letter_writer.rewrite import rewrite_letter  # noqa: E402

GOLDEN_DIR = ROOT / "letter_writer" / "prompts" / "golden"


class RecordingClient(BaseClient):
    """Captures each call and returns a canned reply that parses for the caller."""

    def __init__(self, reply: str = "{}") -> None:
        super().__init__()
        self.reply = reply
        self.calls: List[Dict[str, Any]] = []

    def call(
        self,
        model_role: ModelRole | str,
        system: str,
        user_messages: List[str],
        search: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        cache_prefix: Optional[str] = None,
        system_cache_prefix: Optional[str] = None,
        prompt_cache_key: Optional[str] = None,
    ) -> str:
        self.calls.append(
            {
                "role": model_role.value if isinstance(model_role, ModelRole) else str(model_role),
                "system": system,
                "user_messages": list(user_messages),
                "search": bool(search),
                "response_format": response_format,
                "cache_prefix": cache_prefix,
                "system_cache_prefix": system_cache_prefix,
                "prompt_cache_key": prompt_cache_key,
            }
        )
        return self.reply


def _calls(reply: str, fn) -> Dict[str, Any]:
    client = RecordingClient(reply)
    result = fn(client)
    out: Dict[str, Any] = {"calls": client.calls}
    if isinstance(result, str):
        out["result"] = result
    return out


def build_cases(inp: Dict[str, Any], trace: Path) -> Dict[str, Any]:
    cv = inp["cv_text"]
    job = inp["job_text"]
    report = inp["company_report"]
    letter = inp["letter"]
    kw = inp["known_weaknesses"]
    docs = inp["top_docs"]
    add = inp["additional_user_info"]
    hire = inp["hire_problem"]
    user_data = inp["user_data"]
    lang_prefix = build_language_system_prefix(user_data, "German")

    feedback_reply = '{"items": []}'
    cases: Dict[str, Any] = {}

    cases["language_prefix_de"] = {"result": lang_prefix}
    cases["language_prefix_en"] = {"result": build_language_system_prefix(user_data, "English")}
    cases["language_prefix_it"] = {"result": build_language_system_prefix(user_data, "italiano")}
    cases["language_prefix_unknown"] = {"result": build_language_system_prefix(user_data, "")}
    cases["translation_en_from_de"] = {"result": build_translation_system_message(user_data, "en", "de")}
    cases["translation_fr"] = {"result": build_translation_system_message(user_data, "fr")}

    cases["extract_metadata"] = _calls("{}", lambda c: extract_job_metadata_no_requirements(job, c) and None)
    cases["extract_competences"] = _calls("{}", lambda c: extract_key_competences(job, c) and None)
    cases["grade_competences"] = _calls(
        "{}", lambda c: grade_competence_cv_match(inp["competences"], cv, job, c) and None
    )
    rerank_reply = json.dumps(
        {
            "scores": [
                {"company_name": name, "comment": "", "score": 5, "similarities": [], "differences": []}
                for name in inp["rerank_docs"]
            ]
        }
    )
    cases["rerank"] = _calls(rerank_reply, lambda c: rerank_documents(job, inp["rerank_docs"], c, trace) and None)

    cases["research_custom"] = _calls(
        "report",
        lambda c: company_research(
            inp["company_name"],
            job,
            c,
            trace,
            additional_company_info=inp["additional_company_info"],
            search_instructions=inp["search_instructions"],
            point_of_contact=inp["point_of_contact"],
        ),
    )
    cases["research_default"] = _calls("report", lambda c: company_research(inp["company_name"], job, c, trace))
    # What perform_company_research actually sends per model: web findings folded into the context, no search, no POC.
    cases["research_flow"] = _calls(
        "report",
        lambda c: company_research(
            inp["company_name"],
            job,
            c,
            trace,
            additional_company_info=inp["research_combined_context"],
            search=False,
            search_instructions=inp["search_instructions"],
        ),
    )

    cases["plan"] = _calls(
        "plan",
        lambda c: generate_letter_plan(
            cv,
            docs,
            report,
            job,
            c,
            trace,
            structure_instructions=inp["structure_instructions"],
            additional_user_info=add,
            hire_problem=hire,
            language_prefix=lang_prefix,
        ),
    )
    cases["plan_defaults"] = _calls("plan", lambda c: generate_letter_plan(cv, [], report, job, c, trace))
    draft_reply = '{"draft_letter": "x", "known_weaknesses": []}'
    cases["draft"] = _calls(
        draft_reply,
        lambda c: generate_letter(
            cv,
            docs,
            report,
            job,
            c,
            trace,
            inp["custom_style_instructions"],
            add,
            letter_plan=inp["letter_plan"],
            hire_problem=hire,
            language_prefix=lang_prefix,
        )
        and None,
    )
    cases["draft_defaults"] = _calls(draft_reply, lambda c: generate_letter(cv, [], "", job, c, trace) and None)
    cases["fancy"] = _calls("fancy", lambda c: fancy_letter(letter, c))

    for suffix, weaknesses in (("", kw), ("_no_kw", None)):
        cases["feedback_instruction" + suffix] = _calls(
            feedback_reply, lambda c, w=weaknesses: instruction_check(letter, c, "", w) and None
        )
        cases["feedback_accuracy" + suffix] = _calls(
            feedback_reply, lambda c, w=weaknesses: accuracy_check(letter, cv, c, add, w) and None
        )
        cases["feedback_precision" + suffix] = _calls(
            feedback_reply, lambda c, w=weaknesses: precision_check(letter, report, job, c, w) and None
        )
        cases["feedback_company_fit" + suffix] = _calls(
            feedback_reply, lambda c, w=weaknesses: company_fit_check(letter, report, job, c, w) and None
        )
        cases["feedback_goal_fit" + suffix] = _calls(
            feedback_reply, lambda c, w=weaknesses: goal_fit_check(letter, report, job, c, hire, w) and None
        )
        cases["feedback_user_fit" + suffix] = _calls(
            feedback_reply, lambda c, w=weaknesses: user_fit_check(letter, docs, c, cv, add, w) and None
        )
        cases["feedback_human" + suffix] = _calls(
            feedback_reply, lambda c, w=weaknesses: human_check(letter, docs, c, w) and None
        )
    cases["feedback_accuracy_plain"] = _calls(
        feedback_reply, lambda c: accuracy_check(letter, "", c, "", None) and None
    )
    cases["feedback_goal_fit_no_hire"] = _calls(
        feedback_reply, lambda c: goal_fit_check(letter, report, job, c, "", None) and None
    )
    cases["feedback_user_fit_no_docs"] = _calls(
        feedback_reply, lambda c: user_fit_check(letter, [], c, cv, "", None) and None
    )
    cases["feedback_human_no_docs"] = _calls(feedback_reply, lambda c: human_check(letter, [], c, None) and None)

    sc = inp["suggest_context"]
    prompts = get_phased_feedback_checker_prompts(
        sc["category"],
        letter=letter,
        style_instructions="",
        cv_text=cv,
        additional_user_info=add,
        company_report=report,
        job_text=job,
        hire_problem=hire,
        top_docs=None,
    )
    assert prompts is not None
    cases["suggest_context"] = _calls(
        '{"items": []}',
        lambda c: run_suggest_additional_feedback_context(
            c, sc["category"], sc["observation"], sc["existing"], prompts[0], prompts[1], top_docs=None
        )
        and None,
    )

    for cat in FEEDBACK_CATEGORY_KEYS:
        ctx = _build_justification_context(
            cat,
            draft_letter=letter,
            style_instructions="",
            cv_text=cv,
            additional_user_info=add,
            company_report=report,
            job_text=job,
            top_docs=docs,
            hire_problem=hire,
            known_weaknesses=kw,
        )
        cases[f"review_context_{cat}"] = {"result": ctx}
    review_items = [tuple(x) for x in inp["review_items"]]
    review_reply = json.dumps({"results": [{"id": i, "keep": True} for i, _ in review_items]})
    accuracy_ctx = cases["review_context_accuracy"]["result"]
    cases["review_stage12"] = _calls(
        review_reply, lambda c: _stage12_batch(c, "accuracy", review_items, accuracy_ctx) and None
    )
    cases["review_stage3"] = _calls('{"groups": []}', lambda c: _stage3_duplicate_groups(c, inp["stage3_items"]) and None)
    cases["review_stage4"] = _calls('{"clusters": []}', lambda c: _stage4_input_clusters(c, inp["stage4_rows"]) and None)

    fb = inp["rewrite_feedback"]
    cases["rewrite"] = _calls(
        "revised",
        lambda c: rewrite_letter(
            letter,
            fb["instruction"],
            fb["accuracy"],
            fb["precision"],
            fb["company_fit"],
            fb["goal_fit"],
            fb["user_fit"],
            fb["human"],
            c,
            trace,
            letter_plan=inp["letter_plan"],
            style_instructions=inp["custom_style_instructions"],
            language_prefix=lang_prefix,
        ),
    )

    cases["decision_rag_state"] = {
        "result": rag_state(job, "Swiss Re", inp["rerank_docs"]["Swiss Re"]["job_text"])
    }
    cases["decision_feedback_state"] = {
        "result": feedback_state(letter, inp["feedback_state_item"], "accuracy")
    }
    cases["decision_questions"] = {
        "result": json.dumps(
            {"rag": RAG_SIMILARITY_QUESTION, "feedback": FEEDBACK_GROUNDED_QUESTION},
            ensure_ascii=False,
            sort_keys=True,
        )
    }
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args()

    inp = json.loads((GOLDEN_DIR / "inputs.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        cases = build_cases(inp, Path(tmp))
    text = json.dumps(cases, ensure_ascii=False, indent=2) + "\n"
    target = GOLDEN_DIR / "expected.json"
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != text:
            old = json.loads(current) if current else {}
            changed = sorted(k for k in set(old) | set(cases) if old.get(k) != cases.get(k))
            print(f"Golden prompts differ in {len(changed)} case(s): {', '.join(changed)}")
            return 1
        print(f"Golden prompts match ({len(cases)} cases).")
        return 0
    target.write_text(text, encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
