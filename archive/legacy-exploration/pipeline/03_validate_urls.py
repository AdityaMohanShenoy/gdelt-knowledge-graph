"""
Step 3: Validate all SOURCEURL values via async HTTP HEAD requests.

- Checks every unique URL in the causal-filtered dataset
- Uses aiohttp with concurrency=50, timeout=10s, 1 retry
- Caches results to out/url_cache.json (reruns skip already-checked URLs)
- Marks URL as dead if: 404, 410, 451, or connection error/timeout
- Drops events with dead URLs

Output: out/step3_url_validated.parquet
         out/url_cache.json
"""

import asyncio
import json
import os
import aiohttp
import polars as pl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_FILE = os.path.join(ROOT, "out", "step2_causal_filtered.parquet")
OUT_FILE = os.path.join(ROOT, "out", "step3_url_validated.parquet")
CACHE_FILE = os.path.join(ROOT, "out", "url_cache.json")

CONCURRENCY = 50
TIMEOUT_SEC = 10
DEAD_STATUSES = {404, 410, 451}
# These status codes often mean the article is behind a paywall or requires login
# but the URL itself is valid — keep them
KEEP_STATUSES = {200, 201, 301, 302, 307, 308, 401, 403, 405, 429, 500, 502, 503}


def load_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print(f"  Warning: cache file corrupted, starting fresh.")
            return {}
    return {}


def save_cache(path: str, cache: dict):
    # Write atomically to a temp file then rename — prevents corruption on kill
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, path)  # atomic rename


async def check_url(session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore) -> tuple[str, bool]:
    """Returns (url, is_alive). Dead = True means the URL should be KEPT."""
    async with semaphore:
        for attempt in range(2):
            try:
                async with session.head(
                    url,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=TIMEOUT_SEC),
                    headers={"User-Agent": "Mozilla/5.0 (compatible; GDELTResearch/1.0)"},
                ) as resp:
                    is_alive = resp.status not in DEAD_STATUSES
                    return url, is_alive
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return url, False  # dead after retry
    return url, False


async def validate_urls(urls: list[str], cache: dict) -> dict:
    unchecked = [u for u in urls if u and u not in cache]
    print(f"URLs to check: {len(unchecked):,}  (cached: {len(urls) - len(unchecked):,})")

    if not unchecked:
        return cache

    semaphore = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [check_url(session, url, semaphore) for url in unchecked]

        done = 0
        batch_size = 500
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i : i + batch_size]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    continue
                url, is_alive = r
                cache[url] = is_alive
            done += len(batch)
            pct = done / len(unchecked) * 100
            alive = sum(1 for v in cache.values() if v)
            print(f"  Progress: {done:,}/{len(unchecked):,} ({pct:.0f}%)  alive so far: {alive:,}")

            # Save cache every batch
            save_cache(CACHE_FILE, cache)

    return cache


def main():
    print(f"Loading {IN_FILE}...")
    df = pl.read_parquet(IN_FILE)
    print(f"Loaded {len(df):,} events")

    # Extract unique non-empty URLs
    urls = df.filter(pl.col("SOURCEURL").is_not_null() & (pl.col("SOURCEURL") != ""))["SOURCEURL"].unique().to_list()
    print(f"Unique URLs to validate: {len(urls):,}")

    # Load cache
    cache = load_cache(CACHE_FILE)
    print(f"Loaded {len(cache):,} cached URL results")

    # Run async validation
    cache = asyncio.run(validate_urls(urls, cache))
    save_cache(CACHE_FILE, cache)

    # Summary
    alive_count = sum(1 for v in cache.values() if v)
    dead_count = sum(1 for v in cache.values() if not v)
    print(f"\nURL validation results:")
    print(f"  Alive: {alive_count:,}")
    print(f"  Dead:  {dead_count:,}  ({dead_count / len(cache) * 100:.1f}%)")

    # Filter dataframe: keep events with alive URLs or no URL at all
    # (events with no URL can still be useful structurally)
    df = df.with_columns(
        pl.col("SOURCEURL").map_elements(
            lambda u: cache.get(u, True) if u else False,  # no URL = drop
            return_dtype=pl.Boolean,
        ).alias("url_alive")
    )

    before = len(df)
    df_valid = df.filter(pl.col("url_alive")).drop("url_alive")
    after = len(df_valid)
    print(f"\nEvents before URL filter: {before:,}")
    print(f"Events after URL filter:  {after:,}  (dropped {before - after:,})")

    df_valid.write_parquet(OUT_FILE)
    print(f"Written to: {OUT_FILE}")


if __name__ == "__main__":
    main()
