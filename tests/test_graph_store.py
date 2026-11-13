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

from graph_store import compile_graph, load, representatives, snapshot, version  # noqa: E402

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
    by_claim = {tuple(e["claim_ids"]): e for e in graph["edges"]}
    assert set(by_claim) == {("cl:1",), ("cl:2",)}
    assert [e["claim_ids"] for e in strict["edges"]] == [["cl:1"]]
    # The second annotator's rejection travels with the edge it disputes.
    assert {h["action"] for h in by_claim[("cl:2",)]["review_history"]} == {"accept", "reject"}
    assert by_claim[("cl:1",)]["evidence"][0]["text"] == SPAN["text"]
    assert by_claim[("cl:1",)]["source_urls"] == ["https://example.test/a"]
    assert {n["id"]: n["search_status"] for n in graph["nodes"]}["ce:protest"] == "PARENTS_FOUND"


def test_judged_duplicates_merge_at_build_and_the_store_keeps_both_nodes():
    merges = [{"key": "ce:arrest|ce:rally", "a": "ce:arrest", "b": "ce:rally",
               "decision": "same", "why": "same arrest", "reviewer": "Claude (AI)",
               "label_source": "ai_assisted", "reviewed_at": "2026-11-01T00:00:00+00:00"}]

    async def body(connection, schema):
        await load(connection, {**DATA, "merges": merges})
        snap = await snapshot(connection)
        return (compile_graph(snap, {}), compile_graph(snap, {"merge_duplicates": False}),
                await connection.fetchval("SELECT count(*) FROM events"))

    merged, apart, events = run(body)
    graph = json.loads(merged)
    assert events == 3  # merging is an alias at build time; both nodes stay in the store
    # Both claims now join the same pair, so they fold into one edge with both claims.
    [edge] = graph["edges"]
    assert edge["source"] == "ce:arrest" and edge["claim_ids"] == ["cl:1", "cl:2"]
    assert edge["strength"] == 1.0  # the strongest claim leads
    node = {n["id"]: n for n in graph["nodes"]}["ce:arrest"]
    assert node["merged_from"] == ["ce:rally"]
    assert graph["counts"]["nodes_merged_away"] == 1
    assert len(json.loads(apart)["edges"]) == 2


def test_a_newer_merge_decision_supersedes_an_older_one():
    same = {"key": "ce:arrest|ce:rally", "a": "ce:arrest", "b": "ce:rally", "decision": "same",
            "why": "same", "reviewer": "Claude (AI)", "label_source": "ai_assisted",
            "reviewed_at": "2026-11-01T00:00:00+00:00"}
    undo = {**same, "key": "ce:arrest|ce:rally#2", "decision": "different",
            "reviewed_at": "2026-11-01T12:00:00+00:00"}

    async def body(connection, schema):
        await load(connection, {**DATA, "merges": [same, undo]})
        return compile_graph(await snapshot(connection), {}), await connection.fetchval(
            "SELECT count(*) FROM node_merges")

    graph, rows = run(body)
    assert rows == 2  # both decisions stay: the store is append-only
    assert len(json.loads(graph)["edges"]) == 2  # the later "different" wins


def test_a_human_verdict_outranks_the_ai_and_is_marked_on_the_edge():
    review = [
        {"claim_id": "cl:1", "verdict": "accept", "reason": None, "relation": None, "note": None,
         "reviewed_at": "2026-11-01T12:00:00Z", "reviewer_id": "human:owner",
         "label_source": "human"},
        {"claim_id": "cl:2", "verdict": "reject", "reason": None, "relation": None, "note": None,
         "reviewed_at": "2026-11-01T12:00:00Z", "reviewer_id": "human:owner",
         "label_source": "human"},
    ]

    async def body(connection, schema):
        await load(connection, {**DATA, "human_review": review})
        snap = await snapshot(connection)
        return compile_graph(snap, {}), compile_graph(snap, {"require_human": True})

    graph, strict = (json.loads(g) for g in run(body))
    # The AI accepted both claims; the person rejected cl:2, so only cl:1 remains.
    assert [e["claim_ids"] for e in graph["edges"]] == [["cl:1"]]
    assert graph["edges"][0]["human_verified"] is True
    assert graph["counts"]["human_rejected_claims"] == 1
    assert strict["counts"]["edges"] == 1


def test_a_blind_rejection_drops_an_ai_edge_unless_a_person_accepted_it():
    blind = [edge("cl:1", "REJECTED", role="blind", reason="OTHER"),
             edge("cl:2", "REJECTED", role="blind", reason="OTHER")]
    review = [{"claim_id": "cl:1", "verdict": "accept", "reason": None, "relation": None,
               "note": None, "reviewed_at": "2026-11-01T12:00:00Z",
               "reviewer_id": "human:owner", "label_source": "human"}]

    async def body(connection, schema):
        await load(connection, {**DATA, "edges": DATA["edges"] + blind, "human_review": review})
        return compile_graph(await snapshot(connection), {})

    graph = json.loads(run(body))
    # cl:2 had only the first AI accept; the blind judge rejected it, nobody overrode.
    assert [e["claim_ids"] for e in graph["edges"]] == [["cl:1"]]


def test_a_merge_chain_never_joins_what_a_person_kept_apart():
    # call ~ campaign ~ march are judged "same" pairwise, but a person accepted call -> march.
    nodes = {n: {"kind": "event"} for n in ("ce:call", "ce:campaign", "ce:march", "ce:other")}
    blocked = []
    alias = representatives([("ce:call", "ce:campaign"), ("ce:campaign", "ce:march"),
                             ("ce:march", "ce:other")], nodes, [("ce:call", "ce:march")], blocked)
    root = {n: alias.get(n, n) for n in nodes}
    assert root["ce:call"] != root["ce:march"]
    assert root["ce:march"] == root["ce:other"]
    assert blocked == [["ce:campaign", "ce:march"]]
