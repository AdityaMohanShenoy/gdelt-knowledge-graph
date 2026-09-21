"""Channel fusion: weighted sum through a logistic, plus the term breakdown
that lets a reader re-derive the number by hand."""

import math

from .config import CAUSAL_INTERCEPT, CAUSAL_W


def logistic(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def fuse(channels: dict[str, float]) -> tuple[float, float]:
    """Returns (z, confidence)."""
    z = CAUSAL_INTERCEPT + sum(CAUSAL_W[k] * channels[k] for k in CAUSAL_W)
    return z, logistic(z)


def terms(channels: dict[str, float], questions: dict[str, str]) -> list[dict]:
    return [
        {"key": k, "question": questions[k], "score": channels[k], "weight": CAUSAL_W[k],
         "contribution": round(CAUSAL_W[k] * channels[k], 3)}
        for k in CAUSAL_W
    ]
