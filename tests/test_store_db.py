import asyncio
import os
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from store import db  # noqa: E402

DATABASE_URL = os.environ.get(
    "EVIDENCE_DATABASE_URL",
    os.environ.get("ARTICLE_DATABASE_URL", db.DEFAULT_DATABASE_URL),
)


async def _in_throwaway_schema(body):
    """Each run gets its own schema, so the real evidence store is untouched."""
    name = f"evidence_test_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(DATABASE_URL, timeout=2)
    await admin.execute(f'CREATE SCHEMA "{name}"')
    await admin.close()

    connection = await asyncpg.connect(DATABASE_URL, timeout=2)
    try:
        await connection.execute(f'SET search_path TO "{name}", public')
        return await body(connection)
    finally:
        await connection.execute(f'DROP SCHEMA "{name}" CASCADE')
        await connection.close()


def run(body):
    try:
        return asyncio.run(_in_throwaway_schema(body))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


async def _seed(connection):
    """One row per table, threaded through the real foreign keys."""
    source_id = await connection.fetchval(
        "INSERT INTO sources (url, url_key, fetch_status) VALUES ($1, $1, 'extracted')"
        " RETURNING source_id", "https://example.test/a")
    entity_id = await connection.fetchval(
        "INSERT INTO entities (kind, canonical_name) VALUES ('actor', 'FARMERS')"
        " RETURNING entity_id")
    event_id = await connection.fetchval(
        "INSERT INTO events (event_type, best_time, time_confidence) "
        "VALUES ('PROTEST', NOW(), 0.8) RETURNING event_id")
    mention_id = await connection.fetchval(
        "INSERT INTO mentions (source_id, event_id, evidence_start, evidence_end) "
        "VALUES ($1, $2, 10, 90) RETURNING mention_id", source_id, event_id)
    condition_id = await connection.fetchval(
        "INSERT INTO conditions (description) VALUES ('declining farm-gate prices')"
        " RETURNING condition_id")
    build_id = await connection.fetchval(
        "INSERT INTO build_versions (config_hash, config, graph_version) "
        "VALUES ('abc123', '{}'::jsonb, 'v1') RETURNING build_id")
    claim_id = await connection.fetchval(
        "INSERT INTO claims (cause_kind, cause_id, effect_kind, effect_id, verdict, build_id) "
        "VALUES ('condition', $1, 'event', $2, 'unreviewed', $3) RETURNING claim_id",
        condition_id, event_id, build_id)
    channel_id = await connection.fetchval(
        "INSERT INTO claim_channels (claim_id, channel_key, score, available) "
        "VALUES ($1, 'documented', 0.9, TRUE) RETURNING claim_channel_id", claim_id)
    annotation_id = await connection.fetchval(
        "INSERT INTO annotations (claim_id, annotator, action, machine_strength, human_strength) "
        "VALUES ($1, 'ana', 'accept', 0.7, 0.9) RETURNING annotation_id", claim_id)
    return {
        "source_id": source_id, "entity_id": entity_id, "event_id": event_id,
        "mention_id": mention_id, "condition_id": condition_id, "build_id": build_id,
        "claim_id": claim_id, "claim_channel_id": channel_id, "annotation_id": annotation_id,
    }


def test_init_is_idempotent_and_every_table_round_trips():
    async def body(connection):
        await db.init(connection)
        await db.init(connection)          # the acceptance criterion: twice is safe
        ids = await _seed(connection)
        counts = await db.describe(connection)
        return ids, counts

    ids, counts = run(body)

    assert all(v is not None for v in ids.values())
    for table in db.TABLES:
        assert counts[table] == 1, f"{table} did not round-trip one row"


def test_evidence_tables_reject_update_and_delete():
    async def body(connection):
        await db.init(connection)
        await _seed(connection)
        refused = {}
        for table in db.APPEND_ONLY:
            for statement in (f"UPDATE {table} SET created_at = NOW()", f"DELETE FROM {table}"):
                try:
                    await connection.execute(statement)
                    refused[(table, statement.split()[0])] = None
                except asyncpg.PostgresError as error:
                    refused[(table, statement.split()[0])] = str(error)
        return refused

    refused = run(body)

    for (table, op), message in refused.items():
        assert message is not None, f"{table} allowed {op} — append-only not enforced"
        assert "append-only" in message


def test_mutable_tables_still_accept_updates():
    async def body(connection):
        await db.init(connection)
        ids = await _seed(connection)
        # claims carry a verdict that changes as review proceeds; only the
        # evidence tables are frozen.
        await connection.execute(
            "UPDATE claims SET verdict = 'accepted' WHERE claim_id = $1", ids["claim_id"])
        return await connection.fetchval(
            "SELECT verdict FROM claims WHERE claim_id = $1", ids["claim_id"])

    assert run(body) == "accepted"


def test_rejected_claims_are_retained_as_hard_negatives():
    async def body(connection):
        await db.init(connection)
        ids = await _seed(connection)
        await connection.execute(
            "UPDATE claims SET verdict = 'rejected' WHERE claim_id = $1", ids["claim_id"])
        await connection.execute(
            "INSERT INTO annotations (claim_id, annotator, action, reject_reason) "
            "VALUES ($1, 'ana', 'reject', 'CORRELATED_ONLY')", ids["claim_id"])
        return await connection.fetchval(
            "SELECT count(*) FROM claims WHERE verdict = 'rejected'")

    assert run(body) == 1, "rejected candidates must survive; they are the hard negatives"


def test_reject_without_a_reason_is_refused():
    async def body(connection):
        await db.init(connection)
        ids = await _seed(connection)
        try:
            await connection.execute(
                "INSERT INTO annotations (claim_id, annotator, action) "
                "VALUES ($1, 'ana', 'reject')", ids["claim_id"])
            return None
        except asyncpg.PostgresError as error:
            return str(error)

    assert run(body) is not None, "P2.3 requires a reason on every rejection"
