"""Causal Evidence scoring, lifted out of app.py by BUILD_PLAN P3.1.

The invariants this package must preserve are documented in CLAUDE.md: spike
days rather than raw presence, `available: false` never collapsed to 0,
IDF-weighted actor tokens, and one candidate per event type.
"""

from . import channels
from .config import (
    ACTOR_MAX_SHARE, ACTOR_PROBES, CAUSAL_FLOOR, CAUSAL_INTERCEPT,
    CAUSAL_W, CAUSAL_WINDOW_DAYS, CHANNEL_META, MIN_GROUP_EVENTS,
    ROOT_LABEL, STOP_ACTORS,
)
from .fuse import fuse, logistic, terms
from .grade import grade, strength
from .retrieval import actor_tokens, matrix_index, matrix_rows, pick_probes, token_idf

__all__ = [
    "channels", "fuse", "logistic", "terms", "grade", "strength",
    "actor_tokens", "matrix_index", "matrix_rows", "pick_probes", "token_idf",
    "ACTOR_MAX_SHARE", "ACTOR_PROBES", "CAUSAL_FLOOR", "CAUSAL_INTERCEPT",
    "CAUSAL_W", "CAUSAL_WINDOW_DAYS", "CHANNEL_META", "MIN_GROUP_EVENTS",
    "ROOT_LABEL", "STOP_ACTORS",
]
