"""Local LLM cost estimation from wall-clock time and assumed full-GPU power draw.

Cost = (elapsed_hours) * (gpu_watts / 1000) * price_per_kWh

Both ``LOCAL_GPU_WATTS_AT_100`` and ``LOCAL_ENERGY_PRICE_PER_KWH`` must be set to
positive numbers, or recorded cost stays 0 (see ``compute_local_inference_cost_usd``).
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import logging

logger = logging.getLogger(__name__)


def _parse_positive_float(name: str) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        v = float(raw)
        if v <= 0:
            logger.warning(
                "Invalid %s=%r: must be a positive number; local energy cost will be $0",
                name,
                raw,
            )
            return None
        return v
    except ValueError:
        logger.warning(
            "Invalid %s=%r: not a number; local energy cost will be $0",
            name,
            raw,
        )
        return None


def local_energy_pricing_params() -> Tuple[Optional[float], Optional[float]]:
    """Return (gpu_watts_at_100, energy_price_per_kwh) or None for each if unset/invalid."""
    w = _parse_positive_float("LOCAL_GPU_WATTS_AT_100")
    p = _parse_positive_float("LOCAL_ENERGY_PRICE_PER_KWH")
    return w, p


def is_local_energy_pricing_configured() -> bool:
    """True when both env vars are set to valid positive numbers."""
    w, p = local_energy_pricing_params()
    return w is not None and p is not None


def compute_local_inference_cost_usd(elapsed_seconds: float) -> float:
    """Energy cost in USD (same currency unit as cloud per-token costs), assuming GPU at 100% for the full duration."""
    w, p = local_energy_pricing_params()
    if w is None or p is None:
        return 0.0
    if elapsed_seconds <= 0:
        return 0.0
    kwh = (elapsed_seconds / 3600.0) * (w / 1000.0)
    return kwh * p
