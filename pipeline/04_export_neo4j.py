"""
Step 4: Export cleaned GDELT data to Neo4j.

Graph schema:
  Nodes:    Event, Country, Actor, Article, Theme
  Edges:    ACTOR1_IN, ACTOR2_IN, OCCURRED_IN, MENTIONED_IN, HAS_THEME, PRECEDED_BY

Requires a running Neo4j instance. Set connection details via environment variables:
  NEO4J_URI      (default: bolt://localhost:7687)
  NEO4J_USER     (default: neo4j)
  NEO4J_PASSWORD (required)

Usage:
  NEO4J_PASSWORD=yourpassword python pipeline/04_export_neo4j.py
"""

import os
import polars as pl
from neo4j import GraphDatabase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_FILE = os.path.join(ROOT, "out", "step3_url_validated.parquet")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

BATCH_SIZE = 500

# CAMEO country code -> readable name (common ones)
COUNTRY_NAMES = {
    "US": "United States", "IS": "Israel", "UP": "Palestine",
    "RS": "Russia", "IN": "India", "UK": "United Kingdom",
    "PK": "Pakistan", "NI": "Nicaragua", "DJ": "Djibouti", "AS": "Australia",
}

# CAMEO QuadClass meanings
QUAD_CLASS = {"1": "Verbal Cooperation", "2": "Material Cooperation",
              "3": "Verbal Conflict", "4": "Material Conflict"}


def run_batch(tx, query: str, batch: list[dict]):
    tx.run(query, rows=batch)


def create_constraints(driver):
    print("Creating constraints and indexes...")
    constraints = [
        "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE",
        "CREATE CONSTRAINT country_code IF NOT EXISTS FOR (c:Country) REQUIRE c.code IS UNIQUE",
        "CREATE CONSTRAINT article_url IF NOT EXISTS FOR (a:Article) REQUIRE a.url IS UNIQUE",
        "CREATE CONSTRAINT actor_key IF NOT EXISTS FOR (a:Actor) REQUIRE a.name IS UNIQUE",
        "CREATE CONSTRAINT theme_name IF NOT EXISTS FOR (t:Theme) REQUIRE t.name IS UNIQUE",
    ]
    with driver.session() as session:
        for c in constraints:
            try:
                session.run(c)
            except Exception as e:
                print(f"  Warning: {e}")
    print("  Done.")


def ingest_events(driver, rows: list[dict]):
    query = """
    UNWIND $rows AS row
    MERGE (e:Event {id: row.id})
    SET e.date       = row.date,
        e.eventCode  = row.eventCode,
        e.rootCode   = row.rootCode,
        e.quadClass  = row.quadClass,
        e.goldstein  = row.goldstein,
        e.inDegree   = row.inDegree
    """
    with driver.session() as session:
        for i in range(0, len(rows), BATCH_SIZE):
            session.execute_write(run_batch, query, rows[i:i+BATCH_SIZE])


def ingest_countries(driver, codes: set):
    query = """
    UNWIND $rows AS row
    MERGE (c:Country {code: row.code})
    SET c.name = row.name
    """
    rows = [{"code": c, "name": COUNTRY_NAMES.get(c, c)} for c in codes if c]
    with driver.session() as session:
        session.execute_write(run_batch, query, rows)


def ingest_actors(driver, names: set):
    query = """
    UNWIND $rows AS row
    MERGE (a:Actor {name: row.name})
    """
    rows = [{"name": n} for n in names if n]
    with driver.session() as session:
        for i in range(0, len(rows), BATCH_SIZE):
            session.execute_write(run_batch, query, rows[i:i+BATCH_SIZE])


def ingest_articles(driver, rows: list[dict]):
    query = """
    UNWIND $rows AS row
    MERGE (a:Article {url: row.url})
    SET a.source = row.source
    """
    with driver.session() as session:
        for i in range(0, len(rows), BATCH_SIZE):
            session.execute_write(run_batch, query, rows[i:i+BATCH_SIZE])


def ingest_event_relationships(driver, rows: list[dict]):
    """Create OCCURRED_IN, ACTOR1_IN, ACTOR2_IN, MENTIONED_IN edges."""
    query = """
    UNWIND $rows AS row
    MATCH (e:Event {id: row.event_id})

    // OCCURRED_IN
    FOREACH (_ IN CASE WHEN row.geo_country <> '' THEN [1] ELSE [] END |
        MERGE (c:Country {code: row.geo_country})
        MERGE (e)-[:OCCURRED_IN]->(c)
    )

    // ACTOR1_IN
    FOREACH (_ IN CASE WHEN row.actor1 <> '' THEN [1] ELSE [] END |
        MERGE (a1:Actor {name: row.actor1})
        MERGE (a1)-[:ACTOR1_IN]->(e)
    )

    // ACTOR2_IN
    FOREACH (_ IN CASE WHEN row.actor2 <> '' THEN [1] ELSE [] END |
        MERGE (a2:Actor {name: row.actor2})
        MERGE (a2)-[:ACTOR2_IN]->(e)
    )

    // MENTIONED_IN
    FOREACH (_ IN CASE WHEN row.url <> '' THEN [1] ELSE [] END |
        MERGE (art:Article {url: row.url})
        MERGE (e)-[:MENTIONED_IN]->(art)
    )
    """
    with driver.session() as session:
        for i in range(0, len(rows), BATCH_SIZE):
            session.execute_write(run_batch, query, rows[i:i+BATCH_SIZE])
            if i % 5000 == 0:
                print(f"  Relationships: {i:,}/{len(rows):,}")


def ingest_causal_edges(driver, rows: list[dict]):
    """Create PRECEDED_BY edges between events."""
    query = """
    UNWIND $rows AS row
    MATCH (later:Event {id: row.later_id})
    MATCH (earlier:Event {id: row.earlier_id})
    MERGE (later)-[:PRECEDED_BY]->(earlier)
    """
    with driver.session() as session:
        for i in range(0, len(rows), BATCH_SIZE):
            session.execute_write(run_batch, query, rows[i:i+BATCH_SIZE])


def main():
    if not NEO4J_PASSWORD:
        print("ERROR: Set NEO4J_PASSWORD environment variable before running.")
        print("  Example: NEO4J_PASSWORD=yourpassword python pipeline/04_export_neo4j.py")
        return

    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    print("  Connected.")

    print(f"\nLoading {IN_FILE}...")
    df = pl.read_parquet(IN_FILE)
    print(f"Loaded {len(df):,} events")

    create_constraints(driver)

    # --- Ingest Event nodes ---
    print("\nIngesting Event nodes...")
    event_rows = [
        {
            "id": str(row["GlobalEventID"]),
            "date": str(row["day"]),
            "eventCode": str(row["EventCode"]) if row["EventCode"] else "",
            "rootCode": str(row["EventRootCode"]) if row["EventRootCode"] else "",
            "quadClass": QUAD_CLASS.get(str(row["QuadClass"]), str(row["QuadClass"])),
            "goldstein": float(row["GoldsteinScale"]) if row["GoldsteinScale"] is not None else 0.0,
            "inDegree": int(row["causal_in_degree"]),
        }
        for row in df.iter_rows(named=True)
    ]
    ingest_events(driver, event_rows)
    print(f"  {len(event_rows):,} events ingested.")

    # --- Ingest Country nodes ---
    print("\nIngesting Country nodes...")
    all_country_codes = set()
    for col in ["Actor1CountryCode", "Actor2CountryCode", "ActionGeo_CountryCode"]:
        all_country_codes.update(df[col].drop_nulls().unique().to_list())
    ingest_countries(driver, all_country_codes)
    print(f"  {len(all_country_codes):,} countries ingested.")

    # --- Ingest Article nodes ---
    print("\nIngesting Article nodes...")
    article_rows = (
        df.filter(pl.col("SOURCEURL").is_not_null() & (pl.col("SOURCEURL") != ""))
        .select(["SOURCEURL"])
        .unique()
        .rename({"SOURCEURL": "url"})
        .with_columns(pl.lit("").alias("source"))
        .to_dicts()
    )
    ingest_articles(driver, article_rows)
    print(f"  {len(article_rows):,} articles ingested.")

    # --- Ingest all relationships ---
    print("\nIngesting event relationships (OCCURRED_IN, ACTOR1_IN, ACTOR2_IN, MENTIONED_IN)...")
    rel_rows = [
        {
            "event_id": str(row["GlobalEventID"]),
            "geo_country": str(row["ActionGeo_CountryCode"]) if row["ActionGeo_CountryCode"] else "",
            "actor1": str(row["Actor1Name"]) if row["Actor1Name"] else "",
            "actor2": str(row["Actor2Name"]) if row["Actor2Name"] else "",
            "url": str(row["SOURCEURL"]) if row["SOURCEURL"] else "",
        }
        for row in df.iter_rows(named=True)
    ]
    ingest_event_relationships(driver, rel_rows)
    print("  Done.")

    # --- Ingest causal edges ---
    print("\nIngesting PRECEDED_BY causal edges...")
    causal_rows = []
    for row in df.filter(pl.col("precursor_ids") != "").iter_rows(named=True):
        later_id = str(row["GlobalEventID"])
        for earlier_id in str(row["precursor_ids"]).split(","):
            earlier_id = earlier_id.strip()
            if earlier_id:
                causal_rows.append({"later_id": later_id, "earlier_id": earlier_id})

    if causal_rows:
        ingest_causal_edges(driver, causal_rows)
        print(f"  {len(causal_rows):,} causal edges ingested.")
    else:
        print("  No causal edges found.")

    driver.close()
    print("\nDone! Neo4j graph populated.")
    print("\nSample queries to try:")
    print("  // Events per country")
    print("  MATCH (e:Event)-[:OCCURRED_IN]->(c:Country) RETURN c.name, count(e) ORDER BY count(e) DESC")
    print("  // Causal chains (up to 3 hops)")
    print("  MATCH path=(e1:Event)-[:PRECEDED_BY*1..3]->(e2:Event) RETURN path LIMIT 25")
    print("  // Most active actors")
    print("  MATCH (a:Actor)-[:ACTOR1_IN]->(e:Event) RETURN a.name, count(e) as events ORDER BY events DESC LIMIT 20")


if __name__ == "__main__":
    main()
