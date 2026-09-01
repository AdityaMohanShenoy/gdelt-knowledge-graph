import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import asyncpg
import httpx
import pytest
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
SCRIPT_PATH = ROOT / "pipeline" / "08_run_viewer.py"
DATABASE_URL = os.environ.get(
    "ARTICLE_DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5432/gdelt"
)


def load_api():
    spec = importlib.util.spec_from_file_location("run_viewer", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def exercise_api(api):
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, timeout=2)
    url = "https://Example.test/api-article#top"
    url_key = api.normalize_url(url)
    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute("DELETE FROM article_documents WHERE url_key = $1", url_key)
        await pool.execute(
            """
            INSERT INTO article_documents (
                url_key, source_url, final_url, status, attempt_count,
                http_status, content_type, title, cleaned_text, text_length,
                extraction_reason
            ) VALUES ($1, $2, $3, 'extracted', 1, 200, 'text/html', $4, $5, $6, $7)
            """,
            url_key,
            url,
            "https://example.test/api-article",
            "API fixture",
            "Cleaned article text from Postgres.",
            34,
            "article-body",
        )
        app = api.create_app(DATABASE_URL)
        app.state.pool = pool
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/articles/by-url",
                params={"url": "https://example.test/api-article#section"},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["found"] is True
        assert payload["status"] == "extracted"
        assert payload["cleaned_text"] == "Cleaned article text from Postgres."
    finally:
        await pool.execute("DELETE FROM article_documents WHERE url_key = $1", url_key)
        await pool.close()


def test_article_api_returns_cleaned_text_from_postgres():
    api = load_api()
    try:
        asyncio.run(exercise_api(api))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


async def exercise_targeted_fetch(api):
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, timeout=2)
    url = "https://Example.test/targeted-api#top"
    url_key = api.normalize_url(url)
    original_ingest_targeted = api.ingest_targeted
    calls = []

    async def fake_ingest_targeted(pool_arg, url_key_arg, raw_dir):
        calls.append((pool_arg, url_key_arg, raw_dir))

    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute("DELETE FROM article_documents WHERE url_key = $1", url_key)
        api.ingest_targeted = fake_ingest_targeted
        app = api.create_app(DATABASE_URL)
        app.state.pool = pool
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/articles/fetch", json={"url": url})
        await asyncio.sleep(0)

        assert response.status_code == 200
        payload = response.json()
        assert payload["found"] is True
        assert payload["url_key"] == url_key
        assert payload["status"] == "pending"
        assert len(calls) == 1
        assert calls[0][0] is pool
        assert calls[0][1] == url_key
        assert calls[0][2] == api.RAW_ARTICLE_DIR
    finally:
        api.ingest_targeted = original_ingest_targeted
        await pool.execute("DELETE FROM article_documents WHERE url_key = $1", url_key)
        await pool.close()


def test_article_api_enqueues_and_dispatches_targeted_fetch():
    api = load_api()
    try:
        asyncio.run(exercise_targeted_fetch(api))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


async def exercise_targeted_fetch_end_to_end(api, raw_dir):
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2, timeout=2)
    server = web.Application()
    article_html = """
    <html><body><article>
      <h1>Targeted integration article</h1>
      <p>This local article verifies that the selected URL can be fetched and stored
      without waiting for the bulk queue.</p>
      <p>The real targeted worker should extract this readable body, persist its metadata,
      and make it visible through the viewer API.</p>
      <p>The raw response should also be written to the configured content-addressed
      evidence directory.</p>
      <p>The stored article is intentionally long enough to pass the precision gate while
      still exercising the same single-request targeted path used by the local viewer.</p>
    </article></body></html>
    """

    async def article_handler(request):
        return web.Response(text=article_html, content_type="text/html")

    server.router.add_get("/article", article_handler)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets if site._server else None
    assert sockets
    port = sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/article#section"
    url_key = api.normalize_url(url)
    app = api.create_app(DATABASE_URL)
    app.state.pool = pool
    original_raw_dir = api.RAW_ARTICLE_DIR
    api.RAW_ARTICLE_DIR = raw_dir
    task = None
    try:
        await pool.execute((ROOT / "pipeline" / "article_schema.sql").read_text())
        await pool.execute("DELETE FROM article_documents WHERE url_key = $1", url_key)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/articles/fetch", json={"url": url})
            assert response.status_code == 200
            assert response.json()["status"] in {"pending", "fetching", "extracted"}
            payload = response.json()
            for _ in range(100):
                if payload["status"] == "extracted":
                    break
                await asyncio.sleep(0.05)
                response = await client.get(
                    "/api/articles/by-url",
                    params={"url": url},
                )
                assert response.status_code == 200
                payload = response.json()

        assert payload["status"] == "extracted"
        assert payload["title"] == "Targeted integration article"
        assert "selected URL can be fetched" in payload["cleaned_text"]
        assert payload["attempt_count"] == 1
        row = await pool.fetchrow(
            """
            SELECT content_hash, raw_html_path
            FROM article_documents
            WHERE url_key = $1
            """,
            url_key,
        )
        assert row is not None
        assert row["content_hash"]
        assert Path(row["raw_html_path"]).exists()
    finally:
        api.RAW_ARTICLE_DIR = original_raw_dir
        task = app.state.targeted_tasks.get(url_key)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await pool.execute("DELETE FROM article_documents WHERE url_key = $1", url_key)
        await pool.close()
        await runner.cleanup()


def test_article_api_fetches_selected_url_and_stores_text(tmp_path):
    api = load_api()
    try:
        asyncio.run(exercise_targeted_fetch_end_to_end(api, tmp_path))
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")
