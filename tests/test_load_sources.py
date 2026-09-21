import asyncio
import datetime
import importlib.util
import os
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

from store import db  # noqa: E402

DATABASE_URL = os.environ.get(
    "EVIDENCE_DATABASE_URL", os.environ.get("ARTICLE_DATABASE_URL", db.DEFAULT_DATABASE_URL)
)
DAY = datetime.date(2024, 6, 10)


def load_loader():
    path = ROOT / "pipeline" / "13_load_sources.py"
    spec = importlib.util.spec_from_file_location("load_sources", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_date_near_the_event_day_is_kept():
    loader = load_loader()
    for offset in (0, -7, 29, -29):
        date = DAY + datetime.timedelta(days=offset)
        assert loader.validated_publication_date(date, DAY, 30) == (date, None)


def test_date_far_from_the_event_day_is_dropped():
    loader = load_loader()
    # The crawl-date failure: a 2024 story stamped 2026.
    crawl = datetime.date(2026, 9, 19)
    assert loader.validated_publication_date(crawl, DAY, 30) == (None, "outside_event_window")
    stale = datetime.date(2011, 6, 4)
    assert loader.validated_publication_date(stale, DAY, 30) == (None, "outside_event_window")


def test_without_an_event_day_there_is_no_basis_to_reject():
    loader = load_loader()
    date = datetime.date(2026, 9, 19)
    assert loader.validated_publication_date(date, None, 30) == (date, None)


def test_a_missing_date_stays_missing():
    loader = load_loader()
    assert loader.validated_publication_date(None, DAY, 30) == (None, None)


async def _exercise(body):
    name = f"load_sources_test_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(DATABASE_URL, timeout=2)
    await admin.execute(f'CREATE SCHEMA "{name}"')
    await admin.close()

    async def setup(connection):
        await connection.execute(f'SET search_path TO "{name}", public')

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, timeout=2, setup=setup)
    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute((ROOT / "store" / "schema.sql").read_text())
        return await body(pool)
    finally:
        await pool.close()
        admin = await asyncpg.connect(DATABASE_URL, timeout=2)
        await admin.execute(f'DROP SCHEMA "{name}" CASCADE')
        await admin.close()


def run(body):
    try:
        return asyncio.run(_exercise(body))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


async def _seed_articles(pool):
    rows = [
        ("https://a.test/1", datetime.date(2024, 6, 11)),   # near the event day
        ("https://b.test/2", datetime.date(2026, 9, 19)),   # crawl date
        ("https://c.test/3", None),                          # undated
    ]
    for url, published in rows:
        await pool.execute(
            "INSERT INTO article_documents (url_key, source_url, status, published_at,"
            " content_hash, raw_html_path) VALUES ($1, $1, 'extracted', $2, 'h', 'p')",
            url, published)
    # not extracted — must not be loaded
    await pool.execute(
        "INSERT INTO article_documents (url_key, source_url, status) "
        "VALUES ('https://d.test/4', 'https://d.test/4', 'blocked')")


def test_loads_only_extracted_rows_and_validates_dates():
    loader = load_loader()
    days = {"https://a.test/1": DAY, "https://b.test/2": DAY, "https://c.test/3": DAY}

    async def body(pool):
        await _seed_articles(pool)
        counts = await loader.load(pool, days, 30, 0)
        stored = await pool.fetch("SELECT url_key, published_at FROM sources ORDER BY url_key")
        return counts, {r["url_key"]: r["published_at"] for r in stored}

    counts, stored = run(body)

    assert counts["inserted"] == 3, "the blocked row must not become evidence"
    assert set(stored) == {"https://a.test/1", "https://b.test/2", "https://c.test/3"}
    assert stored["https://a.test/1"] == datetime.date(2024, 6, 11)
    assert stored["https://b.test/2"] is None, "crawl date should have been rejected"
    assert stored["https://c.test/3"] is None
    assert counts["date_rejected"] == 1


def test_reloading_inserts_nothing_new():
    loader = load_loader()
    days = {"https://a.test/1": DAY, "https://b.test/2": DAY, "https://c.test/3": DAY}

    async def body(pool):
        await _seed_articles(pool)
        first = await loader.load(pool, days, 30, 0)
        second = await loader.load(pool, days, 30, 0)
        total = await pool.fetchval("SELECT count(*) FROM sources")
        return first, second, total

    first, second, total = run(body)

    assert first["inserted"] == 3
    assert second["inserted"] == 0, "append-only load must be idempotent"
    assert second["already_present"] == 3
    assert total == 3


def test_a_changed_row_supersedes_rather_than_updating():
    loader = load_loader()
    days = {"https://a.test/1": DAY}

    async def body(pool):
        await pool.execute(
            "INSERT INTO article_documents (url_key, source_url, status, content_hash) "
            "VALUES ('https://a.test/1', 'https://a.test/1', 'extracted', 'hash-one')")
        first = await loader.load(pool, days, 30, 0)

        # What the date backfill does: the article row gains a publication date.
        await pool.execute(
            "UPDATE article_documents SET published_at = $1 WHERE url_key = 'https://a.test/1'",
            datetime.date(2024, 6, 11))
        second = await loader.load(pool, days, 30, 0)

        rows = await pool.fetch(
            "SELECT source_id, published_at FROM sources ORDER BY source_id")
        current = await pool.fetchrow(
            "SELECT published_at FROM current_sources WHERE url_key = 'https://a.test/1'")
        return first, second, rows, current

    first, second, rows, current = run(body)

    assert first["inserted"] == 1
    assert second["inserted"] == 1 and second["superseded"] == 1
    assert len(rows) == 2, "the original row must survive; history is the point"
    assert rows[0]["published_at"] is None
    assert current["published_at"] == datetime.date(2024, 6, 11)


def test_an_unchanged_reload_supersedes_nothing():
    loader = load_loader()
    days = {"https://a.test/1": DAY}

    async def body(pool):
        await pool.execute(
            "INSERT INTO article_documents (url_key, source_url, status) "
            "VALUES ('https://a.test/1', 'https://a.test/1', 'extracted')")
        await loader.load(pool, days, 30, 0)
        second = await loader.load(pool, days, 30, 0)
        return second, await pool.fetchval("SELECT count(*) FROM sources")

    second, total = run(body)
    assert second["inserted"] == 0 and second["already_present"] == 1
    assert total == 1
