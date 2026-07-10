"""Train the editor model (drafts -> the letter the user actually sends) with QLoRA.

Learns the user's edit style: stitching the best material from several drafts,
removing list-like company recitations and trite wording, matching their voice.
Defaults are sized for a 24GB RTX 3090 (7B model, 4-bit base, LoRA adapters,
8k context to fit several drafts in the prompt).

Usage:
    python -m finetune.train_editor [--model Qwen/Qwen2.5-7B-Instruct] \
        [--dataset-dir finetune/datasets] [--out finetune/runs/editor]
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_FINETUNE_PACKAGES = ("datasets", "torch", "peft", "transformers", "trl", "bitsandbytes")


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
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--dataset-dir", default=str(Path(__file__).parent / "datasets"))
    parser.add_argument("--out", default=str(Path(__file__).parent / "runs" / "editor"))
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--max-seq-len", type=int, default=8192)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--no-4bit", action="store_true",
                        help="load the base model in bf16 instead of 4-bit (small models only)")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    from finetune.cuda_compat import patch_bitsandbytes_cuda
    patch_bitsandbytes_cuda()
    _require_packages()

    # datasets before torch: on Windows, torch-then-datasets can segfault (no Python traceback).
    from datasets import load_dataset
    import torch
    from peft import LoraConfig, TaskType
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    dataset_dir = Path(args.dataset_dir)
    data_files = {
        "train": str(dataset_dir / "editor_train.jsonl"),
        "validation": str(dataset_dir / "editor_val.jsonl"),
    }
    dataset = load_dataset("json", data_files=data_files)
    # SFTTrainer treats a dataset with prompt/completion columns as
    # prompt-completion pairs (loss on the completion only).
    keep = {"prompt", "completion"}
    dataset = dataset.remove_columns(
        [c for c in dataset["train"].column_names if c not in keep]
    )
    print(f"train pairs: {len(dataset['train'])}, val pairs: {len(dataset['validation'])}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs: dict = {"torch_dtype": torch.bfloat16}
    if not args.no_4bit:
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)

    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_r,
        lora_alpha=2 * args.lora_r,
        lora_dropout=0.05,
        target_modules="all-linear",
    )

    config = SFTConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        gradient_checkpointing=True,
        bf16=True,
        max_seq_length=args.max_seq_len,
        packing=False,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        report_to="none",
        seed=args.seed,
    )

    trainer = SFTTrainer(
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
