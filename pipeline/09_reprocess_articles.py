import argparse
import asyncio
import gzip
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import asyncpg
from article_extractor import (
    EXTRACTOR_VERSION,
    ExtractionResult,
    extract_article,
    extract_article_variant,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5432/gdelt"
)
DEFAULT_RAW_DIR = ROOT / "data" / "evidence" / "articles" / "raw"
DEFAULT_BENCHMARK_PATH = (
    ROOT / "data" / "evidence" / "articles" / "benchmarks" / "trafilatura.jsonl"
)
DEFAULT_SAMPLE_SIZE = 200
DEFAULT_BATCH_SIZE = 500
BENCHMARK_STATUSES = (
    "extracted",
    "insufficient_text",
    "paywall",
    "blocked",
    "parse_error",
)
CandidateMode = Literal["precision", "recall", "production"]


def resolve_raw_path(raw_html_path: str, raw_dir: Path = DEFAULT_RAW_DIR) -> Path:
    path = Path(raw_html_path)
    if path.is_absolute():
        return path
    if raw_html_path.startswith("data/evidence/articles/raw/"):
        return ROOT / path
    return raw_dir / path


def read_raw_html(raw_html_path: str, raw_dir: Path = DEFAULT_RAW_DIR) -> bytes:
    path = resolve_raw_path(raw_html_path, raw_dir)
    with gzip.open(path, "rb") as source:
        return source.read()


def result_payload(result: ExtractionResult) -> dict[str, object]:
    return {
        "status": result.status,
        "title": result.title,
        "text": result.text,
        "text_length": len(result.text),
        "reason": result.reason,
    }


def row_url(row: asyncpg.Record) -> str | None:
    return row["final_url"] or row["source_url"]


async def select_benchmark_rows(
    pool: asyncpg.Pool,
    sample_size: int,
) -> list[asyncpg.Record]:
    per_status = max(1, (sample_size + len(BENCHMARK_STATUSES) - 1) // len(BENCHMARK_STATUSES))
    rows: list[asyncpg.Record] = []
    seen: set[int] = set()
    for status in BENCHMARK_STATUSES:
        status_rows = await pool.fetch(
            """
            SELECT document_id, url_key, source_url, final_url, status,
                   title, cleaned_text, text_length, raw_html_path
            FROM article_documents
            WHERE status = $1
              AND raw_html_path IS NOT NULL
            ORDER BY md5(url_key), document_id
            LIMIT $2
            """,
            status,
            per_status,
        )
        for row in status_rows:
            if row["document_id"] not in seen and len(rows) < sample_size:
                rows.append(row)
                seen.add(row["document_id"])

    if len(rows) < sample_size:
        remaining = await pool.fetch(
            """
            SELECT document_id, url_key, source_url, final_url, status,
                   title, cleaned_text, text_length, raw_html_path
            FROM article_documents
            WHERE raw_html_path IS NOT NULL
            ORDER BY md5(url_key), document_id
            LIMIT $1
            """,
            sample_size * 2,
        )
        for row in remaining:
            if row["document_id"] not in seen and len(rows) < sample_size:
                rows.append(row)
                seen.add(row["document_id"])
    return rows


def run_candidate(
    row: asyncpg.Record,
    raw_dir: Path,
    mode: CandidateMode = "production",
) -> ExtractionResult:
    body = read_raw_html(row["raw_html_path"], raw_dir)
    if mode == "precision":
        return extract_article_variant(body, url=row_url(row), favor_recall=False)
    if mode == "recall":
        return extract_article_variant(body, url=row_url(row), favor_recall=True)
    return extract_article(body, url=row_url(row))


async def benchmark(
    pool: asyncpg.Pool,
    raw_dir: Path,
    output_path: Path,
    sample_size: int,
) -> dict[str, Any]:
    rows = await select_benchmark_rows(pool, sample_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    with output_path.open("w", encoding="utf-8") as output:
        for row in rows:
            record: dict[str, object] = {
                "document_id": row["document_id"],
                "url_key": row["url_key"],
                "source_url": row["source_url"],
                "final_url": row["final_url"],
                "baseline_status": row["status"],
                "baseline_title": row["title"],
                "baseline_text": row["cleaned_text"],
                "baseline_text_length": row["text_length"],
                "raw_html_path": row["raw_html_path"],
                "extractor_version": EXTRACTOR_VERSION,
            }
            try:
                precision = run_candidate(row, raw_dir, mode="precision")
                recall = run_candidate(row, raw_dir, mode="recall")
                production = run_candidate(row, raw_dir, mode="production")
                record["precision"] = result_payload(precision)
                record["recall"] = result_payload(recall)
                record["production"] = result_payload(production)
                counts[f"precision:{precision.status}"] += 1
                counts[f"recall:{recall.status}"] += 1
                counts[f"production:{production.status}"] += 1
            except (OSError, EOFError, gzip.BadGzipFile) as error:
                record["error"] = f"{type(error).__name__}: {error}"
                counts["read_error"] += 1
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "mode": "benchmark",
        "sample_size_requested": sample_size,
        "rows_written": len(rows),
        "output": str(output_path),
        "extractor_version": EXTRACTOR_VERSION,
        "counts": dict(sorted(counts.items())),
    }


async def promote(
    pool: asyncpg.Pool,
    raw_dir: Path,
    batch_size: int,
    limit: int,
) -> dict[str, Any]:
    last_document_id = 0
    processed = 0
    counts: Counter[str] = Counter()
    while limit == 0 or processed < limit:
        fetch_size = min(batch_size, limit - processed) if limit else batch_size
        rows = await pool.fetch(
            """
            SELECT document_id, source_url, final_url, status, raw_html_path
            FROM article_documents
            WHERE document_id > $1
              AND raw_html_path IS NOT NULL
              AND status <> 'fetching'
              AND extractor_version IS DISTINCT FROM $2
            ORDER BY document_id
            LIMIT $3
            """,
            last_document_id,
            EXTRACTOR_VERSION,
            fetch_size,
        )
        if not rows:
            break
        for row in rows:
            last_document_id = row["document_id"]
            try:
                result = run_candidate(row, raw_dir, mode="production")
            except (OSError, EOFError, gzip.BadGzipFile) as error:
                counts[f"read_error:{type(error).__name__}"] += 1
                continue
            updated = await pool.execute(
                """
                UPDATE article_documents
                SET status = $2,
                    title = $3,
                    cleaned_text = $4,
                    text_length = $5,
                    extraction_reason = $6,
                    extractor_version = $7,
                    last_error = NULL
                WHERE document_id = $1
                  AND status <> 'fetching'
                  AND extractor_version IS DISTINCT FROM $7
                """,
                row["document_id"],
                result.status,
                result.title,
                result.text,
                len(result.text),
                result.reason,
                EXTRACTOR_VERSION,
            )
            if updated == "UPDATE 1":
                counts[result.status] += 1
                processed += 1
            else:
                counts["skipped_concurrent_update"] += 1
        if len(rows) < fetch_size:
            break
    return {
        "mode": "promote",
        "processed": processed,
        "extractor_version": EXTRACTOR_VERSION,
        "counts": dict(sorted(counts.items())),
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    pool = await asyncpg.create_pool(args.database_url, min_size=1, max_size=2)
    try:
        raw_dir = Path(args.raw_dir).resolve()
        if args.mode == "benchmark":
            return await benchmark(
                pool,
                raw_dir,
                Path(args.output).resolve(),
                args.sample_size,
            )
        return await promote(pool, raw_dir, args.batch_size, args.limit)
    finally:
        await pool.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("benchmark", "promote"))
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--output", default=str(DEFAULT_BENCHMARK_PATH))
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
