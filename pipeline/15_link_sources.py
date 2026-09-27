"""Attach the GDELT source articles to each event in the evidence store.

"8 events, 4 outlets" is not something an annotator can check. This puts the
actual reporting one click away, with the headline where we have it.

Runs over events already in the store, so judgements already recorded survive.

    python pipeline/15_link_sources.py --schema evidence --database-url "$SUPABASE"
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

from annotator.app import search_path_setup  # noqa: E402
from scoring.sql import num, rows, safe  # noqa: E402
from url_utils import normalize_url  # noqa: E402

DEFAULT_PARQUET = ROOT / "out" / "step2_causal_filtered.parquet"
ARTICLE_DB = "postgresql://gdelt:gdelt_local@localhost:5433/gdelt"
PER_GROUP = 12   # enough to check the claim; a whole day's wire copy is not


def domain_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


async def headline_index(urls: list[str]) -> dict[str, dict]:
    """Titles and publication dates from the local article store, where the
    fetcher got that far. Missing ones just show their domain."""
    if not urls:
        return {}
    try:
        conn = await asyncpg.connect(ARTICLE_DB, statement_cache_size=0, timeout=10)
    except Exception:
        return {}
    try:
        got = await conn.fetch(
            "SELECT url_key, title, published_at FROM article_documents"
            " WHERE url_key = ANY($1::text[]) AND title IS NOT NULL",
            urls)
        return {r["url_key"]: {"title": r["title"],
                               "published_at": str(r["published_at"]) if r["published_at"] else None}
                for r in got}
    finally:
        await conn.close()


async def main_async(args) -> None:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{args.parquet.as_posix()}')")

    pool = await asyncpg.create_pool(
        args.database_url, min_size=1, max_size=4,
        setup=search_path_setup(args.schema), statement_cache_size=0)
    try:
        stored = await pool.fetch("""
            SELECT e.event_id, e.external_id,
                   EXISTS (SELECT 1 FROM claims c WHERE c.cause_id = e.event_id) AS is_cause
            FROM events e WHERE e.external_id IS NOT NULL
        """)
        ids = [r["external_id"] for r in stored]
        print(f"{len(ids)} events in the store")

        # One scan: where each stored event sits, so a cause can be widened to
        # the whole (day, type) group it actually stands for.
        placed = {str(int(num(r["GlobalEventID"]))): r for r in rows(con.execute(
            f"SELECT GlobalEventID, day, COALESCE(NULLIF(EventRootCode,''),'00') AS rc,"
            f" ActionGeo_CountryCode AS cc, SOURCEURL"
            f" FROM events WHERE CAST(GlobalEventID AS VARCHAR) IN"
            f" ({','.join(repr(i) for i in ids)})"))}

        groups = {(int(num(r['day'])), str(r['rc']), str(r['cc']))
                  for r in placed.values()}
        by_group: dict[tuple, list[str]] = {}
        for day, rc, cc in groups:
            got = rows(con.execute(f"""
                SELECT SOURCEURL FROM events
                WHERE day = {day} AND COALESCE(NULLIF(EventRootCode,''),'00') = '{safe(rc)}'
                  AND ActionGeo_CountryCode = '{safe(cc)}'
                  AND SOURCEURL IS NOT NULL AND SOURCEURL <> ''
                GROUP BY SOURCEURL ORDER BY SOURCEURL
            """))
            by_group[(day, rc, cc)] = [str(r["SOURCEURL"]) for r in got]

        wanted: set[str] = set()
        plan: dict[int, list[str]] = {}
        for row in stored:
            here = placed.get(row["external_id"])
            if here is None:
                continue
            key = (int(num(here["day"])), str(here["rc"]), str(here["cc"]))
            urls = by_group.get(key, []) if row["is_cause"] else [str(here["SOURCEURL"] or "")]
            urls = [u for u in urls if u][:PER_GROUP]
            plan[row["event_id"]] = urls
            wanted.update(normalize_url(u) for u in urls if normalize_url(u))

        print(f"{len(wanted)} distinct articles; looking up headlines")
        heads = await headline_index(sorted(wanted))
        print(f"  {len(heads)} have a title stored locally")

        written = 0
        for event_id, urls in plan.items():
            payload = []
            for u in urls:
                key = normalize_url(u)
                meta = heads.get(key, {})
                payload.append({"url": u, "domain": domain_of(u),
                                "title": meta.get("title"),
                                "published_at": meta.get("published_at")})
            await pool.execute("UPDATE events SET source_urls = $2 WHERE event_id = $1",
                               event_id, json.dumps(payload))
            written += 1
        linked = await pool.fetchval(
            "SELECT count(*) FROM events WHERE jsonb_array_length(source_urls) > 0")
        print(json.dumps({"events_updated": written, "events_with_links": linked,
                          "headlines_found": len(heads)}, indent=2))
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--schema", default="evidence")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
