"""Pick a local device for Laya on Windows and Linux.

NVIDIA CUDA and AMD ROCm both show up as ``torch.cuda``. Windows AMD and Intel
GPUs, including a Ryzen 7 7735HS Radeon iGPU, are used through DirectML when
``torch-directml`` is installed. Linux has no PyTorch backend for that iGPU, so
the CPU path is the supported one there. ``LAYA_DEVICE`` may be ``auto``,
``cpu``, ``cuda``, or ``directml``.
"""

from __future__ import annotations

import os

# Optional. Importing torch/DirectML at startup would load GPU libraries in every
# server process, including ones that never score with Laya.
try:
    import torch
except (ImportError, OSError):
    torch = None  # type: ignore[assignment]

try:
    import torch_directml
except (ImportError, OSError):
    torch_directml = None  # type: ignore[assignment]


def choose_laya_device(
    requested: str | None,
    *,
    cuda_available: bool,
    cuda_name: str = "",
    directml_available: bool,
    directml_name: str = "",
) -> tuple[str, str]:
    """Return ``(kind, detail)`` where kind is ``cpu``, ``cuda``, or ``directml``.

    A requested accelerator that is not actually present resolves to CPU and the
    detail says why. Callers must surface that detail; the score is still computed.
    """
    req = (requested or "auto").strip().lower() or "auto"
    if req not in ("auto", "cpu", "cuda", "directml"):
        raise ValueError(
            f"LAYA_DEVICE must be auto, cpu, cuda, or directml; got {requested!r}"
        )
    if req == "cpu":
        return "cpu", "LAYA_DEVICE=cpu"
    if req == "cuda":
        if cuda_available:
            return "cuda", cuda_name or "CUDA/ROCm"
        return "cpu", "LAYA_DEVICE=cuda but no CUDA/ROCm device is available; using CPU"
    if req == "directml":
        if directml_available:
            return "directml", directml_name or "DirectML"
        return (
            "cpu",
            "LAYA_DEVICE=directml but torch-directml has no device; using CPU",
        )
    if cuda_available:
        return "cuda", cuda_name or "CUDA/ROCm"
    if directml_available:
        return "directml", directml_name or "DirectML"
    return (
        "cpu",
        "No CUDA, ROCm, or DirectML device. Using the CPU. "
        "NVIDIA and AMD ROCm need a matching PyTorch build. "
        "Windows AMD or Intel GPUs need torch-directml. "
        "AMD integrated graphics such as the Ryzen 7 7735HS Radeon use DirectML on Windows and the CPU on Linux.",
    )


def probe_cuda() -> tuple[bool, str]:
    if torch is None or not torch.cuda.is_available():
        return False, ""
    try:
        name = str(torch.cuda.get_device_name(0))
    except Exception:
        name = "cuda:0"
    return True, name


def probe_directml() -> tuple[bool, str]:
    if torch_directml is None:
        return False, ""
    try:
        count = int(torch_directml.device_count())
    except Exception:
        return False, ""
    if count <= 0:
        return False, ""
    name = "directml:0"
    device_name = getattr(torch_directml, "device_name", None)
    if callable(device_name):
        try:
            name = str(device_name(0))
        except Exception:
            name = "directml:0"
    return True, name


def resolve_laya_device() -> tuple[str, str]:
    """Resolve ``LAYA_DEVICE`` against the machine this process is running on."""
    cuda_ok, cuda_name = probe_cuda()
    dml_ok, dml_name = probe_directml()
    return choose_laya_device(
        os.environ.get("LAYA_DEVICE"),
        cuda_available=cuda_ok,
        cuda_name=cuda_name,
        directml_available=dml_ok,
        directml_name=dml_name,
    )
