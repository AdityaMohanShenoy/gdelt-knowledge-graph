"""Phase 9: candidate causes for each protest seed, from canonical events.

Retrieval is broad on purpose: any event in the window before a seed that shares
an article, actors, a place, named words or similar wording becomes a candidate.
These signals propose; none of them is evidence of cause. Every candidate is
stored as an unreviewed claim, including the ones review will reject, because
rejections are the hard negatives later phases learn from.

GATE 11 showed the GDELT-group scorer never retrieved the causes articles name,
so this retrieves from the text pipeline (reviewed mentions, canonical events).
"""

import datetime as dt
import hashlib
import re

WINDOW_DAYS = 7
GRIEVANCE_DAYS = 180  # a longer stratum, for triggers weeks or months back
SIMILARITY_FLOOR = 0.45  # proposes a candidate; never a confidence
FAR_SIMILARITY = 0.55  # for events beyond WINDOW_DAYS, with a shared actor or place
CONDITION_SIMILARITY = 0.6  # for conditions not reported in the seed's article


def day(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def content(texts: list[str]) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", " ".join(texts).lower()) if len(w) > 3}


def is_seed(event: dict, mentions: dict, articles: dict) -> bool:
    """An asserted 2024 protest that is the main event of a protest article."""
    focal = [mentions[m] for m in event["mentions"] if mentions[m]["focal"]]
    return (
        event["event_type"] == "14"
        and event["status"] == "asserted"
        and day(event["best_time"]).year == 2024
        and any(
            articles[m["source_article_id"]]["eligibility"]["protest_relevance"] == "PROTEST"
            for m in focal
        )
    )


def in_window(seed: dict, cause: dict, days: int = WINDOW_DAYS) -> bool:
    """The cause happens before or during the seed, within `days`, or is still
    under way when the seed happens. Nothing after the seed can cause it."""
    seed_day, cause_day = day(seed["best_time"]), day(cause["best_time"])
    if cause_day > seed_day:
        return False
    start, end = (day(x) for x in cause["time_range"])
    return seed_day - cause_day <= dt.timedelta(days=days) or start <= seed_day <= end


def signals(seed: dict, cause: dict, similarity: float) -> dict:
    fields = lambda e: e["actors"] + e["targets"] + e["locations"]  # noqa: E731
    shared_names = (content(fields(seed)) & content(cause["sentences"])) | (
        content(fields(cause)) & content(seed["sentences"])
    )
    return {
        "same_article": sorted(set(seed["supporting_sources"]) & set(cause["supporting_sources"])),
        "actors": sorted(content(seed["actors"]) & content(cause["actors"])),
        "locations": sorted(content(seed["locations"]) & content(cause["locations"])),
        "shared_names": sorted(shared_names),
        "similarity": round(similarity, 4),
    }


def proposed(found: dict, reach: str = "near") -> bool:
    """Any one signal proposes a near event. Beyond the 7-day window one weak signal
    would propose most of the corpus, so a far event needs the same article, or
    similar wording with a shared actor or place; a condition needs the same
    article or closer wording. Thresholds were set on the 20 judged recall seeds
    (docs/measurements/conditions.md), so they are tuned, not validated."""
    if reach == "far":
        return bool(
            found["same_article"]
            or (found["similarity"] >= FAR_SIMILARITY and (found["actors"] or found["locations"]))
        )
    if reach == "condition":
        return bool(found["same_article"] or found["similarity"] >= CONDITION_SIMILARITY)
    return bool(
        found["same_article"]
        or found["actors"]
        or found["locations"]
        or found["shared_names"]
        or found["similarity"] >= SIMILARITY_FLOOR
    )


def condition_node(condition: dict, sentences: list[str]) -> dict:
    """A canonical condition in the shape retrieval reads: holders stand in for actors,
    and its validity window for its time range. It is in effect at a seed when the
    window covers the seed's day."""
    return {
        "canonical_event_id": condition["canonical_condition_id"],
        "cause_kind": "condition",
        "event_type": None,
        "actors": condition["holders"],
        "targets": [],
        "locations": condition["locations"],
        "best_time": condition["valid_from"],
        "time_range": [condition["valid_from"], condition["valid_to"]],
        "supporting_sources": condition["supporting_sources"],
        "sentences": sentences,
    }


def retrieval_score(found: dict) -> float:
    """Orders the review queue. It is not a probability of cause, and GATE 3.5
    showed fused scores of this kind cannot tell real pairs from shuffled ones."""
    return round(
        2.0 * bool(found["same_article"])
        + found["similarity"]
        + 0.5 * bool(found["actors"])
        + 0.5 * bool(found["locations"])
        + 0.3 * bool(found["shared_names"]),
        4,
    )


def claim(
    seed: dict, cause: dict, found: dict, evidence: dict, retriever: str = "text-retrieval.v1"
) -> dict:
    key = f"{seed['canonical_event_id']}<-{cause['canonical_event_id']}"
    return {
        "claim_id": "cl:" + hashlib.sha256(key.encode()).hexdigest()[:16],
        "effect_event_id": seed["canonical_event_id"],
        "cause_event_id": cause["canonical_event_id"],
        "cause_kind": cause.get("cause_kind", "event"),
        # A condition's start is usually the assumed fallback, so it has no lag.
        "lag_days": None
        if cause.get("cause_kind") == "condition"
        else (day(seed["best_time"]) - day(cause["best_time"])).days,
        "signals": found,
        "retrieval_score": retrieval_score(found),
        "evidence": evidence,
        "verdict": "unreviewed",
        "retriever": retriever,
    }


def queue(claims: list[dict]) -> list[dict]:
    """Round-robin across seeds by each seed's own ranking, so review spreads over
    seeds instead of draining the first seed's candidates."""
    by_seed: dict[str, list[dict]] = {}
    for c in sorted(claims, key=lambda c: (-c["retrieval_score"], c["claim_id"])):
        by_seed.setdefault(c["effect_event_id"], []).append(c)
    ordered, depth = [], 0
    while any(len(v) > depth for v in by_seed.values()):
        for seed_id in sorted(by_seed):
            if len(by_seed[seed_id]) > depth:
                ordered.append({**by_seed[seed_id][depth], "seed_rank": depth + 1})
        depth += 1
    return [{**c, "queue_position": i} for i, c in enumerate(ordered, 1)]
