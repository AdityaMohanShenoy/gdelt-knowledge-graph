"""Phase 8: merge mentions of one real event, reported by different articles.

A mention's date is resolved against its article's report date (the earliest
GDELT observation day): weekdays, "yesterday", "February 13" and the like.
Candidate pairs are blocked on event type, status and overlapping dates, then
scored on actor, place, action and sentence similarity. Merging is a decision,
not a score: pairs are labelled merge / separate, and only labelled merges join.
Never merge on a shared URL or GDELT row; two articles are never assumed to be
the same story.
"""

import datetime as dt
import hashlib
import re

WEEKDAYS = {
    d: i for i, d in enumerate("monday tuesday wednesday thursday friday saturday sunday".split())
}
MONTHS = {
    **{
        m: i
        for i, m in enumerate(
            "january february march april may june july august september october november "
            "december".split(),
            1,
        )
    },
    **{m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)},
    "sept": 9,
}
MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
# (?!\d): "May 2024" is a month and year, not May 20.
MONTH_DAY = re.compile(
    rf"\b({MONTH})\.?\s+(\d{{1,2}})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", re.I
)
DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?!\d)(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH})\.?(?:,?\s+(\d{{4}}))?", re.I
)
STOP = frozenset(
    "the a an of in on at to for and or by with from as its their his her this that these those "
    "who which was were is are be been has have had said says".split()
)


def anchor_date(gold: dict) -> dt.date:
    """The article's report date: its earliest GDELT observation day."""
    days = [o["day"] for o in gold["source_metadata"].get("gdelt_observations") or []]
    if not days:
        raise ValueError(f"{gold['article_id']}: no GDELT day to anchor dates on")
    return dt.datetime.strptime(str(min(days)), "%Y%m%d").date()


def nearest_year(month: int, day: int, anchor: dt.date, future: bool) -> dt.date | None:
    """A bare 'February 13' takes the year that keeps it closest to the report,
    on the side of the report its status implies (past if asserted)."""
    options = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            options.append(dt.date(year, month, day))
        except ValueError:
            continue
    slack = dt.timedelta(days=3)
    side = [d for d in options if (d >= anchor - slack if future else d <= anchor + slack)]
    side = side or options
    return min(side, key=lambda d: abs((d - anchor).days)) if side else None


def resolve_time(text: str | None, anchor: dt.date, announced: bool) -> dict:
    """A best date, a range and a confidence for a mention's time expression.

    No usable expression falls back to the report date with a wide, low-confidence
    range: past for asserted events, near future for announced ones."""
    def result(best, start, end, confidence, rule):
        return {"best": best, "start": start, "end": end, "confidence": confidence, "rule": rule}

    lowered = (text or "").lower()
    found = MONTH_DAY.search(lowered) or DAY_MONTH.search(lowered)
    if found:
        groups = found.groups()
        if found.re is MONTH_DAY:
            month_word, day_text = groups[0], groups[1]
        else:
            month_word, day_text = groups[1], groups[0]
        month, day = MONTHS[month_word.lower()], int(day_text)
        date = None
        if groups[2]:
            try:
                date = dt.date(int(groups[2]), month, day)
            except ValueError:
                date = None
        else:
            date = nearest_year(month, day, anchor, announced)
        if date:
            return result(date, date, date, "high", "calendar date")
    for name, index in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lowered):
            back = (anchor.weekday() - index) % 7
            ahead = dt.timedelta(days=(7 - back) % 7)
            date = anchor + ahead if announced else anchor - dt.timedelta(days=back)
            return result(date, date, date, "medium", "weekday")
    if re.search(r"\b(today|tonight|this (morning|afternoon|evening))\b", lowered):
        return result(anchor, anchor - dt.timedelta(days=1), anchor, "medium", "today")
    if re.search(r"\b(yesterday|last night)\b", lowered):
        date = anchor - dt.timedelta(days=1)
        return result(date, date - dt.timedelta(days=1), date, "medium", "yesterday")
    if re.search(r"\blast week\b", lowered):
        week = dt.timedelta(days=7)
        return result(anchor - week, anchor - 2 * week, anchor - dt.timedelta(days=5), "low",
                      "last week")
    month_only = re.search(rf"\b({MONTH})\b", lowered)
    if month_only:
        month = MONTHS[month_only.group(1)]
        start = nearest_year(month, 1, anchor, announced)
        if start:
            next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            end = next_month - dt.timedelta(days=1)
            return result(start + (end - start) / 2, start, end, "low", "month")
    if announced:
        return result(anchor, anchor, anchor + dt.timedelta(days=14), "low", "report date")
    return result(anchor, anchor - dt.timedelta(days=3), anchor, "low", "report date")


def words(texts: list[str]) -> set[str]:
    found = (w for t in texts for w in re.findall(r"[a-z0-9]+", t.lower()))
    return {w for w in found if len(w) > 2 and w not in STOP}


def jaccard(a: set, b: set) -> float | None:
    """None when either side is empty: an unstated field is unknown, not a mismatch."""
    return len(a & b) / len(a | b) if a and b else None


def overlaps(a: dict, b: dict, slack: int = 1) -> bool:
    pad = dt.timedelta(days=slack)
    return a["start"] <= b["end"] + pad and b["start"] <= a["end"] + pad


def candidate_pairs(mentions: list[dict]) -> list[tuple[int, int]]:
    """Cross-article pairs that could be one event: same status, compatible type,
    overlapping dates. Blocking only; nothing here decides a merge."""
    pairs = []
    for i, a in enumerate(mentions):
        for j in range(i + 1, len(mentions)):
            b = mentions[j]
            if a["source_article_id"] == b["source_article_id"] or a["status"] != b["status"]:
                continue
            if a["event_type"] and b["event_type"] and a["event_type"] != b["event_type"]:
                continue
            if overlaps(a["when"], b["when"]):
                pairs.append((i, j))
    return pairs


def pair_features(a: dict, b: dict, similarity: float) -> dict:
    texts = lambda m, f: [s["text"] for s in m[f]]  # noqa: E731
    gap = abs((a["when"]["best"] - b["when"]["best"]).days)
    return {
        "actors": jaccard(words(texts(a, "actors")), words(texts(b, "actors"))),
        "targets": jaccard(words(texts(a, "targets")), words(texts(b, "targets"))),
        "locations": jaccard(words(texts(a, "locations")), words(texts(b, "locations"))),
        "action": jaccard(words([a["action"]["text"]]), words([b["action"]["text"]])),
        "sentence_similarity": round(similarity, 4),
        "day_gap": gap,
        "both_dated": a["when"]["confidence"] != "low" and b["when"]["confidence"] != "low",
    }


def score(features: dict) -> float:
    """Orders pairs for review; it is not a merge probability. Missing fields are
    skipped, not counted against the pair."""
    parts = [
        (features["sentence_similarity"], 3.0),
        (features["actors"], 2.0),
        (features["locations"], 1.5),
        (features["action"], 1.0),
        (features["targets"], 1.0),
    ]
    present = [(v, w) for v, w in parts if v is not None]
    base = sum(v * w for v, w in present) / sum(w for _, w in present)
    if features["both_dated"] and features["day_gap"] == 0:
        base += 0.1
    return round(min(1.0, base), 4)


CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}


def merged_pairs(scored: list[dict], decisions: dict[str, str], auto: float, review: float) -> dict:
    """Which pairs merge, and by which tier.

    A judged pair follows its judgement. An unjudged pair merges only at or above
    `auto`; nothing below the review band is ever merged without a judgement."""
    tiers: dict[str, list] = {"auto": [], "reviewed": [], "rejected": [], "below_band": []}
    for pair in scored:
        verdict = decisions.get(pair["key"])
        if verdict == "same":
            tiers["reviewed"].append(pair)
        elif verdict == "different":
            tiers["rejected"].append(pair)
        elif pair["score"] >= auto:
            tiers["auto"].append(pair)
        elif pair["score"] >= review:
            tiers["rejected"].append({**pair, "unreviewed_in_band": True})
        else:
            tiers["below_band"].append(pair)
    return tiers


def clusters(ids: list[str], merges: list[dict]) -> list[list[str]]:
    parent = {i: i for i in ids}

    def find(i: str) -> str:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for pair in merges:
        parent[find(pair["a"])] = find(pair["b"])
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def canonical_event(members: list[dict], conflicts: list[tuple]) -> dict:
    """One canonical event from the mentions judged to be the same development."""
    def precision(m: dict) -> tuple:
        return (-CONFIDENCE_RANK[m["when"]["confidence"]], m["when"]["best"], m["event_mention_id"])

    lead = min(members, key=precision)
    # The time range comes from the best-dated reports only; vaguer ones would widen it.
    best = [m["when"] for m in members if m["when"]["confidence"] == lead["when"]["confidence"]]
    starts, ends = [w["start"] for w in best], [w["end"] for w in best]
    types = [m["event_type"] for m in members if m["event_type"]]

    def texts(field: str) -> list[str]:
        seen: dict[str, str] = {}
        for m in members:
            for s in m[field]:
                seen.setdefault(s["text"].lower(), s["text"])
        return sorted(seen.values())

    ids = sorted(m["event_mention_id"] for m in members)
    digest = hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
    return {
        "canonical_event_id": f"ce:{digest}",
        # Generated from fields for display; the evidence is the member spans.
        "description": " ".join(
            filter(None, [", ".join(texts("actors")), (lead["action"] or {}).get("text")])
        ),
        "event_type": max(set(types), key=types.count) if types else None,
        "status": lead["status"],
        "actors": texts("actors"),
        "targets": texts("targets"),
        "locations": texts("locations"),
        "best_time": lead["when"]["best"].isoformat(),
        "time_range": [min(starts).isoformat(), max(ends).isoformat()],
        "time_confidence": lead["when"]["confidence"],
        "supporting_sources": sorted({m["source_article_id"] for m in members}),
        # Syndicated copies are one outlet, not independent confirmation.
        "independent_outlets": sorted({m["outlet"] for m in members}),
        "mentions": ids,
        "review_status": "CONFLICT" if conflicts else ("MERGED" if len(members) > 1 else "SINGLE"),
        "conflicts": [list(c) for c in conflicts],
    }
