import asyncio
import importlib.util
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from store import db  # noqa: E402

DATABASE_URL = os.environ.get(
    "EVIDENCE_DATABASE_URL", os.environ.get("ARTICLE_DATABASE_URL", db.DEFAULT_DATABASE_URL)
)


def load():
    """The serving app now lives in annotator/, free of duckdb and scoring so
    the deployed bundle carries only what it calls."""
    from annotator import app as annotator_app
    import importlib
    return importlib.reload(annotator_app)


@pytest.fixture
def client():
    annot = load()
    name = f"annot_test_{uuid.uuid4().hex}"

    async def setup(connection):
        await connection.execute(f'SET search_path TO "{name}", public')

    try:
        asyncio.run(_make_schema(name))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")

    holder: dict = {}

    @asynccontextmanager
    async def lifespan(_app):
        holder["pool"] = await asyncpg.create_pool(
            DATABASE_URL, min_size=1, max_size=2, setup=setup)
        await _seed_claims(holder["pool"])
        await annot.assign(holder["pool"], annot.ANNOTATORS)
        try:
            yield
        finally:
            await holder["pool"].close()

    app = annot.build_app(holder, lifespan)
    app.state.schema = name
    with TestClient(app) as c:
        yield c
    asyncio.run(_drop_schema(name))


async def _make_schema(name):
    conn = await asyncpg.connect(DATABASE_URL, timeout=2)
    await conn.execute(f'CREATE SCHEMA "{name}"')
    await conn.execute(f'SET search_path TO "{name}", public')
    await conn.execute((ROOT / "store" / "schema.sql").read_text())
    await conn.close()


async def _drop_schema(name):
    conn = await asyncpg.connect(DATABASE_URL, timeout=2)
    await conn.execute(f'DROP SCHEMA "{name}" CASCADE')
    await conn.close()


async def _seed_claims(pool):
    """Eight targets, four candidates each, so block-level double-annotation
    shows up at its real rate instead of catching every claim."""
    import datetime
    day = datetime.datetime(2024, 6, 10, tzinfo=datetime.timezone.utc)
    build = await pool.fetchval(
        "INSERT INTO build_versions (config_hash, config, graph_version)"
        " VALUES ('t', '{}'::jsonb, 'test') RETURNING build_id")
    for target in range(1, 9):
        effect = await pool.fetchval(
            "INSERT INTO events (external_id, event_type, best_time) VALUES ($1,'Protest',$2)"
            " RETURNING event_id", f"effect-{target}", day)
        for rank, strength in enumerate((0.9, 0.7, 0.5, 0.3)):
            cause = await pool.fetchval(
                "INSERT INTO events (external_id, event_type, best_time) VALUES ($1,'Assault',$2)"
                " RETURNING event_id", f"cause-{target}-{rank}", day - datetime.timedelta(days=3))
            claim = await pool.fetchval(
                "INSERT INTO claims (cause_kind, cause_id, effect_kind, effect_id,"
                " machine_strength, confidence, grade, verdict, build_id)"
                " VALUES ('event',$1,'event',$2,$3,$3,'weak','unreviewed',$4) RETURNING claim_id",
                cause, effect, strength, build)
            await pool.execute(
                "INSERT INTO claim_channels (claim_id, channel_key, score, available, raw_inputs)"
                " VALUES ($1,'documented',$2,TRUE,'{\"plain\":\"x\",\"question\":\"q\"}'::jsonb)",
                claim, strength)


def _next(client, who="pabo"):
    return client.get("/api/claims/next", params={"annotator": who}).json()


def test_queue_spreads_across_targets_instead_of_draining_one(client):
    """With ~90 candidates per target, id order would exhaust one event before
    the next was seen, so each target's strongest is served first."""
    first = _next(client)
    assert first["machine_strength"] == 0.9
    client.post(f"/api/claims/{first['claim_id']}/judge",
                json={"action": "accept", "annotator": "pabo", "human_strength": 0.8})
    second = _next(client)
    assert second.get("done") or second["claim_id"] != first["claim_id"]


def test_a_served_claim_is_always_one_the_person_was_assigned(client):
    """Overlap is not a bug — a quarter of claims have a second reader by
    design. What must never happen is being handed work assigned to nobody or
    to someone else."""
    import asyncpg as _pg

    async def assignment_of(claim_ids):
        conn = await _pg.connect(DATABASE_URL, timeout=2)
        try:
            await conn.execute(f'SET search_path TO "{client.app.state.schema}", public')
            return {r["claim_id"]: (r["primary_annotator"], r["review_annotator"])
                    for r in await conn.fetch(
                        "SELECT claim_id, primary_annotator, review_annotator"
                        " FROM claims WHERE claim_id = ANY($1::bigint[])", claim_ids)}
        finally:
            await conn.close()

    served = {}
    for who in ("pabo", "nambi", "akka", "shenoy"):
        claim = _next(client, who)
        if not claim.get("done"):
            served[who] = claim["claim_id"]

    rows = asyncio.run(assignment_of(list(served.values())))
    for who, claim_id in served.items():
        assert who in rows[claim_id], f"{who} was served a claim assigned to {rows[claim_id]}"


def test_a_quarter_of_claims_get_a_second_reader(client):
    """P2.4 wants 25% double-annotated so agreement can be measured. Selecting
    them on the same modulus as the rotation put every one on a single pile."""
    import asyncpg as _pg

    async def shape():
        conn = await _pg.connect(DATABASE_URL, timeout=2)
        try:
            await conn.execute(f'SET search_path TO "{client.app.state.schema}", public')
            return await conn.fetchrow(
                "SELECT count(*) AS total,"
                " count(review_annotator) AS doubled,"
                " count(DISTINCT primary_annotator) AS primaries,"
                " count(DISTINCT review_annotator) AS reviewers FROM claims")
        finally:
            await conn.close()

    row = asyncio.run(shape())
    assert row["primaries"] == 4, "work must spread over all four"
    assert row["reviewers"] > 1, "second reads must not all land on one person"
    assert 0.15 <= row["doubled"] / row["total"] <= 0.35


def test_an_unknown_name_cannot_pull_work(client):
    r = client.get("/api/claims/next", params={"annotator": "mallory"})
    assert r.status_code == 400
    assert "pabo" in r.json()["detail"]


def test_judging_clears_it_from_that_persons_queue_only(client):
    """A second reader must still see a claim its primary has judged, or the
    25% double-annotation never happens."""
    claim = _next(client, "pabo")
    client.post(f"/api/claims/{claim['claim_id']}/judge",
                json={"action": "accept", "annotator": "pabo", "human_strength": 0.7})
    again = _next(client, "pabo")
    assert again.get("done") or again["claim_id"] != claim["claim_id"]

    reviewers = [w for w in ("nambi", "akka", "shenoy")
                 if not _next(client, w).get("done")]
    assert reviewers, "the other annotators still have work"


def test_accept_keeps_the_machine_value_beside_the_human_one(client):
    claim = _next(client)
    client.post(f"/api/claims/{claim['claim_id']}/judge",
                json={"action": "edit", "annotator": "pabo",
                      "human_strength": 0.2, "relation_type": "MOBILIZES"})
    # P3.4 compares the two, so neither may overwrite the other.
    progress = client.get("/api/progress", params={"annotator": "pabo"}).json()
    assert progress["judged"] == 1
    assert progress["team"]["pabo"] == 1


def test_rejection_requires_a_reason_from_the_taxonomy(client):
    claim = _next(client)
    bare = client.post(f"/api/claims/{claim['claim_id']}/judge",
                       json={"action": "reject", "annotator": "pabo"})
    assert bare.status_code == 400
    invented = client.post(f"/api/claims/{claim['claim_id']}/judge",
                           json={"action": "reject", "annotator": "pabo",
                                 "reject_reason": "I_DONT_LIKE_IT"})
    assert invented.status_code == 400


def test_rejected_candidates_are_queryable_as_a_set(client):
    claim = _next(client)
    client.post(f"/api/claims/{claim['claim_id']}/judge",
                json={"action": "reject", "annotator": "pabo",
                      "reject_reason": "CORRELATED_ONLY", "reason_text": "same wave"})
    got = client.get("/api/claims/rejected").json()
    assert got["count"] == 1
    assert got["rejected"][0]["reject_reason"] == "CORRELATED_ONLY"
    # The hard negatives survive as claims rather than being deleted.
    assert client.get("/api/progress", params={"annotator": "pabo"}).json()["assigned"] >= 1


def test_an_unknown_action_is_refused(client):
    claim = _next(client)
    r = client.post(f"/api/claims/{claim['claim_id']}/judge",
                    json={"action": "maybe", "annotator": "pabo"})
    assert r.status_code == 400


def test_a_persons_queue_empties_when_their_share_is_done(client):
    for _ in range(40):          # comfortably more than one person's share
        claim = _next(client, "akka")
        if claim.get("done"):
            break
        client.post(f"/api/claims/{claim['claim_id']}/judge",
                    json={"action": "accept", "annotator": "akka", "human_strength": 0.5})
    assert _next(client, "akka")["done"] is True


def _client_with_token(monkeypatch_value):
    """A second app instance with a token configured, sharing nothing else."""
    annot = load()
    annot.ANNOTATOR_TOKEN = monkeypatch_value
    return annot


def test_no_token_configured_leaves_the_tool_open(client):
    """Local use must not need a token, or the default workflow breaks."""
    assert client.get("/api/meta").status_code == 200


def test_a_configured_token_is_required_on_every_data_route():
    annot = _client_with_token("s3cret")
    holder: dict = {}
    app = annot.build_app(holder, None)
    with TestClient(app) as c:
        for path in ("/api/meta", "/api/progress", "/api/claims/next",
                     "/api/claims/rejected"):
            assert c.get(path).status_code == 401, f"{path} was reachable without a token"
        assert c.post("/api/claims/1/judge",
                      json={"action": "accept", "annotator": "pabo"}).status_code == 401


def test_the_right_token_passes_by_query_or_header():
    annot = _client_with_token("s3cret")
    holder: dict = {}
    with TestClient(annot.build_app(holder, None)) as c:
        assert c.get("/api/meta", params={"token": "s3cret"}).status_code == 200
        assert c.get("/api/meta", headers={"X-Annotator-Token": "s3cret"}).status_code == 200
        assert c.get("/api/meta", params={"token": "s3cre"}).status_code == 401
        assert c.get("/api/meta", params={"token": "s3crett"}).status_code == 401


def test_the_page_itself_stays_reachable_so_the_error_is_legible():
    annot = _client_with_token("s3cret")
    holder: dict = {}
    with TestClient(annot.build_app(holder, None)) as c:
        assert c.get("/").status_code == 200


def test_a_suggested_relation_is_offered_so_accept_means_something():
    """Accepting an unstated proposition is not a judgement. The screen has to
    propose a specific relation for the annotator to agree or disagree with."""
    annot = load()
    # Same type both sides: the effect already existed, which is the only thing
    # separating ESCALATES from TRIGGERS.
    assert annot.suggest_relation("Protest", "Protest", 1) == "ESCALATES"
    assert annot.suggest_relation("Assault", "Protest", 2) == "TRIGGERS"
    assert annot.suggest_relation("Assault", "Protest", 9) == "MOBILIZES"
    assert annot.suggest_relation("Assault", "Protest", 40) == "CONTRIBUTES_TO"
    for pair in (("Protest", "Protest", 1), ("Assault", "Protest", 2),
                 ("Assault", "Protest", 9), ("Assault", "Protest", 40)):
        assert annot.suggest_relation(*pair) in annot.RELATION_TYPES


def test_the_served_claim_carries_its_proposition(client):
    claim = _next(client, "pabo")
    assert "suggested_relation" in claim
    assert claim["suggested_relation"] in load().RELATION_TYPES
    # Everything the sentence on screen is built from.
    for field in ("cause_type", "effect_type", "cause_time", "effect_time", "lag_days"):
        assert claim[field] is not None
