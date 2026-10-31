import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from causal_candidates import claim, in_window, proposed, queue, signals  # noqa: E402


def event(eid, best, start=None, end=None, sources=("a1",), actors=(), locations=(), sentences=()):
    return {
        "canonical_event_id": eid,
        "best_time": best,
        "time_range": [start or best, end or best],
        "supporting_sources": list(sources),
        "actors": list(actors),
        "targets": [],
        "locations": list(locations),
        "sentences": list(sentences),
    }


SEED = event("ce:seed", "2024-03-22", actors=["AAP workers"], locations=["Srinagar"])


def test_only_earlier_or_ongoing_events_can_be_causes():
    assert in_window(SEED, event("ce:a", "2024-03-21"))  # the day before
    assert in_window(SEED, event("ce:b", "2024-03-22"))  # same day
    assert not in_window(SEED, event("ce:c", "2024-03-23"))  # after: never a cause
    assert not in_window(SEED, event("ce:d", "2024-03-01"))  # beyond the window
    # A sit-in that began weeks earlier and is still under way stays in reach.
    assert in_window(SEED, event("ce:e", "2024-02-13", "2024-02-13", "2024-03-30"))


def test_any_one_signal_proposes_and_none_is_required():
    arrest = event("ce:arrest", "2024-03-21", sources=("a2",),
                   sentences=["Kejriwal was arrested by the ED."])
    nothing = signals(SEED, arrest, similarity=0.1)
    assert not proposed(nothing)
    co_reported = signals(SEED, event("ce:x", "2024-03-21", sources=("a1",)), similarity=0.1)
    assert co_reported["same_article"] == ["a1"] and proposed(co_reported)
    similar = signals(SEED, arrest, similarity=0.6)
    assert proposed(similar)


def test_queue_spreads_across_seeds_and_ids_are_stable():
    def make(seed_id, n, score):
        seed = {**SEED, "canonical_event_id": seed_id}
        cause = event(f"ce:{seed_id}:{n}", "2024-03-21")
        found = signals(seed, cause, similarity=score)
        return claim(seed, cause, found, {"effect": [], "cause": []})

    claims = [make("s1", n, 0.9 - n / 10) for n in range(3)] + [make("s2", 0, 0.5)]
    ordered = queue(claims)
    assert [c["effect_event_id"] for c in ordered[:2]] == ["s1", "s2"]  # one each first
    assert [c["seed_rank"] for c in ordered] == [1, 1, 2, 3]
    assert make("s1", 0, 0.9)["claim_id"] == claims[0]["claim_id"]
    assert all(c["verdict"] == "unreviewed" for c in ordered)
