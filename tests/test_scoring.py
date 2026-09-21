"""Locks the CLAUDE.md scoring invariants in the package they now live in.

P3.1 moved this logic out of app.py with responses byte-identical; these guard
the invariants themselves, which P3.2 onward will be editing around.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scoring  # noqa: E402


def test_unavailable_channel_is_not_a_zero():
    """A channel with no corpus reports unavailable. Collapsing it to 0 would
    feed the fusion evidence of absence where there is only absent evidence."""
    assert scoring.strength(0.0, available=False) == "unavailable"
    assert scoring.strength(0.0) == "none"
    contradiction = next(c for c in scoring.CHANNEL_META if c["key"] == "contradiction")
    assert contradiction["available"] is False


def test_probe_tokens_are_rare_and_stable():
    idf = {
        "COMMON": {"df": 900, "share": 0.9, "idf": 0.1},     # too common
        "MISSING": {"df": 0, "share": 0.0, "idf": 9.9},      # matches nothing
        "RARE": {"df": 5, "share": 0.005, "idf": 5.0},
        "RARER": {"df": 2, "share": 0.002, "idf": 6.0},
    }
    assert scoring.pick_probes(idf) == ["RARER", "RARE"]
    assert scoring.pick_probes({}) == []


def test_probe_ties_break_deterministically():
    tie = {t: {"df": 3, "share": 0.003, "idf": 4.0} for t in ("BETA", "ALPHA", "GAMMA")}
    assert scoring.pick_probes(tie) == sorted(tie)[: scoring.ACTOR_PROBES]


def test_stop_actors_carry_no_signal():
    assert scoring.actor_tokens("POLICE, GOVERNMENT") == set()
    assert scoring.actor_tokens("SAMYUKTA KISAN MORCHA") == {"SAMYUKTA", "KISAN", "MORCHA"}
    assert scoring.actor_tokens(None, "") == set()


def test_fusion_is_the_weighted_sum_through_a_logistic():
    channels = {k: 0.0 for k in scoring.CAUSAL_W}
    z, confidence = scoring.fuse(channels)
    assert z == scoring.CAUSAL_INTERCEPT
    assert confidence == scoring.logistic(scoring.CAUSAL_INTERCEPT)

    channels["documented"] = 1.0
    z2, conf2 = scoring.fuse(channels)
    assert z2 == scoring.CAUSAL_INTERCEPT + scoring.CAUSAL_W["documented"]
    assert conf2 > confidence


def test_contradiction_is_the_only_negative_weight():
    negative = [k for k, w in scoring.CAUSAL_W.items() if w < 0]
    assert negative == ["contradiction"]


def test_logistic_saturates_without_overflowing():
    assert scoring.logistic(-1000) == 0.0
    assert scoring.logistic(1000) == 1.0


def test_grades_follow_the_documented_rules():
    g, _ = scoring.grade(1.0, 0.9, 0, 0, 0, 0.0, 0.9, 12)
    assert g == "confirmed"
    g, _ = scoring.grade(1.0, 0.2, 0, 0, 0, 0.0, 0.9, 2)
    assert g == "reported"
    g, _ = scoring.grade(0.0, 0.2, 0.6, 0.6, 0.6, 0.5, 0.5, 2)
    assert g == "pattern"
    g, _ = scoring.grade(0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0)
    assert g == "dropped"
