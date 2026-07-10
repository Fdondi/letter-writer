"""Build fine-tuning datasets from letter data.

Two datasets are produced (JSONL, train/val split at document level):

1. **Ranker preference pairs** (``ranker_{train,val}.jsonl``): the user's accepted
   letter is a paragraph-level stitch of the AI drafts, so every draft paragraph
   the user kept (near-verbatim in the final letter) is a *chosen* sample and
   every draft paragraph the user discarded is a *rejected* sample, in the
   context of that job. Fields: ``prompt``, ``chosen``, ``rejected`` (prompt is
   already prepended to both texts, ready for TRL's RewardTrainer).

2. **Editor pairs** (``editor_{train,val}.jsonl``): ``prompt`` (job context plus
   the AI drafts) -> ``completion`` (the letter the user actually sent). Also
   includes per-draft edit records from the feedbacks collection
   (original -> final where the user edited a single draft).

Usage:
    python -m finetune.build_dataset --source backup --backup-dir data_backup
    python -m finetune.build_dataset --source cloud [--refresh] [--user-id ...]
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .data_sources import load_data
from .job_text import EDITOR_JOB_EXCERPT_CHARS, RANKER_JOB_EXCERPT_CHARS, clean_job_excerpt

logger = logging.getLogger(__name__)

CHOSEN_MIN_SIMILARITY = 0.75
REJECTED_MAX_SIMILARITY = 0.45
MIN_PARAGRAPH_CHARS = 60
MAX_NEGATIVES_PER_CHOSEN = 4
VAL_FRACTION_BUCKETS = 10  # 1 bucket of 10 -> ~10% validation
DRAFT_CAP_CHARS = 4500
MAX_DRAFTS_IN_EDITOR_PROMPT = 6

# Vendors whose "drafts" are not AI candidates (user's own manual entries).
_NON_AI_VENDORS = {"manual"}


def split_paragraphs(text: str) -> List[str]:
    parts = re.split(r"\n\s*\n", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= MIN_PARAGRAPH_CHARS]


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _context_prompt(doc: Dict[str, Any]) -> str:
    """Compact prefix so paragraph differences dominate the token budget."""
    job_excerpt = clean_job_excerpt(
        doc.get("job_text") or "",
        max_chars=RANKER_JOB_EXCERPT_CHARS,
    )
    return (
        f"Company: {doc.get('company_name') or 'unknown'}\n"
        f"Role: {doc.get('role') or 'unknown'}\n"
        f"Language: {doc.get('language') or 'unspecified'}\n"
        f"Job summary:\n{job_excerpt}\n\n"
        f"Paragraph to rate:\n"
    )


def _is_val_doc(doc_id: str) -> bool:
    digest = hashlib.md5(doc_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % VAL_FRACTION_BUCKETS == 0


# ---------------------------------------------------------------------------
# Ranker pairs
# ---------------------------------------------------------------------------

def _classify_draft_paragraphs(
    doc: Dict[str, Any],
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Return (chosen, rejected) lists of (vendor, paragraph) for one document.

    chosen: draft paragraphs the user kept near-verbatim in the final letter.
    rejected: draft paragraphs not resembling anything in the final letter.
    Paragraphs in the ambiguous middle band are dropped.
    """
    final_paras = split_paragraphs(doc.get("letter_text") or "")
    if not final_paras:
        return [], []
    chosen: List[Tuple[str, str]] = []
    rejected: List[Tuple[str, str]] = []
    for letter in doc.get("ai_letters") or []:
        vendor = letter.get("vendor") or "unknown"
        if vendor in _NON_AI_VENDORS:
            continue
        for para in split_paragraphs(letter.get("text") or ""):
            best = max((_similarity(para, fp) for fp in final_paras), default=0.0)
            if best >= CHOSEN_MIN_SIMILARITY:
                chosen.append((vendor, para))
            elif best <= REJECTED_MAX_SIMILARITY:
                rejected.append((vendor, para))
    return chosen, rejected


def build_ranker_pairs(
    documents: Iterable[Dict[str, Any]],
    rng: random.Random,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    train: List[Dict[str, Any]] = []
    val: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for doc in documents:
        chosen, rejected = _classify_draft_paragraphs(doc)
        if not chosen or not rejected:
            continue
        prompt = _context_prompt(doc)
        bucket = val if _is_val_doc(doc["doc_id"]) else train
        for c_vendor, c_para in chosen:
            negatives = rng.sample(rejected, min(MAX_NEGATIVES_PER_CHOSEN, len(rejected)))
            for r_vendor, r_para in negatives:
                dedupe_key = (c_para[:200], r_para[:200])
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                bucket.append({
                    "prompt": prompt,
                    "chosen": prompt + c_para,
                    "rejected": prompt + r_para,
                    "doc_id": doc["doc_id"],
                    "company_name": doc.get("company_name") or "",
                    "chosen_vendor": c_vendor,
                    "rejected_vendor": r_vendor,
                })
    return train, val


# ---------------------------------------------------------------------------
# Editor pairs
# ---------------------------------------------------------------------------

_EDITOR_SYSTEM = (
    "You are the applicant's personal cover letter editor. Given the job context "
    "and one or more AI-written draft letters, produce the final cover letter the "
    "applicant would send: keep the strongest material, remove list-like company "
    "recitations, banned/trite wording and non-keyboard characters, and match the "
    "applicant's own voice."
)


def _editor_prompt_from_doc(doc: Dict[str, Any]) -> str:
    drafts = [
        letter for letter in (doc.get("ai_letters") or [])
        if letter.get("vendor") not in _NON_AI_VENDORS and (letter.get("text") or "").strip()
    ][:MAX_DRAFTS_IN_EDITOR_PROMPT]
    draft_blocks = "\n\n".join(
        f"---- Draft {i + 1} ({letter.get('vendor')}) ----\n{letter['text'][:DRAFT_CAP_CHARS]}"
        for i, letter in enumerate(drafts)
    )
    return (
        f"{_EDITOR_SYSTEM}\n\n"
        f"Company: {doc.get('company_name') or 'unknown'}\n"
        f"Role: {doc.get('role') or 'unknown'}\n"
        f"Language: {doc.get('language') or 'unspecified'}\n"
        f"Job posting (excerpt):\n"
        f"{clean_job_excerpt(doc.get('job_text') or '', max_chars=EDITOR_JOB_EXCERPT_CHARS)}\n\n"
        f"{draft_blocks}\n\n"
        f"Write the final cover letter:\n"
    )


def _editor_prompt_from_feedback(fb: Dict[str, Any]) -> str:
    return (
        f"{_EDITOR_SYSTEM}\n\n"
        f"---- Draft ({fb.get('vendor') or 'unknown'}) ----\n"
        f"{(fb.get('original_text') or '')[:DRAFT_CAP_CHARS]}\n\n"
        f"Write the final cover letter:\n"
    )


def build_editor_pairs(
    documents: Iterable[Dict[str, Any]],
    feedbacks: Iterable[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    train: List[Dict[str, Any]] = []
    val: List[Dict[str, Any]] = []
    for doc in documents:
        final = (doc.get("letter_text") or "").strip()
        drafts = [
            letter for letter in (doc.get("ai_letters") or [])
            if letter.get("vendor") not in _NON_AI_VENDORS
        ]
        if not final or not drafts:
            continue
        bucket = val if _is_val_doc(doc["doc_id"]) else train
        bucket.append({
            "prompt": _editor_prompt_from_doc(doc),
            "completion": final,
            "doc_id": doc["doc_id"],
            "source": "document",
        })
    for fb in feedbacks:
        if fb.get("action") != "edited":
            continue
        original = (fb.get("original_text") or "").strip()
        final = (fb.get("final_text") or "").strip()
        if not original or not final or original == final:
            continue
        doc_id = fb.get("document_id") or fb.get("feedback_id") or ""
        bucket = val if _is_val_doc(doc_id) else train
        bucket.append({
            "prompt": _editor_prompt_from_feedback(fb),
            "completion": final,
            "doc_id": doc_id,
            "source": "feedback_edit",
        })
    return train, val


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info("wrote %d rows -> %s", len(rows), path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["backup", "cloud"], default="backup")
    parser.add_argument("--backup-dir", default="data_backup", help="Datastore export directory (source=backup)")
    parser.add_argument("--cache-dir", default=None, help="local cache dir for cloud reads")
    parser.add_argument("--refresh", action="store_true", help="refetch from Firestore even if cached")
    parser.add_argument("--user-id", default=None, help="restrict cloud reads to one user")
    parser.add_argument("--out", default=str(Path(__file__).parent / "datasets"))
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    kwargs: Dict[str, Any] = {"backup_dir": args.backup_dir, "refresh": args.refresh,
                              "user_id": args.user_id}
    if args.cache_dir:
        kwargs["cache_dir"] = args.cache_dir
    data = load_data(args.source, **kwargs)
    documents, feedbacks = data["documents"], data["feedbacks"]
    logger.info("loaded %d documents, %d feedbacks", len(documents), len(feedbacks))

    rng = random.Random(args.seed)
    ranker_train, ranker_val = build_ranker_pairs(documents, rng)
    editor_train, editor_val = build_editor_pairs(documents, feedbacks)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "ranker_train.jsonl", ranker_train)
    _write_jsonl(out_dir / "ranker_val.jsonl", ranker_val)
    _write_jsonl(out_dir / "editor_train.jsonl", editor_train)
    _write_jsonl(out_dir / "editor_val.jsonl", editor_val)

    n_docs_with_pairs = len({r["doc_id"] for r in ranker_train + ranker_val})
    if ranker_train:
        prompt_lens = [len(r["prompt"]) for r in ranker_train[:200]]
        para_lens = [len(r["chosen"]) - len(r["prompt"]) for r in ranker_train[:200]]
        avg_prompt = sum(prompt_lens) / len(prompt_lens)
        avg_para = sum(para_lens) / len(para_lens)
        print(f"ranker prompt ~{avg_prompt:.0f} chars, paragraph ~{avg_para:.0f} chars (sample)")
    print()
    print(f"ranker pairs:  {len(ranker_train)} train / {len(ranker_val)} val "
          f"(from {n_docs_with_pairs} documents)")
    print(f"editor pairs:  {len(editor_train)} train / {len(editor_val)} val")


if __name__ == "__main__":
    main()
