"""Match bitsandbytes CUDA DLLs to the installed PyTorch build when they differ."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def patch_bitsandbytes_cuda() -> str | None:
    """Set BNB_CUDA_VERSION before bitsandbytes is imported, if the exact DLL is missing.

    torch 2.12+cu132 ships before bitsandbytes has libbitsandbytes_cuda132.dll.
    Without this, ranker/score spam tracebacks and editor 4-bit loading fails hard.
    Returns the override version string when set, else None.
    """
    if os.environ.get("BNB_CUDA_VERSION"):
        return os.environ["BNB_CUDA_VERSION"]

    if importlib.util.find_spec("torch") is None or importlib.util.find_spec("bitsandbytes") is None:
        return None

    spec = importlib.util.find_spec("bitsandbytes")
    if not spec or not spec.origin:
        return None
    pkg_dir = Path(spec.origin).parent

    import torch

    if not torch.cuda.is_available():
        return None

    cuda = (torch.version.cuda or "").strip()
    if not cuda:
        return None

    tag = cuda.replace(".", "")
    exact = pkg_dir / f"libbitsandbytes_cuda{tag}.dll"
    if exact.exists():
        return None

    candidates = sorted(
        (p.stem.replace("libbitsandbytes_cuda", "") for p in pkg_dir.glob("libbitsandbytes_cuda*.dll")),
        key=lambda v: int(v) if v.isdigit() else -1,
        reverse=True,
    )
    if not candidates:
        return None

    # Prefer the newest prebuilt DLL that is <= torch's CUDA tag (e.g. 130 for torch 13.2).
    chosen = next((v for v in candidates if v.isdigit() and int(v) <= int(tag)), candidates[0])
    os.environ["BNB_CUDA_VERSION"] = chosen
    print(
        f"bitsandbytes: no cuda{tag} DLL; using BNB_CUDA_VERSION={chosen} "
        f"(torch CUDA {cuda}). Set BNB_CUDA_VERSION yourself to override."
    )
    return chosen
