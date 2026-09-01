import asyncio
import gzip
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
DATABASE_URL = os.environ.get(
    "ARTICLE_DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5432/gdelt"
)


def load_reprocessor():
    script_path = ROOT / "pipeline" / "09_reprocess_articles.py"
    spec = importlib.util.spec_from_file_location("reprocess_articles", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_raw_html_resolves_relative_and_absolute_paths(tmp_path):
    reprocessor = load_reprocessor()
    body = b"<html><body><article>stored body</article></body></html>"
    raw_path = tmp_path / "aa" / "article.html.gz"
    raw_path.parent.mkdir()
    with gzip.open(raw_path, "wb") as output:
        output.write(body)

    assert reprocessor.read_raw_html(str(raw_path)) == body
    assert reprocessor.read_raw_html("aa/article.html.gz", tmp_path) == body


async def exercise_benchmark(reprocessor, tmp_path):
    schema_name = f"article_benchmark_{uuid.uuid4().hex}"
    admin_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=2)
    await admin_pool.execute(f'CREATE SCHEMA "{schema_name}"')
    await admin_pool.close()

    async def set_search_path(connection):
        await connection.execute(f'SET search_path TO "{schema_name}", public')

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=2,
        timeout=2,
        setup=set_search_path,
    )
    body = b"""
    <html><head><title>Benchmark article</title></head><body><article>
      <p>Residents gathered outside the district office after officials announced a policy change.
      Organizers requested a public meeting and asked the administration to publish the supporting
      documents before the next session.</p>
      <p>The administration said it would review the request and report back within two weeks.</p>
    </article></body></html>
    """
    raw_path = tmp_path / "benchmark.html.gz"
    with gzip.open(raw_path, "wb") as output:
        output.write(body)
    output_path = tmp_path / "benchmark.jsonl"
    url = "https://benchmark.test/article"
    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute(
            """
            INSERT INTO article_documents (
                url_key, source_url, status, title, cleaned_text, text_length, raw_html_path
            ) VALUES ($1, $2, 'insufficient_text', $3, $4, $5, $6)
            """,
            url,
            url,
            "Old title",
            "Old extracted text",
            18,
            str(raw_path),
        )
        summary = await reprocessor.benchmark(pool, tmp_path, output_path, 1)
        row = await pool.fetchrow(
            """
            SELECT status, title, cleaned_text, extractor_version
            FROM article_documents
            WHERE url_key = $1
            """,
            url,
        )
        record = output_path.read_text(encoding="utf-8").strip()
    finally:
        await pool.close()
        cleanup_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=2)
        await cleanup_pool.execute(f'DROP SCHEMA "{schema_name}" CASCADE')
        await cleanup_pool.close()

    return summary, row, record


def test_benchmark_does_not_modify_canonical_text(tmp_path):
    reprocessor = load_reprocessor()
    try:
        summary, row, record = asyncio.run(exercise_benchmark(reprocessor, tmp_path))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")

    assert summary["rows_written"] == 1
    assert row["status"] == "insufficient_text"
    assert row["title"] == "Old title"
    assert row["cleaned_text"] == "Old extracted text"
    assert row["extractor_version"] is None
    assert '"precision"' in record
    assert '"recall"' in record


async def exercise_promote(reprocessor, tmp_path):
    schema_name = f"article_promote_{uuid.uuid4().hex}"
    admin_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=2)
    await admin_pool.execute(f'CREATE SCHEMA "{schema_name}"')
    await admin_pool.close()

    async def set_search_path(connection):
        await connection.execute(f'SET search_path TO "{schema_name}", public')

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=2,
        timeout=2,
        setup=set_search_path,
    )
    body = b"""
    <html><head><title>Promoted article</title></head><body><article>
      <p>The council met residents after a demonstration and agreed to publish a review of the
      policy. Officials said the review would include a public timetable and named contacts for
      follow-up.</p>
      <p>Residents welcomed the commitment but requested that the next meeting be open to
      observers.</p>
      <p>The council also agreed to release meeting notes, name a contact for questions, and
      publish the next timetable so residents could verify the promised review.</p>
    </article></body></html>
    """
    raw_path = tmp_path / "promote.html.gz"
    with gzip.open(raw_path, "wb") as output:
        output.write(body)
    url = "https://promote.test/article"
    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute(
            """
            INSERT INTO article_documents (
                url_key, source_url, status, raw_html_path
            ) VALUES ($1, $2, 'insufficient_text', $3)
            """,
            url,
            url,
            str(raw_path),
        )
        first = await reprocessor.promote(pool, tmp_path, 1, 0)
        row = await pool.fetchrow(
            """
            SELECT status, title, cleaned_text, text_length, extractor_version
            FROM article_documents
            WHERE url_key = $1
            """,
            url,
        )
        second = await reprocessor.promote(pool, tmp_path, 1, 0)
    finally:
        await pool.close()
        cleanup_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=2)
        await cleanup_pool.execute(f'DROP SCHEMA "{schema_name}" CASCADE')
        await cleanup_pool.close()

    return first, row, second


def test_promote_updates_rows_and_is_checkpointed(tmp_path):
    reprocessor = load_reprocessor()
    try:
        first, row, second = asyncio.run(exercise_promote(reprocessor, tmp_path))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")

    assert first["processed"] == 1
    assert row["status"] == "extracted"
    assert row["title"] == "Promoted article"
    assert "council met residents" in row["cleaned_text"]
    assert row["text_length"] == len(row["cleaned_text"])
    assert row["extractor_version"] == reprocessor.EXTRACTOR_VERSION
    assert second["processed"] == 0
