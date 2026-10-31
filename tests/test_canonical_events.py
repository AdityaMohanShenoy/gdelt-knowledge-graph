import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from canonical_events import (  # noqa: E402
    candidate_pairs,
    canonical_event,
    clusters,
    merged_pairs,
    resolve_time,
)

THURSDAY = dt.date(2024, 3, 21)


@pytest.mark.parametrize(
    ("text", "announced", "best", "confidence"),
    [
        ("March 21", False, dt.date(2024, 3, 21), "high"),
        ("21 March", False, dt.date(2024, 3, 21), "high"),
        ("Sept. 16", False, dt.date(2023, 9, 16), "high"),  # past side of the report
        ("Monday", False, dt.date(2024, 3, 18), "medium"),
        ("Monday", True, dt.date(2024, 3, 25), "medium"),  # an announced Monday is ahead
        ("yesterday", False, dt.date(2024, 3, 20), "medium"),
        (None, False, THURSDAY, "low"),
    ],
)
def test_relative_times_resolve_against_the_report_date(text, announced, best, confidence):
    when = resolve_time(text, THURSDAY, announced)
    assert (when["best"], when["confidence"]) == (best, confidence)
    assert when["start"] <= when["best"] <= when["end"] or when["rule"] == "month"


def mention(mid, article, event_type="17", status="asserted", day=THURSDAY, outlet="a.in"):
    return {
        "event_mention_id": mid,
        "source_article_id": article,
        "event_type": event_type,
        "status": status,
        "when": {"best": day, "start": day, "end": day, "confidence": "high"},
        "action": {"text": "arrested"},
        "actors": [{"text": "the ED"}],
        "targets": [],
        "locations": [],
        "outlet": outlet,
    }


def test_blocking_never_pairs_within_an_article_or_across_status_type_or_time():
    far = THURSDAY + dt.timedelta(days=10)
    found = [
        mention("1:1", "1"),
        mention("1:2", "1"),
        mention("2:1", "2"),
        mention("3:1", "3", event_type="14"),
        mention("4:1", "4", status="announced"),
        mention("5:1", "5", day=far),
    ]
    assert candidate_pairs(found) == [(0, 2), (1, 2)]


def test_nothing_merges_without_a_judgement_below_auto_and_judgements_win():
    scored = [
        {"key": "a|b", "a": "a", "b": "b", "score": 0.99},
        {"key": "a|c", "a": "a", "b": "c", "score": 0.30},
        {"key": "b|c", "a": "b", "b": "c", "score": 0.10},
        {"key": "c|d", "a": "c", "b": "d", "score": 0.95},
    ]
    tiers = merged_pairs(scored, {"a|b": "different", "b|c": "same"}, float("inf"), 0.25)
    assert [p["key"] for p in tiers["reviewed"]] == ["b|c"]
    assert [p["key"] for p in tiers["auto"]] == []  # auto off: even 0.95 waits for review
    assert {p["key"] for p in tiers["rejected"]} == {"a|b", "a|c", "c|d"}
    assert next(p for p in tiers["rejected"] if p["key"] == "a|c")["unreviewed_in_band"]


def test_a_cluster_built_through_a_third_report_is_flagged_not_trusted():
    groups = clusters(["a", "b", "c"], [{"a": "a", "b": "b"}, {"a": "b", "b": "c"}])
    assert groups == [["a", "b", "c"]]
    members = [
        mention("a", "1", outlet="thehindu.com"),
        mention("b", "2", outlet="rediff.com"),
        mention("c", "3", outlet="rediff.com"),  # syndicated copy: same outlet
    ]
    event = canonical_event(members, [("a", "c")])
    assert event["review_status"] == "CONFLICT"
    assert event["supporting_sources"] == ["1", "2", "3"]
    assert event["independent_outlets"] == ["rediff.com", "thehindu.com"]
    assert event["best_time"] == "2024-03-21" and event["event_type"] == "17"
    assert canonical_event(members[:1], [])["review_status"] == "SINGLE"
