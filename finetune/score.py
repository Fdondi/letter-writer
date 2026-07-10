"""Score paragraphs and letters with a trained ranker adapter.

Modes:
  --eval          pairwise accuracy on ranker_val.jsonl (does the model prefer
                  the paragraph the user kept over the one they discarded?)
  --rank-drafts   for each document, rank its AI drafts by mean paragraph score
                  and report where the draft most similar to the accepted
                  letter lands (sanity check that the ranker is useful).

Usage:
    python -m finetune.score --adapter finetune/runs/ranker --eval
    python -m finetune.score --adapter finetune/runs/ranker --rank-drafts --source backup
"""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
from typing import Any, Dict, List


class ParagraphScorer:
    """Loads the trained reward model once and scores (context, paragraph) texts."""

    def __init__(self, adapter_dir: str, max_len: int = 1024, batch_size: int = 16):
        import torch
        from peft import AutoPeftModelForSequenceClassification
        from transformers import AutoTokenizer

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(adapter_dir)
        self.model = AutoPeftModelForSequenceClassification.from_pretrained(
            adapter_dir, num_labels=1, dtype=torch.bfloat16
        ).to(self.device)
        self.model.eval()
        if self.model.config.pad_token_id is None:
            self.model.config.pad_token_id = self.tokenizer.pad_token_id
        self.max_len = max_len
        self.batch_size = batch_size

    def score(self, texts: List[str]) -> List[float]:
        scores: List[float] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            enc = self.tokenizer(
                batch, truncation=True, max_length=self.max_len,
                padding=True, return_tensors="pt",
            ).to(self.device)
            with self.torch.no_grad():
                logits = self.model(**enc).logits.squeeze(-1)
            scores.extend(logits.float().cpu().tolist())
        return scores


def run_eval(scorer: ParagraphScorer, dataset_dir: Path) -> None:
    rows = [
        json.loads(line)
        for line in (dataset_dir / "ranker_val.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        print("ranker_val.jsonl is empty")
        return
    chosen_scores = scorer.score([r["chosen"] for r in rows])
    rejected_scores = scorer.score([r["rejected"] for r in rows])
    correct = sum(1 for c, r in zip(chosen_scores, rejected_scores) if c > r)
    ties = sum(1 for c, r in zip(chosen_scores, rejected_scores) if c == r)
    print(f"pairwise accuracy: {correct}/{len(rows)} = {correct / len(rows):.3f}")
    if ties:
        print(f"ties (counted wrong): {ties}")


def run_rank_drafts(scorer: ParagraphScorer, args: argparse.Namespace) -> None:
    from .build_dataset import _context_prompt, split_paragraphs
    from .data_sources import load_data

    data = load_data(args.source, backup_dir=args.backup_dir, refresh=False,
                     user_id=args.user_id)
    ranks: List[int] = []
    n_docs = 0
    for doc in data["documents"]:
        final = (doc.get("letter_text") or "").strip()
        drafts = [
            letter for letter in (doc.get("ai_letters") or [])
            if letter.get("vendor") != "manual" and (letter.get("text") or "").strip()
        ]
        if not final or len(drafts) < 2:
            continue
        prompt = _context_prompt(doc)
        mean_scores: List[float] = []
        for letter in drafts:
            paras = split_paragraphs(letter["text"])
            if not paras:
                mean_scores.append(float("-inf"))
                continue
            scores = scorer.score([prompt + p for p in paras])
            mean_scores.append(sum(scores) / len(scores))
        similarities = [
            difflib.SequenceMatcher(None, letter["text"], final).ratio() for letter in drafts
        ]
        target = max(range(len(drafts)), key=lambda i: similarities[i])
        order = sorted(range(len(drafts)), key=lambda i: mean_scores[i], reverse=True)
        rank_of_target = order.index(target) + 1
        ranks.append(rank_of_target)
        n_docs += 1
        if args.verbose:
            named = ", ".join(
                f"{drafts[i].get('vendor')}={mean_scores[i]:.2f}" for i in order
            )
            print(f"{doc.get('company_name', ''):30.30s} target-rank {rank_of_target}/{len(drafts)}  [{named}]")
    if not ranks:
        print("no documents with >=2 drafts found")
        return
    top1 = sum(1 for r in ranks if r == 1)
    print(f"documents: {n_docs}; ranker puts the user's preferred draft first "
          f"{top1}/{n_docs} = {top1 / n_docs:.3f} (mean rank {sum(ranks) / len(ranks):.2f})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, help="trained ranker directory")
    parser.add_argument("--dataset-dir", default=str(Path(__file__).parent / "datasets"))
    parser.add_argument("--eval", action="store_true")
    parser.add_argument("--rank-drafts", action="store_true")
    parser.add_argument("--source", choices=["backup", "cloud"], default="backup")
    parser.add_argument("--backup-dir", default="data_backup")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--max-len", type=int, default=1024)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.eval and not args.rank_drafts:
        parser.error("pass --eval and/or --rank-drafts")

    from finetune.cuda_compat import patch_bitsandbytes_cuda
    patch_bitsandbytes_cuda()

    scorer = ParagraphScorer(args.adapter, max_len=args.max_len)
    if args.eval:
        run_eval(scorer, Path(args.dataset_dir))
    if args.rank_drafts:
        run_rank_drafts(scorer, args)


if __name__ == "__main__":
    main()
