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


def load_fetch():
    fetch_path = ROOT / "pipeline" / "article_fetch.py"
    spec = importlib.util.spec_from_file_location("article_fetch", fetch_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retry_policy_and_content_classification():
    ingester = load_fetch()

    assert ingester.retry_delay(1) == 1
    assert ingester.retry_delay(4) == 8
    assert ingester.retry_delay(10) == 60
    assert ingester.is_retryable_status(429)
    assert ingester.is_retryable_status(503)
    assert not ingester.is_retryable_status(404)
    assert ingester.content_type_is_html("text/html", b"not html")
    assert ingester.content_type_is_html(None, b"<html></html>")
    assert not ingester.content_type_is_html("application/pdf", b"%PDF")


def test_raw_html_is_content_addressed_and_compressed(tmp_path):
    ingester = load_fetch()
    body = b"<html><body>article</body></html>"
    content_hash = "a" * 64

    stored_path = ingester.write_raw_html(tmp_path, body, content_hash)
    path = Path(stored_path)
    if not path.is_absolute():
        path = ROOT / path

    assert path == tmp_path / "aa" / (content_hash + ".html.gz")
    with gzip.open(path, "rb") as source:
        assert source.read() == body


def test_fetch_once_uses_one_get_and_extracts_html():
    ingester = load_fetch()
    html = """
    <html><body><article>
      <h1>Local article</h1>
      <p>This article contains enough text to exercise the dispatcher and its extraction path.</p>
      <p>The second paragraph gives the local fixture more than the minimum readable length.</p>
      <p>The stored result should retain the article body without requiring a separate
      liveness request.</p>
      <p>The response also keeps the article URL available to the extractor so metadata
      and publisher-specific parsing can use the final redirected location.</p>
    </article></body></html>
    """

    class FakeContent:
        async def read(self, limit):
            assert limit > len(html)
            return html.encode()

        async def iter_chunked(self, size):
            yield html.encode()

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        url = "https://example.test/final"
        charset = "utf-8"
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, allow_redirects, headers):
            self.calls += 1
            assert url == "https://example.test/article"
            assert allow_redirects is True
            assert "User-Agent" in headers
            return FakeResponse()

    session = FakeSession()
    job = ingester.Job(1, "https://example.test/article", "https://example.test/article", 1)
    result = asyncio.run(ingester.fetch_once(session, job, 1024 * 1024))

    assert session.calls == 1
    assert result.status == "extracted"
    assert result.final_url == "https://example.test/final"
    assert result.extraction is not None
    assert "local fixture" in result.extraction.text


def test_fetch_once_passes_final_url_to_extractor():
    ingester = load_fetch()
    calls = []
    original_extract_article = ingester.extract_article

    def fake_extract_article(body, url=None):
        calls.append((body, url))
        return ingester.ExtractionResult("extracted", "Fixture", "A readable article body.")

    ingester.extract_article = fake_extract_article

    class FakeContent:
        async def read(self, limit):
            return b"<html><body>fixture</body></html>"

        async def iter_chunked(self, size):
            yield b"<html><body>fixture</body></html>"

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "text/html"}
        url = "https://example.test/final"
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    class FakeSession:
        def get(self, url, allow_redirects, headers):
            return FakeResponse()

    try:
        job = ingester.Job(1, "https://example.test/article", "https://example.test/article", 1)
        result = asyncio.run(ingester.fetch_once(FakeSession(), job, 1024 * 1024))
    finally:
        ingester.extract_article = original_extract_article

    assert result.status == "extracted"
    assert calls == [(b"<html><body>fixture</body></html>", "https://example.test/final")]


async def exercise_host_fair_claim(fetch):
    schema_name = f"article_fairness_{uuid.uuid4().hex}"
    admin_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=2)
    await admin_pool.execute(f'CREATE SCHEMA "{schema_name}"')
    await admin_pool.close()

    async def set_search_path(connection):
        await connection.execute(f'SET search_path TO "{schema_name}", public')

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=1,
        timeout=2,
        setup=set_search_path,
    )
    urls = [f"https://fairness-a.test/article-{index}" for index in range(1, 6)]
    urls.append("https://fairness-b.test/article-1")
    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute("DELETE FROM article_documents WHERE url_key = ANY($1::text[])", urls)
        for url in urls:
            await pool.execute(
                "INSERT INTO article_documents (url_key, source_url) VALUES ($1, $2)",
                url,
                url,
            )

        first = await fetch.claim_next(pool, per_host_concurrency=2)
        second = await fetch.claim_next(pool, per_host_concurrency=2)
        third = await fetch.claim_next(pool, per_host_concurrency=2)

        assert first is not None
        assert second is not None
        assert third is not None
        assert first.source_url == urls[0]
        assert second.source_url == urls[1]
        assert third.source_url == urls[-1]
    finally:
        await pool.close()
        cleanup_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=1,
            timeout=2,
        )
        await cleanup_pool.execute(f'DROP SCHEMA "{schema_name}" CASCADE')
        await cleanup_pool.close()


def test_claim_next_skips_a_saturated_host():
    fetch = load_fetch()
    try:
        asyncio.run(exercise_host_fair_claim(fetch))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


async def exercise_recovery_claim(fetch):
    schema_name = f"article_recovery_{uuid.uuid4().hex}"
    admin_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=2)
    await admin_pool.execute(f'CREATE SCHEMA "{schema_name}"')
    await admin_pool.close()

    async def set_search_path(connection):
        await connection.execute(f'SET search_path TO "{schema_name}", public')

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=1,
        timeout=2,
        setup=set_search_path,
    )
    expired_url = "https://expired.test/article"
    retryable_url = "https://retryable.test/article"
    pending_url = "https://pending.test/article"
    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute(
            """
            INSERT INTO article_documents (
                url_key, source_url, status, attempt_count, lease_expires_at, next_attempt_at
            ) VALUES
                ($1, $1, 'fetching', 1, NOW() - INTERVAL '1 minute', NOW()),
                ($2, $2, 'retryable_error', 1, NULL, NOW() - INTERVAL '1 minute'),
                ($3, $3, 'pending', 0, NULL, NOW())
            """,
            expired_url,
            retryable_url,
            pending_url,
        )

        expired = await fetch.claim_next(pool, per_host_concurrency=2)
        retryable = await fetch.claim_next(pool, per_host_concurrency=2)
        pending = await fetch.claim_next(pool, per_host_concurrency=2)

        assert expired is not None
        assert expired.source_url == expired_url
        assert expired.attempt_count == 2
        assert retryable is not None
        assert retryable.source_url == retryable_url
        assert retryable.attempt_count == 2
        assert pending is not None
        assert pending.source_url == pending_url
        assert pending.attempt_count == 1
    finally:
        await pool.close()
        cleanup_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=1, timeout=2)
        await cleanup_pool.execute(f'DROP SCHEMA "{schema_name}" CASCADE')
        await cleanup_pool.close()


def test_claim_next_recovers_expired_and_retryable_rows_before_pending_rows():
    fetch = load_fetch()
    try:
        asyncio.run(exercise_recovery_claim(fetch))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


def _streaming_response(html: bytes, chunk_size: int = 512):
    """Model aiohttp's real StreamReader: read(n) returns only what is already
    buffered, not n bytes. Only iterating to EOF yields the whole body."""

    chunks = [html[i : i + chunk_size] for i in range(0, len(html), chunk_size)]

    class FakeContent:
        async def read(self, limit):
            # Real aiohttp returns the first buffered chunk, capped at limit.
            return chunks[0][:limit] if chunks else b""

        async def iter_chunked(self, size):
            for chunk in chunks:
                yield chunk

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}
        url = "https://example.test/final"
        charset = "utf-8"
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    class FakeSession:
        def get(self, url, allow_redirects, headers):
            return FakeResponse()

    return FakeSession()


def _long_article(marker: str) -> bytes:
    topics = [
        "The state assembly debated the revised procurement bill for several hours",
        "Farmers from three districts gathered outside the secretariat on Tuesday",
        "Officials said the compensation package would be reviewed in December",
        "Traffic was diverted around the main arterial road during the march",
        "A spokesperson declined to comment on the pending court application",
        "Local traders reported a sharp drop in footfall through the week",
        "The opposition demanded a written assurance before ending the protest",
        "Police estimated the crowd at close to four thousand participants",
        "Rail services resumed after a six hour disruption on the eastern line",
        "The committee will publish its findings early in the next session",
    ]
    body = "\n".join(
        f"<p>{line}, according to people familiar with the discussions. "
        f"The detail was confirmed separately by a second official. "
        f"No further statement has been issued so far.</p>"
        for line in topics
    )
    return (
        f"<html><body><article><h1>Streamed article</h1>{body}"
        f"<p>{marker} closes the article after many chunks of preceding text.</p>"
        "</article></body></html>"
    ).encode()


def test_fetch_reads_body_past_the_first_chunk():
    ingester = load_fetch()
    html = _long_article("FINALMARKER")
    assert len(html) > 512, "fixture must span multiple chunks"

    job = ingester.Job(1, "https://example.test/article", "https://example.test/article", 1)
    result = asyncio.run(ingester.fetch_once(_streaming_response(html), job, 1024 * 1024))

    assert result.body is not None
    assert result.body == html, "stored HTML must be the complete response, not the first chunk"
    assert b"</html>" in result.body
    assert result.status == "extracted"
    assert "FINALMARKER" in result.extraction.text


def test_fetch_still_rejects_oversized_bodies():
    ingester = load_fetch()
    html = _long_article("BIG")

    job = ingester.Job(1, "https://example.test/article", "https://example.test/article", 1)
    result = asyncio.run(ingester.fetch_once(_streaming_response(html), job, 600))

    assert result.status == "response_too_large"
