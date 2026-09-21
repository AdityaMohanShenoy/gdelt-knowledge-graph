import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import aiohttp
import asyncpg
import pyarrow.parquet as parquet
from article_fetch import (
    CONCURRENCY,
    MAX_RESPONSE_BYTES,
    MAX_RETRIES,
    HOST_DELAY_SECONDS,
    HostThrottle,
    PER_HOST_CONCURRENCY,
    host_of,
    TIMEOUT_SECONDS,
    claim_next,
    fetch_once,
    save_result,
    write_raw_html,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5432/gdelt"
)
DEFAULT_QUEUE_PATH = ROOT / "data" / "working" / "india-2024" / "article_urls.parquet"
DEFAULT_RAW_DIR = ROOT / "data" / "evidence" / "articles" / "raw"
DB_POOL_SIZE = 20


async def ensure_schema(pool: asyncpg.Pool) -> None:
    schema_path = ROOT / "pipeline" / "article_schema.sql"
    schema = schema_path.read_text()
    async with pool.acquire() as connection:
        await connection.execute(schema)


async def load_queue(pool: asyncpg.Pool, queue_path: Path) -> int:
    inserted = 0
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "CREATE TEMP TABLE article_url_stage (url_key TEXT, source_url TEXT) ON COMMIT DROP"
            )
            parquet_file = parquet.ParquetFile(queue_path)
            for batch in parquet_file.iter_batches(
                batch_size=10_000,
                columns=["url_key", "source_url"],
            ):
                records = list(
                    zip(
                        batch.column("url_key").to_pylist(),
                        batch.column("source_url").to_pylist(),
                        strict=True,
                    )
                )
                await connection.copy_records_to_table(
                    "article_url_stage",
                    records=records,
                    columns=["url_key", "source_url"],
                )
            result = await connection.execute(
                """
                INSERT INTO article_documents (url_key, source_url)
                SELECT url_key, source_url
                FROM article_url_stage
                ON CONFLICT (url_key) DO NOTHING
                """
            )
            inserted = int(result.rsplit(" ", 1)[-1])
    return inserted


async def worker(
    worker_id: int,
    pool: asyncpg.Pool,
    session: aiohttp.ClientSession,
    raw_dir: Path,
    max_response_bytes: int,
    per_host_concurrency: int,
    max_attempts: int,
    max_article_date: str | None,
    claim_limit: int,
    claim_state: dict[str, int],
    claim_lock: asyncio.Lock,
    progress_state: dict[str, int],
    progress_lock: asyncio.Lock,
    throttle: HostThrottle,
) -> None:
    while True:
        async with claim_lock:
            if claim_limit and claim_state["claimed"] >= claim_limit:
                return
            job = await claim_next(pool, per_host_concurrency)
            if job is None:
                return
            claim_state["claimed"] += 1

        await throttle.wait(host_of(job.url_key))
        result = await fetch_once(session, job, max_response_bytes, max_article_date)
        content_hash = hashlib.sha256(result.body).hexdigest() if result.body else None
        stored_raw_path = (
            write_raw_html(raw_dir, result.body, content_hash)
            if result.body and content_hash
            else None
        )
        await save_result(pool, job, result, stored_raw_path, content_hash, max_attempts)

        async with progress_lock:
            progress_state["completed"] += 1
            completed = progress_state["completed"]
            if completed == 1 or completed % 100 == 0:
                print(f"Completed: {completed:,}  worker: {worker_id}")


async def ingest_articles(args: argparse.Namespace) -> dict[str, Any]:
    max_attempts = args.retries + 1
    raw_dir = Path(args.raw_dir).resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    pool = await asyncpg.create_pool(
        args.database_url,
        min_size=1,
        max_size=min(args.db_pool_size, args.concurrency),
    )
    try:
        throttle = HostThrottle(args.host_delay)
        await ensure_schema(pool)
        inserted = await load_queue(pool, Path(args.queue))
        claim_state = {"claimed": 0}
        progress_state = {"completed": 0}
        claim_lock = asyncio.Lock()
        progress_lock = asyncio.Lock()
        timeout = aiohttp.ClientTimeout(total=args.timeout)
        connector = aiohttp.TCPConnector(
            limit=args.concurrency,
            limit_per_host=args.per_host_concurrency,
            ttl_dns_cache=300,
            ssl=False,
        )
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            await asyncio.gather(
                *[
                    worker(
                        worker_id,
                        pool,
                        session,
                        raw_dir,
                        args.max_response_bytes,
                        args.per_host_concurrency,
                        max_attempts,
                        args.max_article_date,
                        args.limit,
                        claim_state,
                        claim_lock,
                        progress_state,
                        progress_lock,
                        throttle,
                    )
                    for worker_id in range(args.concurrency)
                ]
            )
        return {
            "queue_rows_inserted": inserted,
            "claimed": claim_state["claimed"],
            "completed": progress_state["completed"],
            "max_attempts": max_attempts,
            "concurrency": args.concurrency,
            "per_host_concurrency": args.per_host_concurrency,
        }
    finally:
        await pool.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE_PATH))
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--per-host-concurrency", type=int, default=PER_HOST_CONCURRENCY)
    parser.add_argument("--max-article-date", default=None,
                        help="ISO upper bound on publication dates; unbounded, "
                             "htmldate falls back to the crawl date on ~15%% of pages")
    parser.add_argument("--host-delay", type=float, default=HOST_DELAY_SECONDS,
                        help="minimum seconds between requests to one host")
    parser.add_argument("--db-pool-size", type=int, default=DB_POOL_SIZE)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=MAX_RETRIES)
    parser.add_argument("--max-response-bytes", type=int, default=MAX_RESPONSE_BYTES)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = asyncio.run(ingest_articles(args))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
