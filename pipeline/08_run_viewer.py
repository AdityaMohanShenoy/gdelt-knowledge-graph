import argparse
import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from article_fetch import ingest_targeted
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from url_utils import normalize_url

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5432/gdelt"
)
EVENTS_PATH = ROOT / "data" / "working" / "india-2024" / "annotation_units.json"
FRONTEND_PATH = ROOT / "frontend" / "viewer.html"
RAW_ARTICLE_DIR = ROOT / "data" / "evidence" / "articles" / "raw"


class ArticleFetchRequest(BaseModel):
    url: str


async def article_row(pool: asyncpg.Pool, url_key: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT document_id, url_key, source_url, final_url, status,
               attempt_count, http_status, content_type, title,
               cleaned_text, text_length, extraction_reason, last_error,
               fetched_at
        FROM article_documents
        WHERE url_key = $1
        """,
        url_key,
    )


def article_payload(row: asyncpg.Record) -> dict[str, object]:
    return {
        "found": True,
        "document_id": row["document_id"],
        "url_key": row["url_key"],
        "source_url": row["source_url"],
        "final_url": row["final_url"],
        "status": row["status"],
        "attempt_count": row["attempt_count"],
        "http_status": row["http_status"],
        "content_type": row["content_type"],
        "title": row["title"],
        "cleaned_text": row["cleaned_text"],
        "text_length": row["text_length"],
        "extraction_reason": row["extraction_reason"],
        "last_error": row["last_error"],
        "fetched_at": row["fetched_at"],
    }


async def targeted_worker(app: FastAPI, url_key: str) -> None:
    try:
        await ingest_targeted(app.state.pool, url_key, RAW_ARTICLE_DIR)
    except Exception as error:
        await app.state.pool.execute(
            """
            UPDATE article_documents
            SET status = 'retryable_error',
                last_error = $2,
                lease_expires_at = NULL,
                next_attempt_at = NOW() + INTERVAL '2 seconds'
            WHERE url_key = $1 AND status = 'fetching'
            """,
            url_key,
            type(error).__name__,
        )
    finally:
        task = app.state.targeted_tasks.get(url_key)
        if task is asyncio.current_task():
            app.state.targeted_tasks.pop(url_key, None)


def start_targeted_worker(app: FastAPI, url_key: str) -> None:
    task = app.state.targeted_tasks.get(url_key)
    if task is None or task.done():
        app.state.targeted_tasks[url_key] = asyncio.create_task(targeted_worker(app, url_key))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.pool = await asyncpg.create_pool(
        app.state.database_url,
        min_size=1,
        max_size=5,
    )
    try:
        yield
    finally:
        tasks = list(app.state.targeted_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await app.state.pool.close()


def create_app(database_url: str = DEFAULT_DATABASE_URL) -> FastAPI:
    app = FastAPI(title="GDELT article viewer", lifespan=lifespan)
    app.state.database_url = database_url
    app.state.targeted_tasks = {}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_PATH)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        await app.state.pool.fetchval("SELECT 1")
        return {"status": "ok"}

    @app.get("/data/working/india-2024/annotation_units.json")
    async def annotation_units() -> FileResponse:
        return FileResponse(EVENTS_PATH, media_type="application/json")

    @app.get("/api/articles/by-url")
    async def article_by_url(
        url: str = Query(min_length=1),
    ) -> dict[str, object]:
        url_key = normalize_url(url)
        if not url_key:
            raise HTTPException(status_code=400, detail="URL must be an HTTP or HTTPS URL")
        row = await article_row(app.state.pool, url_key)
        if row is None:
            return {
                "found": False,
                "url_key": url_key,
                "status": "not_queued",
            }
        return article_payload(row)

    @app.post("/api/articles/fetch")
    async def fetch_article(request: ArticleFetchRequest) -> dict[str, object]:
        url_key = normalize_url(request.url)
        if not url_key:
            raise HTTPException(status_code=400, detail="URL must be an HTTP or HTTPS URL")
        await app.state.pool.execute(
            """
            INSERT INTO article_documents (url_key, source_url)
            VALUES ($1, $2)
            ON CONFLICT (url_key) DO NOTHING
            """,
            url_key,
            request.url.strip(),
        )
        await app.state.pool.execute(
            """
            UPDATE article_documents
            SET status = 'pending',
                next_attempt_at = NOW(),
                lease_expires_at = NULL,
                last_error = NULL
            WHERE url_key = $1 AND status IN ('pending', 'retryable_error')
            """,
            url_key,
        )
        row = await article_row(app.state.pool, url_key)
        if row is None:
            raise HTTPException(status_code=500, detail="Article queue row was not created")
        if row["status"] in {"pending", "retryable_error", "fetching"}:
            start_targeted_worker(app, url_key)
        return article_payload(row)

    return app


app = create_app()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> None:
    import uvicorn

    args = parse_args()
    uvicorn.run(create_app(args.database_url), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
