"""
Step 1: Filter GDELT 2024 parquet data to top-10 countries only.

Reads all 365 daily parquet files (~14M events) using DuckDB (no RAM overload),
keeps only rows where any of the three country columns matches a top-10 country.

Output: out/step1_country_filtered.parquet
"""

import os
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARQUET_GLOB = os.path.join(ROOT, "out_parquet", "events", "year=2024", "**", "*.parquet").replace("\\", "/")
COUNTRIES_FILE = os.path.join(ROOT, "out", "top10_countries_2024.txt")
OUT_FILE = os.path.join(ROOT, "out", "step1_country_filtered.parquet")


def load_country_codes(path: str) -> list[str]:
    codes = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                code = line.split(",")[0]
                codes.append(code.strip())
    return codes


def main():
    country_codes = load_country_codes(COUNTRIES_FILE)
    print(f"Filtering to {len(country_codes)} countries: {country_codes}")

    codes_sql = ", ".join(f"'{c}'" for c in country_codes)

    con = duckdb.connect()

    # Count total first so we can report reduction
    print("Counting total events across all parquet files...")
    total = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{PARQUET_GLOB}', hive_partitioning=true)"
    ).fetchone()[0]
    print(f"Total events in 2024: {total:,}")

    print("Filtering by country...")
    query = f"""
    SELECT
        day,
        datetime,
        GlobalEventID,
        EventCode,
        EventRootCode,
        QuadClass,
        GoldsteinScale,
        Actor1Name,
        Actor1CountryCode,
        Actor2Name,
        Actor2CountryCode,
        ActionGeo_CountryCode,
        SOURCEURL
    FROM read_parquet('{PARQUET_GLOB}', hive_partitioning=true)
    WHERE
        Actor1CountryCode IN ({codes_sql})
        OR Actor2CountryCode IN ({codes_sql})
        OR ActionGeo_CountryCode IN ({codes_sql})
    ORDER BY day, GlobalEventID
    """

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    con.execute(f"COPY ({query}) TO '{OUT_FILE.replace(chr(92), '/')}' (FORMAT PARQUET)")

    filtered = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT_FILE.replace(chr(92), '/')}')" ).fetchone()[0]
    print(f"\nFiltered events: {filtered:,}  ({filtered / total * 100:.1f}% of total)")
    print(f"Written to: {OUT_FILE}")
    con.close()


if __name__ == "__main__":
    main()
