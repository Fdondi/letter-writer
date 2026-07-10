"""Train the paragraph preference ranker (reward model) with LoRA.

Learns from (chosen, rejected) paragraph pairs which candidate paragraphs the
user keeps for a given job context. Fits comfortably on a 24GB RTX 3090 with
the default 1.5B model (a 3B model also fits; lower the batch size).

Usage:
    python -m finetune.train_ranker [--model Qwen/Qwen2.5-1.5B-Instruct] \
        [--dataset-dir finetune/datasets] [--out finetune/runs/ranker]
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_FINETUNE_PACKAGES = ("datasets", "torch", "peft", "transformers", "trl")


def _require_packages() -> None:
    missing = [name for name in _FINETUNE_PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        print(
            "Missing training packages: "
            + ", ".join(missing)
            + "\nInstall: pip install -r finetune/requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--dataset-dir", default=str(Path(__file__).parent / "datasets"))
    parser.add_argument("--out", default=str(Path(__file__).parent / "runs" / "ranker"))
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--max-len", type=int, default=1024)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    from finetune.cuda_compat import patch_bitsandbytes_cuda
    patch_bitsandbytes_cuda()
    _require_packages()

    # datasets before torch: on Windows, torch-then-datasets can segfault (no Python traceback).
    from datasets import load_dataset
    import torch
    from peft import LoraConfig, TaskType
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer
    from trl import RewardConfig, RewardTrainer

    class QuietRewardTrainer(RewardTrainer):
        """Skip TRL's huge chosen/rejected Rich table at each eval epoch."""

        def evaluate(self, *args, **kwargs):
            kwargs.pop("num_print_samples", None)
            return Trainer.evaluate(self, *args, **kwargs)

    dataset_dir = Path(args.dataset_dir)
    data_files = {
        "train": str(dataset_dir / "ranker_train.jsonl"),
        "validation": str(dataset_dir / "ranker_val.jsonl"),
    }
    dataset = load_dataset("json", data_files=data_files)
    # RewardTrainer needs only chosen/rejected text columns.
    keep = {"chosen", "rejected"}
    dataset = dataset.remove_columns(
        [c for c in dataset["train"].column_names if c not in keep]
    )
    print(f"train pairs: {len(dataset['train'])}, val pairs: {len(dataset['validation'])}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        num_labels=1,
        dtype=torch.bfloat16,
    )
    model.config.pad_token_id = tokenizer.pad_token_id

    peft_config = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=args.lora_r,
        lora_alpha=2 * args.lora_r,
        lora_dropout=0.05,
        target_modules="all-linear",
        modules_to_save=["score"],
    )

    config = RewardConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        bf16=True,
        max_length=args.max_len,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_accuracy",
        greater_is_better=True,
        report_to="none",
        seed=args.seed,
    )

    trainer = QuietRewardTrainer(
        model=model,
        args=config,
        processing_class=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        peft_config=peft_config,
    )
    trainer.train()
    metrics = trainer.evaluate()
    print("final eval:", metrics)

    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"adapter saved to {args.out}")


if __name__ == "__main__":
    main()
