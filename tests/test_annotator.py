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
    path = ROOT / "pipeline" / "14_run_annotator.py"
    spec = importlib.util.spec_from_file_location("run_annotator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        try:
            yield
        finally:
            await holder["pool"].close()

    with TestClient(annot.build_app(holder, lifespan)) as c:
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
    """Two targets, two candidates each, with different machine strengths."""
    import datetime
    day = datetime.datetime(2024, 6, 10, tzinfo=datetime.timezone.utc)
    build = await pool.fetchval(
        "INSERT INTO build_versions (config_hash, config, graph_version)"
        " VALUES ('t', '{}'::jsonb, 'test') RETURNING build_id")
    for target in (1, 2):
        effect = await pool.fetchval(
            "INSERT INTO events (external_id, event_type, best_time) VALUES ($1,'Protest',$2)"
            " RETURNING event_id", f"effect-{target}", day)
        for rank, strength in enumerate((0.9, 0.3)):
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


def test_queue_spreads_across_targets_instead_of_draining_one(client):
    """80-odd candidates per target would exhaust one event before the next is
    seen, so the queue serves each target's strongest first."""
    first = client.get("/api/claims/next").json()
    assert first["machine_strength"] == 0.9
    client.post(f"/api/claims/{first['claim_id']}/judge",
                json={"action": "accept", "annotator": "ada", "human_strength": 0.8})

    second = client.get("/api/claims/next").json()
    assert second["machine_strength"] == 0.9, "the other target's best, not this target's weak one"
    assert second["claim_id"] != first["claim_id"]


def test_accept_keeps_the_machine_value_beside_the_human_one(client):
    claim = client.get("/api/claims/next").json()
    client.post(f"/api/claims/{claim['claim_id']}/judge",
                json={"action": "edit", "annotator": "ada",
                      "human_strength": 0.2, "relation_type": "MOBILIZES"})
    # P3.4 measures calibration by comparing them, so neither may overwrite the other.
    rows = client.get("/api/claims/rejected").json()
    assert rows["count"] == 0
    progress = client.get("/api/progress").json()
    assert progress["accepted"] == 1


def test_rejection_requires_a_reason_from_the_taxonomy(client):
    claim = client.get("/api/claims/next").json()
    bare = client.post(f"/api/claims/{claim['claim_id']}/judge",
                       json={"action": "reject", "annotator": "ada"})
    assert bare.status_code == 400

    invented = client.post(f"/api/claims/{claim['claim_id']}/judge",
                           json={"action": "reject", "annotator": "ada",
                                 "reject_reason": "I_DONT_LIKE_IT"})
    assert invented.status_code == 400


def test_rejected_candidates_are_queryable_as_a_set(client):
    claim = client.get("/api/claims/next").json()
    client.post(f"/api/claims/{claim['claim_id']}/judge",
                json={"action": "reject", "annotator": "ada",
                      "reject_reason": "CORRELATED_ONLY", "reason_text": "same wave"})
    got = client.get("/api/claims/rejected").json()
    assert got["count"] == 1
    assert got["rejected"][0]["reject_reason"] == "CORRELATED_ONLY"
    assert got["rejected"][0]["reason_text"] == "same wave"
    # The hard negatives must survive as claims, not be deleted.
    assert client.get("/api/progress").json()["total"] == 4


def test_an_unknown_action_is_refused(client):
    claim = client.get("/api/claims/next").json()
    r = client.post(f"/api/claims/{claim['claim_id']}/judge",
                    json={"action": "maybe", "annotator": "ada"})
    assert r.status_code == 400


def test_the_queue_reports_done_when_everything_is_judged(client):
    for _ in range(4):
        claim = client.get("/api/claims/next").json()
        assert not claim.get("done")
        client.post(f"/api/claims/{claim['claim_id']}/judge",
                    json={"action": "accept", "annotator": "ada", "human_strength": 0.5})
    assert client.get("/api/claims/next").json()["done"] is True
