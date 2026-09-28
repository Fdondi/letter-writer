# Local Laya

[Laya](https://huggingface.co/convaiinnovations/laya) scores two things inside the letter-writer process:

- how similar each retrieved job is to the target job (the 1–10 score used to order RAG hits)
- whether a feedback comment is grounded in the letter, or a hallucination

The language model still writes similarity bullets and the comments themselves. Laya does not generate text. When it marks a comment invalid, that comment leaves the open critique list and appears under the “already good” notes, with **Restore**.

Laya runs in the Python process that serves the API. It is not the LM Studio server used by the local chat vendor. Install it in that same environment. The first call downloads the checkpoint from Hugging Face (about 800 MB for the English weights, and the multilingual subfolder when the text is not English).

If `laya` is not installed, RAG keeps the language-model score and feedback comments stay visible. The UI says that Laya did not score them.

## Device choice

`LAYA_DEVICE` is `auto` unless you set it to `cpu`, `cuda`, or `directml`.

| Machine | What `auto` uses |
|---|---|
| NVIDIA GPU, Windows or Linux | CUDA, when PyTorch is a CUDA build |
| AMD GPU with a ROCm PyTorch build, Linux | CUDA (ROCm reports itself as `torch.cuda`) |
| AMD or Intel GPU, Windows, with `torch-directml` | DirectML. This includes a Ryzen 7 7735HS with Radeon Graphics |
| Intel CPU, or any machine without those backends | CPU |
| Ryzen 7 7735HS on Linux | CPU. PyTorch has no backend for that Radeon iGPU on Linux |

Check the choice without downloading weights:

```bash
python scripts/laya_device_check.py
```

## Install

Install a PyTorch build first, then `laya`. Use one line per command.

Linux or Windows, CPU only (Intel and the Linux path for a 7735HS):

```bash
pip install torch
pip install "laya>=0.3.5"
```

Linux or Windows, NVIDIA:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install "laya>=0.3.5"
```

Linux, AMD GPU with ROCm (discrete GPUs that ROCm supports; not the 7735HS iGPU):

```bash
pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
pip install "laya>=0.3.5"
```

Windows, AMD or Intel GPU via DirectML (including Ryzen 7 7735HS Radeon Graphics):

```bash
pip install torch-directml
pip install "laya>=0.3.5"
```

`torch-directml` pulls a DirectML-compatible PyTorch. Do not mix it with a CUDA wheel in the same environment.

Optional settings:

- `LAYA_MODEL` — `english`, `multilingual`, or `typed-decisions`. Unset, the router picks English or multilingual from the text.
- `LAYA_FEEDBACK_VALID_MIN` — grounded probability at or above this stays a critique (default `0.40`).
- `LAYA_FEEDBACK_INVALID_MIN_CONFIDENCE` — a low grounded probability is hidden only when confidence is at least this (default `0.55`). Uncertain comments stay in the open list.

Set `USE_TF=0` if `laya` hangs while TensorFlow is installed. The scorer sets that default itself.
