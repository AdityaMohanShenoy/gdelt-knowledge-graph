import asyncio
import gzip
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp
import asyncpg
from article_extractor import EXTRACTOR_VERSION, ExtractionResult, extract_article

ROOT = Path(__file__).resolve().parents[1]
CONCURRENCY = 100
PER_HOST_CONCURRENCY = 4
TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
LEASE_SECONDS = 300
USER_AGENT = "Mozilla/5.0 (compatible; GDELTResearch/1.0)"
DEAD_STATUSES = frozenset({404, 410, 451})
RETRYABLE_STATUSES = frozenset({408, 425, 429})

CLAIM_QUERY_TEMPLATE = """
WITH host_load AS (
    SELECT host_key, COUNT(*) AS active_count
    FROM article_documents
    WHERE status = 'fetching'
      AND lease_expires_at >= NOW()
    GROUP BY host_key
),
candidate AS (
    SELECT documents.document_id
    FROM article_documents AS documents
    LEFT JOIN host_load
        ON host_load.host_key = documents.host_key
    WHERE {predicate}
      AND COALESCE(host_load.active_count, 0) < $2
    ORDER BY documents.document_id
    FOR UPDATE OF documents SKIP LOCKED
    LIMIT 1
)
UPDATE article_documents AS documents
SET status = 'fetching',
    attempt_count = documents.attempt_count + 1,
    lease_expires_at = NOW() + ($1 * INTERVAL '1 second'),
    last_error = NULL
FROM candidate
WHERE documents.document_id = candidate.document_id
RETURNING documents.document_id, documents.url_key,
          documents.source_url, documents.attempt_count
"""
CLAIM_QUERIES = tuple(
    CLAIM_QUERY_TEMPLATE.format(predicate=predicate)
    for predicate in (
        "documents.status = 'fetching' AND documents.lease_expires_at < NOW()",
        "documents.status = 'retryable_error' AND documents.next_attempt_at <= NOW()",
        "documents.status = 'pending'",
    )
)


@dataclass(frozen=True)
class Job:
    document_id: int
    url_key: str
    source_url: str
    attempt_count: int


@dataclass(frozen=True)
class FetchResult:
    status: str
    http_status: int | None = None
    content_type: str | None = None
    final_url: str | None = None
    body: bytes | None = None
    extraction: ExtractionResult | None = None
    error: str | None = None


def now() -> datetime:
    return datetime.now(UTC)


def retry_delay(attempt_count: int) -> float:
    return float(min(60, 2 ** max(0, attempt_count - 1)))


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUSES or status >= 500


def content_type_is_html(content_type: str | None, body: bytes) -> bool:
    if content_type in {"text/html", "application/xhtml+xml"}:
        return True
    return not content_type and body.lstrip().startswith(b"<")


def raw_path(raw_dir: Path, content_hash: str) -> Path:
    return raw_dir / content_hash[:2] / f"{content_hash}.html.gz"


def write_raw_html(raw_dir: Path, body: bytes, content_hash: str) -> str:
    path = raw_path(raw_dir, content_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(temporary_path, "wb") as output:
            output.write(body)
        temporary_path.replace(path)
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


async def fetch_once(
    session: aiohttp.ClientSession,
    job: Job,
    max_response_bytes: int,
) -> FetchResult:
    try:
        async with session.get(
            job.source_url,
            allow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower() or None
            final_url = str(response.url)
            if status in DEAD_STATUSES:
                return FetchResult("dead", status, content_type, final_url)
            if status in {401, 403}:
                return FetchResult("blocked", status, content_type, final_url)
            if is_retryable_status(status):
                return FetchResult(
                    "retryable_error", status, content_type, final_url, error=f"http-{status}"
                )
            if status < 200 or status >= 400:
                return FetchResult(
                    "http_error", status, content_type, final_url, error=f"http-{status}"
                )
            # StreamReader.read(n) returns only what is already buffered, so it
            # truncates the body to the first chunk. Stream to EOF instead.
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.content.iter_chunked(READ_CHUNK_BYTES):
                total += len(chunk)
                if total > max_response_bytes:
                    return FetchResult(
                        "response_too_large",
                        status,
                        content_type,
                        final_url,
                        error=f"response-exceeds-{max_response_bytes}-bytes",
                    )
                chunks.append(chunk)
            body = b"".join(chunks)
            if not content_type_is_html(content_type, body):
                return FetchResult("unsupported_content", status, content_type, final_url)
            extraction = extract_article(body, url=final_url)
            return FetchResult(
                extraction.status,
                status,
                content_type,
                final_url,
                body,
                extraction,
                extraction.reason,
            )
    except (TimeoutError, aiohttp.ClientError) as error:
        return FetchResult("retryable_error", error=type(error).__name__)


async def claim_next(
    pool: asyncpg.Pool,
    per_host_concurrency: int = PER_HOST_CONCURRENCY,
) -> Job | None:
    async with pool.acquire() as connection:
        row = None
        for query in CLAIM_QUERIES:
            row = await connection.fetchrow(query, LEASE_SECONDS, per_host_concurrency)
            if row is not None:
                break
    if row is None:
        return None
    return Job(row["document_id"], row["url_key"], row["source_url"], row["attempt_count"])


async def claim_url(pool: asyncpg.Pool, url_key: str) -> Job | None:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE article_documents AS documents
            SET status = 'fetching',
                attempt_count = documents.attempt_count + 1,
                lease_expires_at = NOW() + ($1 * INTERVAL '1 second'),
                last_error = NULL
            WHERE documents.url_key = $2
              AND (
                  documents.status = 'pending'
                  OR (documents.status = 'retryable_error' AND documents.next_attempt_at <= NOW())
                  OR (documents.status = 'fetching' AND documents.lease_expires_at < NOW())
              )
            RETURNING documents.document_id, documents.url_key,
                      documents.source_url, documents.attempt_count
            """,
            LEASE_SECONDS,
            url_key,
        )
    if row is None:
        return None
    return Job(row["document_id"], row["url_key"], row["source_url"], row["attempt_count"])


async def save_result(
    pool: asyncpg.Pool,
    job: Job,
    result: FetchResult,
    raw_html_path: str | None,
    content_hash: str | None,
    max_attempts: int,
) -> None:
    terminal_status = result.status
    next_attempt_at: datetime | None = None
    error = result.error
    if result.status == "retryable_error" and job.attempt_count < max_attempts:
        terminal_status = "retryable_error"
        next_attempt_at = now() + timedelta(seconds=retry_delay(job.attempt_count))
    elif result.status == "retryable_error":
        terminal_status = "retry_exhausted"

    extraction = result.extraction
    cleaned_text = extraction.text if extraction else None
    title = extraction.title if extraction else None
    text_length = len(cleaned_text) if cleaned_text else 0
    extraction_reason = extraction.reason if extraction else error

    async with pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE article_documents
            SET status = $2,
                final_url = $3,
                http_status = $4,
                content_type = $5,
                title = $6,
                cleaned_text = $7,
                text_length = $8,
                content_hash = $9,
                raw_html_path = $10,
                extraction_reason = $11,
                extractor_version = $12,
                last_error = $13,
                lease_expires_at = NULL,
                next_attempt_at = COALESCE($14, NOW()),
                fetched_at = CASE WHEN $2 <> 'retryable_error' THEN NOW() ELSE fetched_at END
            WHERE document_id = $1
            """,
            job.document_id,
            terminal_status,
            result.final_url,
            result.http_status,
            result.content_type,
            title,
            cleaned_text,
            text_length,
            content_hash,
            raw_html_path,
            extraction_reason,
            EXTRACTOR_VERSION if extraction else None,
            error,
            next_attempt_at,
        )


async def ingest_targeted(
    pool: asyncpg.Pool,
    url_key: str,
    raw_dir: Path,
    timeout_seconds: int = TIMEOUT_SECONDS,
    max_retries: int = MAX_RETRIES,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> None:
    max_attempts = max_retries + 1
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    connector = aiohttp.TCPConnector(limit=1, limit_per_host=1, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        while True:
            job = await claim_url(pool, url_key)
            if job is None:
                return
            result = await fetch_once(session, job, max_response_bytes)
            content_hash = hashlib.sha256(result.body).hexdigest() if result.body else None
            stored_raw_path = (
                write_raw_html(raw_dir, result.body, content_hash)
                if result.body and content_hash
                else None
            )
            await save_result(pool, job, result, stored_raw_path, content_hash, max_attempts)
            if result.status != "retryable_error" or job.attempt_count >= max_attempts:
                return
            await asyncio.sleep(retry_delay(job.attempt_count))
