import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from causal_annotation import agreement, double_sample, edge, kappa  # noqa: E402

CLAIM = {"claim_id": "cl:1", "cause_event_id": "ce:arrest", "cause_kind": "event",
         "effect_event_id": "ce:fast", "lag_days": 13}
TEXTS = {"a1": "AAP leaders sat on a fast against the arrest of Kejriwal.",
         "a2": "Kejriwal was arrested by the ED on March 21."}
OUTLET = {"a1": "thehindu.com", "a2": "ndtv.com"}.get
ACCEPT = {"decision": "accept", "relation": "TRIGGERS", "strength": 3,
          "evidence": "a fast against the arrest of Kejriwal", "supporting": ["arrested by the ED"],
          "evidence_quality": "explicit", "why": "fast is against the arrest"}


def make(judgement, role="primary"):
    return edge(CLAIM, judgement, TEXTS, OUTLET, "Claude (AI) A", role, "2026-10-31T00:00:00")


def test_an_accept_points_at_the_article_text_that_supports_it():
    row = make(ACCEPT)
    assert row["review_status"] == "ACCEPTED" and row["final_strength"] == 1.0
    span = row["primary_evidence"]
    assert TEXTS[span["article_id"]][span["start"] : span["end"]] == ACCEPT["evidence"]
    assert row["corroboration_count"] == 2  # two outlets carry the link
    assert row["machine_relation_type"] is None and row["machine_strength"] is None
    assert row["temporal_gap"] == 13 and row["reviewed_at"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"evidence": "a fast against the arrest of Sisodia"}, "not in the article"),
        ({"relation": "CAUSES"}, "unknown relation"),
        ({"strength": 5}, "strength"),
        ({"evidence_quality": None}, "evidence_quality"),
    ],
)
def test_an_accept_that_breaks_the_rubric_is_refused(change, message):
    with pytest.raises(ValueError, match=message):
        make({**ACCEPT, **change})


def test_a_reject_keeps_its_reason_as_a_hard_negative():
    row = make({"decision": "reject", "reject_reason": "CORRELATED_ONLY", "why": "same topic"})
    assert row["review_status"] == "REJECTED" and row["reject_reason"] == "CORRELATED_ONLY"
    with pytest.raises(ValueError, match="reason"):
        make({"decision": "reject", "reject_reason": None})


def test_agreement_is_reported_per_relation_type():
    def pair(cid, status, relation=None):
        return {"claim_id": cid, "review_status": status, "relation_type": relation,
                "reject_reason": None if status == "ACCEPTED" else "NO_CAUSAL_EVIDENCE"}

    first = [pair("1", "ACCEPTED", "TRIGGERS"), pair("2", "ACCEPTED", "ESCALATES"),
             pair("3", "REJECTED"), pair("4", "ACCEPTED", "MOTIVATES")]
    second = [pair("1", "ACCEPTED", "TRIGGERS"), pair("2", "ACCEPTED", "TRIGGERS"),
              pair("3", "REJECTED"), pair("4", "REJECTED")]
    result = agreement(first, second)
    assert result["double_annotated"] == 4 and result["decision"]["split"] == 1
    assert result["relation"]["per_type"]["TRIGGERS"]["specific_agreement"] == round(2 / 3, 4)
    assert result["relation"]["confusions"] == {"ESCALATES|TRIGGERS": 1}
    assert kappa([("a", "a"), ("b", "b")]) == 1.0 and kappa([("a", "a")]) is None


def test_double_annotation_takes_whole_seeds_for_a_quarter_of_claims():
    claims = [{"effect_event_id": f"ce:{i % 8}"} for i in range(80)]
    picked = double_sample(claims, 0.25, "x")
    assert sum(c["effect_event_id"] in picked for c in claims) == 20
