"""Conditions and remarks: the causes an event-only graph cannot hold.

Phase 9 found that about three quarters of the causes articles name are
persistent states (a water crisis, a surety bond, rising violence against doctors)
and two were remarks (an insult). This module turns AI extraction of both into
records whose every field is verbatim article text, as event mentions are.

A condition is observed on its article's report date. Unless the text states when
it began or ended, that one day is all the evidence fixes, so its validity window
for retrieval is a wide, low-confidence guess around it, not a fact.
"""

import datetime as dt
import hashlib
import re

from canonical_events import DAY_MONTH, MONTH, MONTH_DAY, MONTHS, anchor_date, resolve_time
from event_mentions import SCHEMA_VERSION, locate, text_hash, validate_mention

CONDITION_SCHEMA = "condition-mention.v1"
KINDS = frozenset("policy shortage violence economic governance other".split())
STATUSES = frozenset({"ongoing", "ended", "unclear"})
ROLES = frozenset({"protest_cause", "context"})
REMARK_TYPES = frozenset({"01", "11", "12", "13"})
LOOKBACK = dt.timedelta(days=180)  # a condition is assumed to hold this long before it is reported
LOOKAHEAD = dt.timedelta(days=30)  # and this long after, unless the text says it ended
YEAR = re.compile(r"\b(19|20)\d{2}\b")


def bound(span: dict | None, anchor: dt.date) -> dt.date | None:
    """A date from a `since`/`until` span: a calendar date, else the first day of a
    stated month and year, or of a stated year."""
    if span is None:
        return None
    lowered = span["text"].lower()
    if MONTH_DAY.search(lowered) or DAY_MONTH.search(lowered):
        return resolve_time(span["text"], anchor, announced=False)["best"]
    year = YEAR.search(lowered)
    month = re.search(rf"\b({MONTH})\b", lowered)
    return dt.date(int(year.group()), MONTHS[month.group(1)] if month else 1, 1) if year else None


def validity(condition: dict, anchor: dt.date) -> dict:
    """When the condition can be taken to hold, and how much of that the text states."""
    start = bound(condition["since"], anchor)
    end = bound(condition["until"], anchor) if condition["status"] == "ended" else None
    return {
        "observed": anchor.isoformat(),
        "start": (start or anchor - LOOKBACK).isoformat(),
        "end": (end or anchor + LOOKAHEAD).isoformat(),
        "start_stated": start is not None,
        "end_stated": end is not None,
    }


def apply_extraction(gold: dict, extraction: dict, reviewer: str) -> tuple:
    """Conditions and remark events for one article, keeping only verbatim spans.

    Returns (conditions, remark mentions, values dropped for not being verbatim)."""
    text = gold["article_text"]
    sentences = {s["sentence_id"]: s for s in gold["sentences"]}
    anchor = anchor_date(gold)
    dropped = 0

    def spans(values: list | None, sentence: dict) -> list[dict]:
        nonlocal dropped
        found = [locate(v, sentence) for v in values or []]
        dropped += found.count(None)
        return [s for s in found if s is not None]

    def one(value: str | None, sentence: dict) -> dict | None:
        nonlocal dropped
        if not value:
            return None
        found = locate(value, sentence)
        dropped += found is None
        return found

    conditions = []
    for n, entry in enumerate(extraction.get("conditions") or [], 1):
        sentence = sentences.get(entry.get("sentence_id"))
        span = one(entry.get("condition"), sentence) if sentence else None
        if sentence is None or span is None:
            dropped += sentence is None
            continue
        record = {
            "schema_version": CONDITION_SCHEMA,
            "condition_mention_id": f"{gold['article_id']}:{sentence['sentence_id']}:k{n}",
            "source_article_id": gold["article_id"],
            "text_sha256": text_hash(text),
            "sentence_id": sentence["sentence_id"],
            "evidence_start": sentence["start_char"],
            "evidence_end": sentence["end_char"],
            "condition": span,
            "holders": spans(entry.get("holders"), sentence),
            "locations": spans(entry.get("locations"), sentence),
            "since": one(entry.get("since"), sentence),
            "until": one(entry.get("until"), sentence),
            "status": entry.get("status") if entry.get("status") in STATUSES else "unclear",
            "kind": entry.get("kind") if entry.get("kind") in KINDS else "other",
            "role": entry.get("role") if entry.get("role") in ROLES else "context",
            "review_status": "REVIEWED",
            "reviewer": reviewer,
            "label_source": "ai_assisted",
        }
        record["validity"] = validity(record, anchor)
        validate_condition(record, text)
        conditions.append(record)

    remarks = []
    for n, entry in enumerate(extraction.get("remarks") or [], 1):
        sentence = sentences.get(entry.get("sentence_id"))
        action = one(entry.get("action"), sentence) if sentence else None
        if sentence is None or action is None:
            dropped += sentence is None
            continue
        mention = {
            "schema_version": SCHEMA_VERSION,
            "event_mention_id": f"{gold['article_id']}:{sentence['sentence_id']}:s{n}",
            "source_article_id": gold["article_id"],
            "text_sha256": text_hash(text),
            "sentence_id": sentence["sentence_id"],
            "evidence_start": sentence["start_char"],
            "evidence_end": sentence["end_char"],
            "action": {**action, "lemma": None},
            "actors": spans(entry.get("actors"), sentence),
            "targets": spans(entry.get("targets"), sentence),
            "locations": [],
            "event_time": one(entry.get("event_time"), sentence),
            "event_type": entry["event_type"] if entry.get("event_type") in REMARK_TYPES else None,
            "status": "asserted",
            "provoked_reaction": bool(entry.get("provoked_reaction")),
            "focal": False,
            "origin": "remark_added",
            "confidence": None,
            "review_status": "REVIEWED",
            "extractor": None,
            "reviewer": reviewer,
            "label_source": "ai_assisted",
            "corrected": False,
        }
        validate_mention(mention, text)
        remarks.append(mention)
    return conditions, remarks, dropped


def validate_condition(record: dict, text: str) -> None:
    if record["text_sha256"] != text_hash(text):
        raise ValueError(f"{record['condition_mention_id']}: pinned text hash mismatch")
    start, end = record["evidence_start"], record["evidence_end"]
    fields = [record["condition"], record["since"], record["until"]]
    fields += record["holders"] + record["locations"]
    for field in (f for f in fields if f is not None):
        if text[field["start"] : field["end"]] != field["text"]:
            raise ValueError(f"{record['condition_mention_id']}: span text differs from article")
        if not start <= field["start"] < field["end"] <= end:
            raise ValueError(f"{record['condition_mention_id']}: field outside its evidence")


def holds_at(validity: dict, day: dt.date) -> bool:
    return dt.date.fromisoformat(validity["start"]) <= day <= dt.date.fromisoformat(validity["end"])


def condition_text(record: dict) -> str:
    return record["condition"]["text"]


def condition_pairs(records: list[dict], vectors, floor: float) -> list[dict]:
    """Cross-article condition pairs worth judging: similar wording, or a shared holder or
    place with some similarity. Ordering only; a judgement decides every merge."""
    words = lambda r: {  # noqa: E731
        w
        for s in r["holders"] + r["locations"]
        for w in re.findall(r"[a-z0-9]+", s["text"].lower())
        if len(w) > 3
    }
    pairs = []
    for i, a in enumerate(records):
        for j in range(i + 1, len(records)):
            b = records[j]
            if a["source_article_id"] == b["source_article_id"]:
                continue
            similarity = float(vectors[i] @ vectors[j])
            shared = sorted(words(a) & words(b))
            if similarity >= floor or (shared and similarity >= floor - 0.15):
                pairs.append(
                    {
                        "key": f"{a['condition_mention_id']}|{b['condition_mention_id']}",
                        "a": a["condition_mention_id"],
                        "b": b["condition_mention_id"],
                        "score": round(similarity, 4),
                        "shared_holder_or_place": shared,
                    }
                )
    return sorted(pairs, key=lambda p: (-p["score"], p["key"]))


def canonical_condition(members: list[dict], conflicts: list[tuple], outlet) -> dict:
    """One canonical condition from the mentions judged to be the same state."""
    ids = sorted(m["condition_mention_id"] for m in members)
    kinds = [m["kind"] for m in members]
    texts = lambda f: sorted({s["text"] for m in members for s in m[f]})  # noqa: E731
    stated = [m["validity"]["start"] for m in members if m["validity"]["start_stated"]]
    return {
        "canonical_condition_id": "cc:" + hashlib.sha256("|".join(ids).encode()).hexdigest()[:16],
        "description": sorted({condition_text(m) for m in members}, key=len)[0],
        "phrasings": sorted({condition_text(m) for m in members}),
        "kind": max(set(kinds), key=kinds.count),
        "role": next(
            (m["role"] for m in members if m["role"] == "protest_cause"), "context"
        ),
        "holders": texts("holders"),
        "locations": texts("locations"),
        "observed": sorted({m["validity"]["observed"] for m in members}),
        # Stated start where any report gives one; otherwise the fallback window.
        "valid_from": min(stated) if stated else min(m["validity"]["start"] for m in members),
        "valid_from_stated": bool(stated),
        "valid_to": max(m["validity"]["end"] for m in members),
        "supporting_sources": sorted({m["source_article_id"] for m in members}),
        "independent_outlets": sorted({outlet(m) for m in members}),
        "mentions": ids,
        "review_status": "CONFLICT" if conflicts else ("MERGED" if len(members) > 1 else "SINGLE"),
        "conflicts": [list(c) for c in conflicts],
    }
