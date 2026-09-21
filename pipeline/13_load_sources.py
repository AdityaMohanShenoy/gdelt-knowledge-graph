"""Load the evidence store's `sources` table from the article corpus.

`article_documents` is the mutable fetch queue — statuses, leases, retries.
`sources` is the settled evidence record, append-only, and nothing populated it
until now: BUILD_PLAN P1.1 built the schema and P2.1 has nowhere to write.

Also the right place to validate `published_at`. GDELT sources an event from a
news article, so the article is published within days of the event. A date far
outside that window is the crawler's, not the publisher's — and here, unlike
inside the extractor, the event day is actually known.

    python pipeline/13_load_sources.py            # load everything extracted
    python pipeline/13_load_sources.py --limit 500
"""

import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

import asyncpg
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from url_utils import normalize_url  # noqa: E402

DEFAULT_EVENTS = ROOT / "data" / "working" / "india-2024" / "events.parquet"
DEFAULT_DATABASE_URL = "postgresql://gdelt:gdelt_local@localhost:5433/gdelt"
DEFAULT_TOLERANCE_DAYS = 30
BATCH = 5_000


def validated_publication_date(
    published_at: datetime.date | None,
    event_day: datetime.date | None,
    tolerance_days: int,
) -> tuple[datetime.date | None, str | None]:
    """Returns the date to store and, when dropped, why.

    With no event day there is no basis to reject, so the date stands; the raw
    value survives in article_documents either way.
    """
    if published_at is None:
        return None, None
    if event_day is None:
        return published_at, None
    if abs((published_at - event_day).days) <= tolerance_days:
        return published_at, None
    return None, "outside_event_window"


def event_day_by_url_key(events_path: Path) -> dict[str, datetime.date]:
    """Earliest GDELT day per article URL, keyed the same way the queue was."""
    rows = duckdb.connect().execute(
        f"""
        SELECT SOURCEURL, MIN(day) AS day
        FROM read_parquet('{events_path.as_posix()}')
        WHERE SOURCEURL IS NOT NULL AND SOURCEURL <> ''
        GROUP BY SOURCEURL
        """
    ).fetchall()
    mapping: dict[str, datetime.date] = {}
    for source_url, day in rows:
        key = normalize_url(source_url)
        if not key or day is None:
            continue
        parsed = datetime.datetime.strptime(str(int(day)), "%Y%m%d").date()
        existing = mapping.get(key)
        if existing is None or parsed < existing:
            mapping[key] = parsed
    return mapping


async def load(pool: asyncpg.Pool, days: dict[str, datetime.date], tolerance: int, limit: int) -> dict:
    counts = {
        "read": 0, "inserted": 0, "already_present": 0, "superseded": 0,
        "dated": 0, "undated": 0, "date_rejected": 0, "no_event_day": 0,
    }
    last_id = 0
    while True:
        size = BATCH if not limit else min(BATCH, limit - counts["read"])
        if size <= 0:
            break
        rows = await pool.fetch(
            """
            SELECT document_id, url_key, source_url, published_at, fetched_at,
                   content_hash, raw_html_path, status
            FROM article_documents
            WHERE status = 'extracted' AND document_id > $1
            ORDER BY document_id
            LIMIT $2
            """,
            last_id, size,
        )
        if not rows:
            break
        payload = []
        for row in rows:
            last_id = row["document_id"]
            counts["read"] += 1
            event_day = days.get(row["url_key"])
            if event_day is None:
                counts["no_event_day"] += 1
            date, reason = validated_publication_date(row["published_at"], event_day, tolerance)
            if reason:
                counts["date_rejected"] += 1
            counts["dated" if date else "undated"] += 1
            payload.append(
                (row["document_id"], row["source_url"], row["url_key"], date,
                 row["fetched_at"], row["content_hash"], row["raw_html_path"], row["status"])
            )

        # Append-only, so a change is a new row superseding the old one and an
        # unchanged row is skipped. Comparing against current_sources is what
        # keeps a reload idempotent without an UPDATE the table forbids.
        keys = [row[2] for row in payload]
        current = {
            r["url_key"]: (r["published_at"], r["content_hash"], r["raw_html_path"], r["fetch_status"])
            for r in await pool.fetch(
                "SELECT url_key, published_at, content_hash, raw_html_path, fetch_status"
                " FROM current_sources WHERE url_key = ANY($1::text[])", keys
            )
        }
        fresh = [
            row for row in payload
            if current.get(row[2]) != (row[3], row[5], row[6], row[7])
        ]
        counts["already_present"] += len(payload) - len(fresh)
        counts["superseded"] += sum(1 for row in fresh if row[2] in current)
        inserted = 0
        if fresh:
            inserted = await pool.fetchval(
                """
                WITH incoming AS (
                    SELECT * FROM unnest(
                        $1::bigint[], $2::text[], $3::text[], $4::date[],
                        $5::timestamptz[], $6::text[], $7::text[], $8::text[]
                    ) AS t(article_document_id, url, url_key, published_at,
                           fetched_at, content_hash, raw_html_path, fetch_status)
                ), put AS (
                    INSERT INTO sources (article_document_id, url, url_key, published_at,
                                         fetched_at, content_hash, raw_html_path, fetch_status)
                    SELECT * FROM incoming
                    RETURNING 1
                )
                SELECT count(*) FROM put
                """,
                *[list(col) for col in zip(*fresh, strict=True)],
            )
        counts["inserted"] += inserted
        print(f"  read {counts['read']:,}  inserted {counts['inserted']:,}")
        if len(rows) < size:
            break
    return counts


async def main_async(args) -> None:
    print(f"mapping event days from {args.events.relative_to(ROOT)} ...")
    days = event_day_by_url_key(args.events)
    print(f"  {len(days):,} url keys carry a GDELT day")
    pool = await asyncpg.create_pool(args.database_url, min_size=1, max_size=4)
    try:
        counts = await load(pool, days, args.tolerance_days, args.limit)
        total = await pool.fetchval("SELECT count(*) FROM sources")
    finally:
        await pool.close()
    counts["sources_total"] = total
    print(json.dumps(counts, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--tolerance-days", type=int, default=DEFAULT_TOLERANCE_DAYS)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
