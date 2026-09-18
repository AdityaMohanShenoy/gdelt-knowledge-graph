"""
Step 2: Keep only events with few causal precursors (causal_in_degree <= 2).

Why actor-name matching fails: names like "UNITED STATES" appear 4M times.
Why full self-join fails: 26M events × 26M events cross-product OOMs on 25GB RAM.

Solution — window function approach (O(N log N), no cross-product):
  For each event E, count how many events with the SAME (country-pair, EventRootCode)
  occurred in the 7 days immediately before E. This is the causal_in_degree.

  Then for the small filtered subset (in_degree <= 2), do a targeted join to find
  the specific precursor event IDs for Neo4j edges.

Semantics:
  If the same country pair interacted in the same way (same CAMEO root code) recently,
  this event is part of an ongoing chain. Fresh/initiating events have in_degree = 0.

Output: out/step2_causal_filtered.parquet
"""

import os
import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_FILE = os.path.join(ROOT, "out", "step1_country_filtered.parquet").replace("\\", "/")
OUT_FILE = os.path.join(ROOT, "out", "step2_causal_filtered.parquet").replace("\\", "/")

WINDOW_DAYS = 7
MAX_IN_DEGREE = 2


def main():
    print(f"Loading {IN_FILE}...")

    # Use a persistent DuckDB database for spilling to disk if needed
    db_path = os.path.join(ROOT, "out", "step2_work.duckdb").replace("\\", "/")
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")

    con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{IN_FILE}')")

    total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"Total events: {total:,}")

    # Build enriched table with date and normalized country-pair key
    print("Building pair_key column...")
    con.execute("""
    CREATE TABLE events_keyed AS
    SELECT
        GlobalEventID,
        day,
        strptime(CAST(day AS VARCHAR), '%Y%m%d')::DATE AS event_date,
        COALESCE(NULLIF(Actor1CountryCode, ''), ActionGeo_CountryCode, 'XX') AS c1_raw,
        COALESCE(NULLIF(Actor2CountryCode, ''), ActionGeo_CountryCode, 'XX') AS c2_raw,
        COALESCE(NULLIF(EventRootCode, ''), '00') AS root_code,
        EventCode,
        EventRootCode,
        QuadClass,
        GoldsteinScale,
        Actor1Name,
        Actor1CountryCode,
        Actor2Name,
        Actor2CountryCode,
        ActionGeo_CountryCode,
        SOURCEURL,
        datetime
    FROM events
    """)

    con.execute("""
    ALTER TABLE events_keyed ADD COLUMN pair_key VARCHAR;
    UPDATE events_keyed
    SET pair_key =
        CASE WHEN c1_raw <= c2_raw
             THEN c1_raw || '|' || c2_raw
             ELSE c2_raw || '|' || c1_raw
        END || '|' || root_code
    """)

    print("Computing causal in-degree via window function (no cross-join)...")
    # Window function: count preceding events with same pair_key in last 7 days
    # RANGE BETWEEN ... PRECEDING requires ORDER BY a numeric/date column
    # DuckDB supports date RANGE windows
    con.execute("""
    CREATE TABLE events_with_degree AS
    SELECT
        GlobalEventID, day, event_date, pair_key,
        EventCode, EventRootCode, QuadClass, GoldsteinScale,
        Actor1Name, Actor1CountryCode,
        Actor2Name, Actor2CountryCode,
        ActionGeo_CountryCode, SOURCEURL, datetime,
        (COUNT(*) OVER (
            PARTITION BY pair_key
            ORDER BY event_date
            RANGE BETWEEN INTERVAL 7 DAYS PRECEDING AND INTERVAL 1 DAYS PRECEDING
        ))::INTEGER AS causal_in_degree
    FROM events_keyed
    """)

    # Show degree distribution
    print("\nCausal in-degree distribution:")
    dist = con.execute("""
    SELECT
        CASE WHEN causal_in_degree >= 5 THEN '5+'
             ELSE CAST(causal_in_degree AS VARCHAR)
        END AS bucket,
        COUNT(*) AS cnt
    FROM events_with_degree
    GROUP BY bucket
    ORDER BY MIN(causal_in_degree)
    """).fetchall()
    for bucket, cnt in dist:
        pct = cnt / total * 100
        print(f"  in_degree={bucket:>3}: {cnt:>9,}  ({pct:.1f}%)")

    # Filter to low in-degree
    print(f"\nFiltering to in_degree <= {MAX_IN_DEGREE}...")
    con.execute(f"""
    CREATE TABLE filtered AS
    SELECT * FROM events_with_degree
    WHERE causal_in_degree <= {MAX_IN_DEGREE}
    """)

    kept = con.execute("SELECT COUNT(*) FROM filtered").fetchone()[0]
    print(f"Events kept:    {kept:,}  ({kept / total * 100:.1f}% of input)")
    print(f"Events removed: {total - kept:,}")

    # Compute precursor_ids for the filtered subset (much smaller join)
    print("\nComputing precursor IDs for filtered events (for Neo4j edges)...")
    con.execute(f"""
    CREATE TABLE precursor_links AS
    SELECT
        f.GlobalEventID AS event_id,
        STRING_AGG(DISTINCT CAST(prev.GlobalEventID AS VARCHAR), ',') AS precursor_ids
    FROM filtered f
    JOIN events_keyed prev
        ON prev.pair_key = f.pair_key
       AND prev.event_date >= (f.event_date - INTERVAL '{WINDOW_DAYS} days')
       AND prev.event_date < f.event_date
    WHERE f.causal_in_degree > 0
    GROUP BY f.GlobalEventID
    """)

    linked = con.execute("SELECT COUNT(*) FROM precursor_links").fetchone()[0]
    print(f"  Events with precursor IDs stored: {linked:,}")

    # Write final output
    print(f"\nWriting to {OUT_FILE}...")
    con.execute(f"""
    COPY (
        SELECT
            f.day, f.datetime, f.GlobalEventID,
            f.EventCode, f.EventRootCode, f.QuadClass, f.GoldsteinScale,
            f.Actor1Name, f.Actor1CountryCode,
            f.Actor2Name, f.Actor2CountryCode,
            f.ActionGeo_CountryCode, f.SOURCEURL,
            f.causal_in_degree,
            COALESCE(pl.precursor_ids, '') AS precursor_ids
        FROM filtered f
        LEFT JOIN precursor_links pl ON f.GlobalEventID = pl.event_id
        ORDER BY f.day, f.GlobalEventID
    ) TO '{OUT_FILE}' (FORMAT PARQUET)
    """)

    final = con.execute(f"SELECT COUNT(*) FROM read_parquet('{OUT_FILE}')").fetchone()[0]
    print(f"Final row count: {final:,}")
    print(f"Written to: {OUT_FILE}")
    con.close()

    # Clean up work database
    if os.path.exists(db_path):
        os.remove(db_path)
    wal = db_path + ".wal"
    if os.path.exists(wal):
        os.remove(wal)


if __name__ == "__main__":
    main()
