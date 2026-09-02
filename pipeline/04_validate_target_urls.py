import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = ROOT / "data" / "working" / "india-2024" / "target_events.parquet"
DEFAULT_OUTPUT_PATH = (
    ROOT / "data" / "working" / "india-2024" / "target_events_url_validated.parquet"
)
DEFAULT_CACHE_PATH = ROOT / "data" / "working" / "india-2024" / "url_cache.json"
DEFAULT_MANIFEST_PATH = ROOT / "data" / "working" / "india-2024" / "url_manifest.json"
CONCURRENCY = 50
TIMEOUT_SECONDS = 10
RETRY_COUNT = 2
BATCH_SIZE = 1000
DEAD_STATUSES = frozenset({404, 410, 451})
FALLBACK_STATUSES = frozenset({405, 501})
USER_AGENT = "Mozilla/5.0 (compatible; GDELTResearch/1.0)"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_relation(input_path: str | Path) -> str:
    return f"read_parquet({sql_string(Path(input_path).as_posix())}, hive_partitioning=true)"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def now() -> str:
    return datetime.now(UTC).isoformat()


def status_result(status: int | None, reason: str) -> dict[str, Any]:
    return {
        "alive": status is not None and status not in DEAD_STATUSES,
        "status": status,
        "reason": reason,
        "checked_at": now(),
    }


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    cache: dict[str, dict[str, Any]] = {}
    for url, value in payload.items():
        if isinstance(value, bool):
            cache[url] = status_result(None, "legacy-cache")
            cache[url]["alive"] = value
        elif isinstance(value, dict) and isinstance(value.get("alive"), bool):
            cache[url] = value
    return cache


def save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    temporary_path.replace(path)


async def check_url(
    session: aiohttp.ClientSession,
    url: str,
    semaphore: asyncio.Semaphore,
    timeout_seconds: int,
) -> tuple[str, dict[str, Any]]:
    async with semaphore:
        last_reason = "request-failed"
        for attempt in range(RETRY_COUNT):
            try:
                async with asyncio.timeout(timeout_seconds + 2):
                    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
                    async with session.head(
                        url,
                        allow_redirects=True,
                        timeout=timeout,
                        headers={"User-Agent": USER_AGENT},
                    ) as response:
                        status = response.status
                    if status in FALLBACK_STATUSES:
                        async with session.get(
                            url,
                            allow_redirects=True,
                            timeout=timeout,
                            headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"},
                        ) as response:
                            status = response.status
                    return url, status_result(status, f"http-{status}")
            except (aiohttp.ClientError, TimeoutError) as error:
                last_reason = type(error).__name__
                if attempt < RETRY_COUNT - 1:
                    await asyncio.sleep(0.25)
        return url, status_result(None, last_reason)


async def validate_urls(
    urls: list[str],
    cache: dict[str, dict[str, Any]],
    cache_path: Path,
    concurrency: int,
    timeout_seconds: int,
) -> dict[str, dict[str, Any]]:
    unchecked = [url for url in urls if url not in cache]
    print(f"URLs to check: {len(unchecked):,}  (cached: {len(urls) - len(unchecked):,})")
    if not unchecked:
        return cache

    semaphore = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        for start in range(0, len(unchecked), BATCH_SIZE):
            batch = unchecked[start : start + BATCH_SIZE]
            results = await asyncio.gather(
                *[
                    check_url(session, url, semaphore, timeout_seconds)
                    for url in batch
                ],
                return_exceptions=True,
            )
            for url, result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    cache[url] = status_result(None, type(result).__name__)
                else:
                    checked_url, checked_result = result
                    cache[checked_url] = checked_result
            save_cache(cache_path, cache)
            checked = min(start + len(batch), len(unchecked))
            alive = sum(
                1
                for url in urls
                if isinstance(cache.get(url), dict) and cache[url].get("alive") is True
            )
            print(f"Progress: {checked:,}/{len(unchecked):,}  live URLs: {alive:,}")
    return cache


def extract_urls(input_path: str | Path) -> list[str]:
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            SELECT DISTINCT SOURCEURL
            FROM {parquet_relation(input_path)}
            WHERE SOURCEURL IS NOT NULL AND SOURCEURL <> ''
            ORDER BY SOURCEURL
            """
        ).fetchall()
    finally:
        connection.close()
    return [str(row[0]) for row in rows]


def filter_dataset(
    input_path: str | Path,
    output_path: Path,
    cache: dict[str, dict[str, Any]],
) -> dict[str, int]:
    connection = duckdb.connect()
    output_path = output_path.resolve()
    status_rows = [
        (url, bool(result.get("alive")))
        for url, result in cache.items()
        if isinstance(result, dict)
    ]
    input_relation = parquet_relation(input_path)
    try:
        before = connection.execute(f"SELECT COUNT(*) FROM {input_relation}").fetchone()
        if before is None:
            raise RuntimeError("Unable to count input events")
        connection.execute("CREATE TEMP TABLE url_status (url VARCHAR, alive BOOLEAN)")
        connection.executemany("INSERT INTO url_status VALUES (?, ?)", status_rows)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        connection.execute(
            f"""
            COPY (
                SELECT events.*
                FROM {input_relation} AS events
                INNER JOIN url_status
                    ON events.SOURCEURL = url_status.url
                WHERE url_status.alive
            ) TO {sql_string(output_path.as_posix())}
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        after = connection.execute(
            f"SELECT COUNT(*) FROM {parquet_relation(output_path)}"
        ).fetchone()
        if after is None:
            raise RuntimeError("Unable to count filtered events")
    finally:
        connection.close()
    return {"input_rows": int(before[0]), "output_rows": int(after[0])}


def build_manifest(
    input_path: str | Path,
    output_path: Path,
    cache_path: Path,
    urls: list[str],
    cache: dict[str, dict[str, Any]],
    counts: dict[str, int],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    live_urls = 0
    for url in urls:
        result = cache.get(url)
        if result is None:
            key = "missing-result"
            alive = False
        else:
            status = result.get("status")
            key = str(status) if status is not None else str(result.get("reason", "unknown"))
            alive = result.get("alive") is True
        status_counts[key] = status_counts.get(key, 0) + 1
        live_urls += int(alive)

    return {
        "manifest_version": "india-target-url-validated.v1",
        "input_path": display_path(Path(input_path)),
        "output_path": display_path(output_path),
        "cache_path": display_path(cache_path),
        "generated_at": now(),
        "filter": {
            "source_field": "SOURCEURL",
            "behavior": "keep events with a validated live source URL",
            "dead_statuses": sorted(DEAD_STATUSES),
        },
        "unique_urls": len(urls),
        "live_urls": live_urls,
        "dead_urls": len(urls) - live_urls,
        "input_rows": counts["input_rows"],
        "output_rows": counts["output_rows"],
        "dropped_rows": counts["input_rows"] - counts["output_rows"],
        "status_counts": status_counts,
    }


def validate_dataset(
    input_path: str | Path,
    output_path: Path,
    cache_path: Path,
    manifest_path: Path,
    concurrency: int = CONCURRENCY,
    timeout_seconds: int = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    urls = extract_urls(input_path)
    cache = load_cache(cache_path)
    cache = asyncio.run(
        validate_urls(urls, cache, cache_path, concurrency, timeout_seconds)
    )
    counts = filter_dataset(input_path, output_path, cache)
    manifest = build_manifest(input_path, output_path, cache_path, urls, cache, counts)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = validate_dataset(
        args.input,
        Path(args.output),
        Path(args.cache),
        Path(args.manifest),
        args.concurrency,
        args.timeout,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
