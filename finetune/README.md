# Local fine-tuning (RTX 3090)

Turns your saved letter data into two locally trained models:

1. **Paragraph preference ranker** (reward model). Your accepted letters are
   paragraph-level stitches of the AI drafts, so "which paragraphs did I keep
   vs. discard" is a clean *ranking* signal — it stays meaningful even though
   the kept text was AI-written, because the choice was yours. Used for
   best-of-N paragraph/draft selection.
2. **Editor model** (QLoRA SFT). Learns the transformation
   *(job context + drafts) → the letter you actually sent*, i.e. your stitching
   and editing style. Trained on the ~100 (drafts → final) pairs plus the
   per-draft edit records from `feedbacks`.

## Setup

Use a dedicated venv (training deps are heavy and must not pollute the app env):

```powershell
python -m venv finetune\.venv
finetune\.venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r finetune\requirements.txt
```

**CUDA / bitsandbytes:** if torch is `cu132` but bitsandbytes only ships up to
`cuda130`, you will see a scary traceback on import. Ranker training (bf16 only)
still worked, but **editor 4-bit will fail** until versions align. The finetune
scripts auto-set `BNB_CUDA_VERSION=130` when needed; or install torch `cu124`
per the comment in `requirements.txt`.

## 1. Build datasets

From the on-disk Datastore export (no credentials needed):

```powershell
python -m finetune.build_dataset --source backup --backup-dir data_backup
```

Or from the live Firestore, cached locally under `finetune/cache/` (uses the
same env vars as the app: `GOOGLE_APPLICATION_CREDENTIALS`,
`GOOGLE_CLOUD_PROJECT`, `FIRESTORE_DATABASE`, `FIRESTORE_COLLECTION`; needs
`google-cloud-firestore` installed):

```powershell
python -m finetune.build_dataset --source cloud            # uses cache if present
python -m finetune.build_dataset --source cloud --refresh  # refetch from Firestore
```

Outputs in `finetune/datasets/`:

- `ranker_{train,val}.jsonl` — `prompt`, `chosen`, `rejected` (compact job summary +
  paragraph; scrape chrome stripped so chosen/rejected differ mainly at the tail)
- `editor_{train,val}.jsonl` — `prompt`, `completion`

The split is by document (stable hash, ~10% validation) so no letter leaks
between train and val.

## 2. Train the ranker (start here)

Rebuild datasets after changing `finetune/job_text.py` or pair logic in
`build_dataset.py`.

```powershell
python -m finetune.train_ranker
```

Defaults: `Qwen/Qwen2.5-1.5B-Instruct`, LoRA r=16, 3 epochs, bf16, 1024-token
context — minutes on a 3090. Then check it actually predicts your taste:

```powershell
python -m finetune.score --adapter finetune/runs/ranker --eval
python -m finetune.score --adapter finetune/runs/ranker --rank-drafts --source backup --verbose
```

`--eval` reports pairwise accuracy on held-out documents (random = 0.5; below
~0.65 the signal is too weak to deploy). `--rank-drafts` checks whether ranking
whole drafts by mean paragraph score recovers the draft you actually built
your letter from.

## 3. Train the editor (optional second step)

```powershell
python -m finetune.train_editor
```

Defaults: `Qwen/Qwen2.5-7B-Instruct` with a 4-bit base + LoRA (QLoRA), 8k
context so several drafts fit in the prompt, batch 1 × grad-accum 8. With only
~100 documents this is deliberately modest — judge it by reading its outputs on
validation documents, not just eval loss.

## Data flow

```
data_backup export ─┐
                    ├─ data_sources.load_data() ─ build_dataset.py ─ datasets/*.jsonl
Firestore ─ cache/ ─┘                                   │
                                        train_ranker.py / train_editor.py
                                                        │
                                              runs/{ranker,editor}/ (LoRA adapters)
```

`cache/`, `datasets/`, and `runs/` are local artifacts (gitignored).
