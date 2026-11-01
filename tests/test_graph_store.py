import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

from graph_store import compile_graph, load, snapshot, version  # noqa: E402

from store import db  # noqa: E402

DATABASE_URL = os.environ.get(
    "EVIDENCE_DATABASE_URL",
    os.environ.get("ARTICLE_DATABASE_URL", db.DEFAULT_DATABASE_URL),
)
SPAN = {"article_id": "7", "start": 0, "end": 24, "text": "AAP protested the arrest"}


def edge(claim, status, role="primary", strength=1.0, reason=None):
    accepted = status == "ACCEPTED"
    return {"claim_id": claim, "review_status": status, "annotation_role": role,
            "reviewer_id": f"Claude (AI) {role}", "relation_type": "TRIGGERS" if accepted else None,
            "reject_reason": reason, "why": "test",
            "final_strength": strength if accepted else None,
            "primary_evidence": SPAN if accepted else None, "supporting_evidence": [],
            "evidence_quality": "explicit" if accepted else None,
            "corroboration_count": 1 if accepted else 0,
            "reviewed_at": "2026-10-31T00:00:00+00:00", "label_source": "ai_assisted"}


def event(eid, when, mentions):
    return {"canonical_event_id": eid, "event_type": "14", "description": eid, "best_time": when,
            "time_range": [when, when], "time_confidence": "high", "supporting_sources": ["7"],
            "status": "asserted", "actors": [], "targets": [], "locations": [],
            "mentions": mentions}


def mention(mid, eid):
    return {"event_mention_id": mid, "canonical": eid, "source_article_id": "7",
            "action": {"text": "protested"}, "event_type": "14", "evidence_start": 0,
            "evidence_end": 24, "text_sha256": "x", "status": "asserted", "actors": [],
            "reviewer": "Claude (AI)", "label_source": "ai_assisted"}


def claim(cid, cause, effect):
    return {"claim_id": cid, "cause_event_id": cause, "effect_event_id": effect,
            "cause_kind": "event", "retriever": "test", "signals": {}, "lag_days": 1,
            "expansion_level": 1}


DATA = {
    "articles": {"7": {"url": "https://example.test/a", "url_key": "https://example.test/a",
                       "fetched_at": None, "content_hash": None, "raw_html_path": None,
                       "fetch_status": "extracted"}},
    "events": [event("ce:arrest", "2024-03-21", ["7:1:1"]),
               event("ce:protest", "2024-03-22", ["7:2:1"]),
               event("ce:rally", "2024-03-20", ["7:3:1"])],
    "event_mentions": [mention("7:1:1", "ce:arrest"), mention("7:2:1", "ce:protest"),
                       mention("7:3:1", "ce:rally")],
    "conditions": [], "condition_mentions": [],
    "claims": [claim("cl:1", "ce:arrest", "ce:protest"), claim("cl:2", "ce:rally", "ce:protest")],
    "edges": [edge("cl:1", "ACCEPTED", strength=1.0),
              edge("cl:2", "ACCEPTED", strength=1 / 3),
              edge("cl:2", "REJECTED", role="second", reason="INSUFFICIENT_EVIDENCE")],
    "status": {"ce:protest": "PARENTS_FOUND", "ce:arrest": "NO_SUPPORTED_PARENT_FOUND"},
    "spot_check": [],
}


async def _in_throwaway_schema(body):
    name = f"graph_test_{uuid.uuid4().hex}"
    connection = await asyncpg.connect(DATABASE_URL, timeout=2)
    try:
        await db.init(connection, name)
        return await body(connection, name)
    finally:
        await connection.execute(f'DROP SCHEMA "{name}" CASCADE')
        await connection.close()


def run(body):
    try:
        return asyncio.run(_in_throwaway_schema(body))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


def test_load_is_idempotent_and_builds_are_byte_identical():
    async def body(connection, schema):
        first = await load(connection, DATA)
        again = await load(connection, DATA)
        assert first["claims"] == 2 and first["annotations"] == 3
        assert not any(again.values())  # a reload inserts nothing
        evidence = await db.describe(connection, schema)
        one = compile_graph(await snapshot(connection), {})
        two = compile_graph(await snapshot(connection), {})
        assert one == two and version(one) == version(two)
        stricter = compile_graph(await snapshot(connection), {"min_strength": 0.5})
        assert version(stricter) != version(one)
        assert await db.describe(connection, schema) == evidence  # building never writes evidence
        return one, stricter

    one, stricter = run(body)
    graph, strict = json.loads(one), json.loads(stricter)
    assert [e["claim_id"] for e in graph["edges"]] == ["cl:1", "cl:2"]
    assert [e["claim_id"] for e in strict["edges"]] == ["cl:1"]
    # The second annotator's rejection travels with the edge it disputes.
    history = graph["edges"][1]["review_history"]
    assert {h["action"] for h in history} == {"accept", "reject"}
    assert graph["edges"][0]["evidence"][0]["text"] == SPAN["text"]
    assert graph["edges"][0]["source_urls"] == ["https://example.test/a"]
    assert {n["id"]: n["search_status"] for n in graph["nodes"]}["ce:protest"] == "PARENTS_FOUND"
