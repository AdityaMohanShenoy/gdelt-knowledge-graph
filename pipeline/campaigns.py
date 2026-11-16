"""Campaigns: one continuing protest action reported on many days.

Phase 8 merges mentions of one event, but only when their dates overlap, and a
mention's date is a single day. A sit-in reported on its first day and again on
its tenth therefore stays two events, and an "ongoing" report with no date falls
back to its article's report day. This module reads how long an action has run
("since February 13", "for 50 days", "entered its 10th day", "indefinite") into
a date range, and folds judged episodes of one campaign into a campaign node.

A campaign is not a time window: a clash, an arrest or a rail roko during a sit-in
is a separate action and stays its own event. Only pairs judged to be the same
continuing action join, as with every other merge in this pipeline.
"""

import datetime as dt
import hashlib
import re

from canonical_events import resolve_time

ORDINALS = {w: i for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth "
    "twentieth".split(), 1)}
SINCE = re.compile(r"\bsince\s+([^,.;]+)", re.I)
FOR_DAYS = re.compile(r"\b(?:for|since|over|nearly|almost|about)\s+(?:the\s+)?(?:past\s+|last\s+)?"
                      r"(\d+)\s+days?\b|\b(\d+)[- ]day[- ]long\b|\bnearly\s+(\d+)\s+days\b", re.I)
NTH_DAY = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+day\b|\bday\s+(\d+)\b|"
                     rf"\b({'|'.join(ORDINALS)})\s+day\b", re.I)
ONGOING = re.compile(r"\b(indefinite|continu\w+|ongoing|camping|camped|sit-in|"
                     r"fast[- ]unto[- ]death|have been (?:protesting|on)|has been)\b", re.I)


def duration(sentences: list[str], best: dt.date, report: dt.date) -> dict:
    """The range an action is stated to have run, and what the text says.

    `best` is the event's own resolved day, `report` its article's report day.
    Without duration wording the range is the single best day."""
    text = " ".join(sentences)
    start, basis = None, None
    for m in SINCE.finditer(text):  # "since then" first must not hide "since February 13"
        when = resolve_time(m.group(1), report, announced=False)
        if when["confidence"] in ("high", "medium") and when["best"] <= report:
            start, basis = when["best"], f"since {m.group(1).strip()[:40]}"
            break
    if start is None and (m := FOR_DAYS.search(text)):
        days = int(next(g for g in m.groups() if g))
        start, basis = report - dt.timedelta(days=days), m.group(0)
    if start is None and (m := NTH_DAY.search(text)):
        n = int(m.group(1) or m.group(2)) if (m.group(1) or m.group(2)) else ORDINALS[
            m.group(3).lower()]
        start, basis = report - dt.timedelta(days=n - 1), m.group(0)
    ongoing = bool(ONGOING.search(text))
    if start is None:
        return {"start": best.isoformat(), "end": (report if ongoing else best).isoformat(),
                "basis": "ongoing wording" if ongoing else None, "stated": False}
    return {"start": min(start, best).isoformat(), "end": max(report, best).isoformat(),
            "basis": basis, "stated": True}


def fold_campaigns(groups: list[list[str]], nodes: dict, ranges: dict,
                   names: dict | None = None) -> dict[str, dict]:
    """Campaign nodes from judged groups of episodes: one node per group, spanning
    every member's range, named after the member whose text states the range
    (else the shortest name). Returns {campaign id: node}."""
    names = names or {n: nodes[n]["description"] for g in groups for n in g}
    out = {}
    for group in groups:
        members = sorted(group)
        cid = "cp:" + hashlib.sha256("|".join(members).encode()).hexdigest()[:16]
        starts = [ranges[m]["start"] for m in members]
        ends = [ranges[m]["end"] for m in members]
        out[cid] = {
            "id": cid, "kind": "campaign",
            "description": names[min(members, key=lambda m: (
                not ranges[m]["stated"], len(names[m]), names[m]))],
            "date": min(starts), "date_range": [min(starts), max(ends)],
            "range_stated": any(ranges[m]["stated"] for m in members),
            "episodes": members,
            "actors": sorted({a for m in members for a in nodes[m].get("actors", [])}),
            "locations": sorted({p for m in members for p in nodes[m].get("locations", [])}),
            "source_urls": sorted({u for m in members for u in nodes[m].get("source_urls") or []}),
            "search_status": "PARENTS_FOUND" if any(
                nodes[m]["search_status"] == "PARENTS_FOUND" for m in members)
            else nodes[members[0]]["search_status"],
        }
    return out
