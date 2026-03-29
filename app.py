"""
GDELT Knowledge Graph — FastAPI Backend
Run: uvicorn app:app --reload --port 8000
Then open: http://localhost:8000
"""

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import duckdb
import math

app = FastAPI(title="GDELT Intel API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

ROOT = Path(__file__).parent

# Use best available data file (step3 if URL-validated, else step2)
def _best_data():
    for name in ["step3_url_validated.parquet", "step2_causal_filtered.parquet"]:
        p = ROOT / "out" / name
        if p.exists():
            print(f"[GDELT] Using: {p.name}")
            return p
    raise FileNotFoundError("No processed parquet found. Run pipeline steps first.")

DATA_FILE = _best_data()

# ── Lookups ─────────────────────────────────────────────────────────────────
FIPS_NAME = {
    "US": "United States", "IS": "Israel",   "UP": "Palestine",
    "RS": "Russia",        "IN": "India",    "UK": "United Kingdom",
    "PK": "Pakistan",      "NI": "Nicaragua","DJ": "Djibouti", "AS": "Australia",
}
FIPS_FLAG = {
    "US": "🇺🇸", "IS": "🇮🇱", "UP": "🇵🇸", "RS": "🇷🇺", "IN": "🇮🇳",
    "UK": "🇬🇧", "PK": "🇵🇰", "NI": "🇳🇮", "DJ": "🇩🇯", "AS": "🇦🇺",
}
ISO_FIPS = {
    "USA":"US","ISR":"IS","PSE":"UP","RUS":"RS","IND":"IN",
    "GBR":"UK","PAK":"PK","NIC":"NI","DJI":"DJ","AUS":"AS",
}
TOP10 = list(FIPS_NAME.keys())
TOP10_SQL = ",".join(f"'{c}'" for c in TOP10)
QUAD_LABEL = {"1":"Verbal Cooperation","2":"Material Cooperation","3":"Verbal Conflict","4":"Material Conflict"}

# ── DB connection (lazy, reused) ─────────────────────────────────────────────
_con: duckdb.DuckDBPyConnection | None = None

def get_con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        _con = duckdb.connect()
        path = str(DATA_FILE).replace("\\", "/")
        _con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{path}')")
    return _con

def safe(s: str) -> str:
    return s.replace("'", "''")

# ── Helpers ──────────────────────────────────────────────────────────────────
def _country_filter(country: str, col: str = "ActionGeo_CountryCode") -> str:
    if not country:
        return f"AND {col} IN ({TOP10_SQL})"
    codes = ",".join(f"'{c.strip()}'" for c in country.split(",") if c.strip())
    return f"AND {col} IN ({codes})"

def _quad_filter(quad: str) -> str:
    return f"AND QuadClass = '{safe(quad)}'" if quad else ""

def _date_filter(date_from: int, date_to: int) -> str:
    return f"AND day >= {date_from} AND day <= {date_to}"

# ── Routes ───────────────────────────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(ROOT / "frontend" / "index.html")

# ── Stats ────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def stats():
    con = get_con()
    r = con.execute("""
        SELECT COUNT(*) AS total, MIN(day) AS d_from, MAX(day) AS d_to,
               COUNT(DISTINCT ActionGeo_CountryCode) AS countries
        FROM events
    """).fetchone()
    return {"total_events": r[0], "date_from": str(r[1]), "date_to": str(r[2]), "countries": r[3]}

# ── Graph ─────────────────────────────────────────────────────────────────────
@app.get("/api/graph")
async def graph(
    country: str = "",
    quad_class: str = "",
    date_from: int = 20240101,
    date_to: int = 20241231,
):
    con = get_con()
    cf = _country_filter(country)
    qf = _quad_filter(quad_class)
    df_range = _date_filter(date_from, date_to)

    # Node stats per country
    nodes_df = con.execute(f"""
        SELECT ActionGeo_CountryCode AS cc,
               COUNT(*) AS n,
               AVG(GoldsteinScale) AS avg_g,
               COUNT(CASE WHEN QuadClass IN ('3','4') THEN 1 END) AS n_conflict
        FROM events WHERE 1=1 {df_range} {cf} {qf}
        GROUP BY cc
    """).df()

    ROOT_CODE_SHORT = {
        "01":"STATEMENT","02":"APPEAL","03":"INTENT","04":"CONSULT","05":"DIPLOMACY",
        "06":"MAT·COOP","07":"AID","08":"YIELD","09":"INVESTIGATE","10":"DEMAND",
        "11":"DISAPPROVE","12":"REJECT","13":"THREATEN","14":"PROTEST","15":"MIL·POSTURE",
        "16":"REDUCE REL","17":"COERCE","18":"ASSAULT","19":"FIGHT","20":"MASS VIOLENCE",
    }

    # Edge stats with dominant EventRootCode per pair
    edges_df = con.execute(f"""
        WITH base AS (
            SELECT Actor1CountryCode AS c1, Actor2CountryCode AS c2,
                   QuadClass AS q, EventRootCode AS rc,
                   COUNT(*) AS n, AVG(GoldsteinScale) AS avg_g
            FROM events
            WHERE Actor1CountryCode IS NOT NULL AND Actor1CountryCode != ''
              AND Actor2CountryCode IS NOT NULL AND Actor2CountryCode != ''
              {df_range} {qf}
            GROUP BY c1, c2, q, rc
        ),
        pair_totals AS (
            SELECT c1, c2, SUM(n) AS total_n, AVG(avg_g) AS pair_avg_g
            FROM base GROUP BY c1, c2
        ),
        ranked AS (
            SELECT b.*, ROW_NUMBER() OVER (PARTITION BY b.c1, b.c2 ORDER BY b.n DESC) AS rn
            FROM base b
        )
        SELECT r.c1, r.c2, r.q AS dominant_q, r.rc AS dominant_rc,
               p.total_n, p.pair_avg_g
        FROM ranked r
        JOIN pair_totals p ON r.c1=p.c1 AND r.c2=p.c2
        WHERE r.rn = 1 AND p.total_n > 5
    """).df()

    nodes = []
    for _, r in nodes_df.iterrows():
        cc = r["cc"]
        nodes.append({
            "id": cc, "label": FIPS_NAME.get(cc, cc), "flag": FIPS_FLAG.get(cc, "🌍"),
            "event_count": int(r["n"]),
            "avg_goldstein": round(float(r["avg_g"]) if r["avg_g"] == r["avg_g"] else 0, 3),
            "conflict_ratio": round(int(r["n_conflict"]) / max(int(r["n"]), 1), 3),
        })

    edges = []
    for _, r in edges_df.iterrows():
        c1 = ISO_FIPS.get(str(r["c1"]), "")
        c2 = ISO_FIPS.get(str(r["c2"]), "")
        if not c1 or not c2 or c1 == c2 or c1 not in TOP10 or c2 not in TOP10:
            continue
        rc = str(r["dominant_rc"]).zfill(2) if r["dominant_rc"] else "01"
        edges.append({
            "source": c1, "target": c2,
            "event_count": int(r["total_n"]),
            "dominant_quad": str(r["dominant_q"]),
            "dominant_root": rc,
            "root_label": ROOT_CODE_SHORT.get(rc, rc),
            "avg_goldstein": round(float(r["pair_avg_g"]) if r["pair_avg_g"] == r["pair_avg_g"] else 0, 3),
        })

    return {"nodes": nodes, "edges": edges}

# ── Edge Detail ───────────────────────────────────────────────────────────────
@app.get("/api/edge-detail")
async def edge_detail(source: str = "", target: str = "", root_code: str = ""):
    """
    Returns rich context for a clicked graph edge:
    - CAMEO event description
    - Sample events (actors, dates, goldstein, URLs)
    - Preceding events that caused this interaction (causal chain)
    - Monthly frequency breakdown
    """
    con = get_con()

    CAMEO_FULL = {
        "01": ("Public Statement", "Both sides issued public declarations, speeches, or official statements regarding their relationship or a shared issue."),
        "02": ("Appeal", "One party formally appealed to the other — requesting action, change in policy, mediation, or international support."),
        "03": ("Intent to Cooperate", "Countries signaled willingness to cooperate, expressing shared goals or agreement in principle without committing material resources."),
        "04": ("Consult", "High-level consultations, meetings, or diplomatic talks took place between representatives of both countries."),
        "05": ("Diplomatic Cooperation", "Formal diplomatic cooperation occurred — joint communiqués, treaty negotiations, or coordinated foreign-policy positions."),
        "06": ("Material Cooperation", "Tangible, material cooperation: joint operations, shared infrastructure, economic agreements, or logistics collaboration."),
        "07": ("Provide Aid", "One country provided humanitarian, economic, military, or technical aid to the other."),
        "08": ("Yield", "One side made concessions, backed down from a position, or yielded to pressure from the other party."),
        "09": ("Investigate", "An investigation, inquiry, or fact-finding mission was launched concerning events involving both countries."),
        "10": ("Demand", "One country issued demands — formal or informal — requiring specific actions from the other party."),
        "11": ("Disapprove", "Official disapproval, criticism, or condemnation was expressed without escalating to formal sanctions or conflict."),
        "12": ("Reject", "One party formally rejected proposals, demands, agreements, or overtures from the other."),
        "13": ("Threaten", "Explicit or implicit threats were made — military, economic, or diplomatic — signaling potential escalation."),
        "14": ("Protest", "Public protests, demonstrations, or organized civil opposition targeted actions related to the other country."),
        "15": ("Military Posture", "Military forces were repositioned, exercises were conducted, or defensive/offensive postures were adopted near the other country."),
        "16": ("Reduce Relations", "Diplomatic relations were downgraded — ambassadors recalled, agreements suspended, or trade restricted."),
        "17": ("Coerce", "Economic sanctions, blockades, embargoes, or other coercive non-military measures were applied."),
        "18": ("Assault", "Physical assault, bombing, shelling, or targeted attacks were carried out against individuals or infrastructure."),
        "19": ("Fight", "Conventional armed fighting between military or paramilitary forces of both sides occurred."),
        "20": ("Mass Violence", "Massacres, genocide, or large-scale indiscriminate violence against civilians was reported."),
    }

    # Normalize root code
    rc = str(root_code).zfill(2)
    title, description = CAMEO_FULL.get(rc, ("Unknown Event", "No description available for this CAMEO code."))

    # Map FIPS source/target to ISO for actor lookup
    FIPS_ISO = {v: k for k, v in ISO_FIPS.items()}
    src_iso = FIPS_ISO.get(source, source)
    tgt_iso = FIPS_ISO.get(target, target)

    # ── Sample events for this country pair + root code ──────────────────
    sample_df = con.execute(f"""
        SELECT day, Actor1Name, Actor1CountryCode, Actor2Name, Actor2CountryCode,
               EventCode, EventRootCode, QuadClass, GoldsteinScale, SOURCEURL,
               causal_in_degree, precursor_ids
        FROM events
        WHERE EventRootCode = '{rc}'
          AND (
            (Actor1CountryCode = '{src_iso}' AND Actor2CountryCode = '{tgt_iso}')
            OR ActionGeo_CountryCode = '{source}'
          )
        ORDER BY ABS(GoldsteinScale) DESC, day DESC
        LIMIT 8
    """).df()

    samples = []
    for _, r in sample_df.iterrows():
        g = float(r["GoldsteinScale"]) if r["GoldsteinScale"] == r["GoldsteinScale"] else 0
        samples.append({
            "date":      str(int(r["day"])),
            "actor1":    str(r["Actor1Name"])  if r["Actor1Name"]  else "—",
            "actor2":    str(r["Actor2Name"])  if r["Actor2Name"]  else "—",
            "event_code":str(r["EventCode"])   if r["EventCode"]   else "",
            "quad":      str(r["QuadClass"])   if r["QuadClass"]   else "",
            "goldstein": round(g, 2),
            "url":       str(r["SOURCEURL"])   if r["SOURCEURL"]   else "",
            "causal_degree": int(r["causal_in_degree"]) if r["causal_in_degree"] == r["causal_in_degree"] else 0,
        })

    # ── Aggregate stats for this pair ────────────────────────────────────
    stats = con.execute(f"""
        SELECT COUNT(*) AS total,
               AVG(GoldsteinScale) AS avg_g,
               MIN(day) AS first_day,
               MAX(day) AS last_day,
               COUNT(CASE WHEN QuadClass='3' OR QuadClass='4' THEN 1 END) AS conflict_n,
               COUNT(CASE WHEN causal_in_degree > 0 THEN 1 END) AS has_cause_n
        FROM events
        WHERE EventRootCode = '{rc}'
          AND (Actor1CountryCode = '{src_iso}' OR ActionGeo_CountryCode = '{source}')
    """).fetchone()

    # ── Causal predecessors — event types that commonly precede this interaction ──
    # Strategy: find root codes that appear as causal_in_degree=0 events for the
    # same source country in the same months as our target event type
    # (lightweight proxy for "what triggers this")
    causes_df = con.execute(f"""
        WITH target_months AS (
            SELECT DISTINCT CAST(day/100 AS INTEGER) AS month
            FROM events
            WHERE EventRootCode = '{rc}'
              AND ActionGeo_CountryCode = '{source}'
            LIMIT 50
        )
        SELECT e.EventRootCode AS cause_rc, COUNT(*) AS n
        FROM events e
        JOIN target_months tm ON CAST(e.day/100 AS INTEGER) = tm.month
        WHERE e.ActionGeo_CountryCode = '{source}'
          AND e.causal_in_degree = 0
          AND e.EventRootCode IS NOT NULL
          AND e.EventRootCode != ''
          AND e.EventRootCode != '{rc}'
        GROUP BY cause_rc
        ORDER BY n DESC
        LIMIT 4
    """).df()

    causes = []
    for _, r in causes_df.iterrows():
        crc = str(r["cause_rc"]).zfill(2)
        ctitle, _ = CAMEO_FULL.get(crc, (crc, ""))
        causes.append({"root_code": crc, "label": ctitle, "count": int(r["n"]), "inferred": True})

    # ── Monthly frequency ────────────────────────────────────────────────
    monthly_df = con.execute(f"""
        SELECT CAST(day/100 AS INTEGER) AS month, COUNT(*) AS n
        FROM events
        WHERE EventRootCode = '{rc}'
          AND (Actor1CountryCode = '{src_iso}' OR ActionGeo_CountryCode = '{source}')
        GROUP BY month ORDER BY month
    """).df()

    monthly = [{"month": f"{str(int(r['month']))[:4]}-{str(int(r['month']))[4:]}", "count": int(r["n"])}
               for _, r in monthly_df.iterrows()]

    return {
        "source": source,
        "target": target,
        "root_code": rc,
        "event_title": title,
        "event_description": description,
        "stats": {
            "total":       int(stats[0]) if stats[0] else 0,
            "avg_goldstein": round(float(stats[1]) if stats[1] == stats[1] else 0, 2),
            "first_day":   str(int(stats[2])) if stats[2] else "",
            "last_day":    str(int(stats[3])) if stats[3] else "",
            "conflict_pct": round(int(stats[4]) / max(int(stats[0]), 1) * 100, 1),
            "causal_pct":  round(int(stats[5]) / max(int(stats[0]), 1) * 100, 1),
        },
        "samples": samples,
        "causes": causes,
        "monthly": monthly,
    }

# ── Timeline ─────────────────────────────────────────────────────────────────
@app.get("/api/timeline")
async def timeline(country: str = "", quad_class: str = ""):
    con = get_con()
    cf  = _country_filter(country)
    qf  = _quad_filter(quad_class)

    df = con.execute(f"""
        SELECT CAST(day / 100 AS INTEGER) AS month,
               QuadClass, COUNT(*) AS n, AVG(GoldsteinScale) AS avg_g
        FROM events WHERE 1=1 {cf} {qf}
        GROUP BY month, QuadClass ORDER BY month, QuadClass
    """).df()

    months = sorted(df["month"].unique().tolist())
    labels = [f"{str(m)[:4]}-{str(m)[4:]}" for m in months]
    m_idx  = {m: i for i, m in enumerate(months)}

    quad_data = {q: [0] * len(months) for q in ["1","2","3","4"]}
    gold_acc  = [[0.0, 0] for _ in months]  # [sum, count]

    for _, r in df.iterrows():
        idx = m_idx[int(r["month"])]
        q = str(r["QuadClass"])
        if q in quad_data:
            quad_data[q][idx] = int(r["n"])
        g = float(r["avg_g"]) if r["avg_g"] == r["avg_g"] else 0
        gold_acc[idx][0] += g * int(r["n"])
        gold_acc[idx][1] += int(r["n"])

    goldstein_trend = [
        round(g / max(n, 1), 3) for g, n in gold_acc
    ]

    return {"labels": labels, "quad_data": quad_data, "goldstein_trend": goldstein_trend}

# ── Country Stats ─────────────────────────────────────────────────────────────
@app.get("/api/country-stats")
async def country_stats():
    con = get_con()
    result = []
    for cc in TOP10:
        r = con.execute(f"""
            SELECT COUNT(*) AS n,
                   AVG(GoldsteinScale) AS avg_g,
                   COUNT(CASE WHEN QuadClass='1' THEN 1 END) AS q1,
                   COUNT(CASE WHEN QuadClass='2' THEN 1 END) AS q2,
                   COUNT(CASE WHEN QuadClass='3' THEN 1 END) AS q3,
                   COUNT(CASE WHEN QuadClass='4' THEN 1 END) AS q4
            FROM events WHERE ActionGeo_CountryCode = '{cc}'
        """).fetchone()

        trend = con.execute(f"""
            SELECT CAST(day/100 AS INTEGER) AS month, COUNT(*) AS cnt
            FROM events WHERE ActionGeo_CountryCode = '{cc}'
            GROUP BY month ORDER BY month
        """).df()

        total = int(r[0]) or 1
        result.append({
            "code": cc, "name": FIPS_NAME.get(cc, cc), "flag": FIPS_FLAG.get(cc, "🌍"),
            "total_events": int(r[0]),
            "avg_goldstein": round(float(r[1]) if r[1] == r[1] else 0, 3),
            "quad_breakdown": {"1": int(r[2]), "2": int(r[3]), "3": int(r[4]), "4": int(r[5])},
            "conflict_ratio": round((int(r[4]) + int(r[5])) / total, 3),
            "monthly_trend": trend["cnt"].tolist(),
        })

    return {"countries": sorted(result, key=lambda x: -x["total_events"])}

# ── Events (paginated) ────────────────────────────────────────────────────────
@app.get("/api/events")
async def events(
    search: str = "",
    country: str = "",
    quad_class: str = "",
    page: int = 1,
    limit: int = 50,
):
    con = get_con()
    filters = [f"ActionGeo_CountryCode IN ({TOP10_SQL})"]

    if country:
        codes = ",".join(f"'{c.strip()}'" for c in country.split(",") if c.strip())
        filters.append(f"ActionGeo_CountryCode IN ({codes})")
    if quad_class:
        filters.append(f"QuadClass = '{safe(quad_class)}'")
    if search:
        s = safe(search)
        filters.append(f"(Actor1Name ILIKE '%{s}%' OR Actor2Name ILIKE '%{s}%')")

    where = "WHERE " + " AND ".join(filters)
    total = con.execute(f"SELECT COUNT(*) FROM events {where}").fetchone()[0]
    offset = (page - 1) * limit

    df = con.execute(f"""
        SELECT GlobalEventID, day, Actor1Name, Actor1CountryCode,
               Actor2Name, Actor2CountryCode, EventCode, EventRootCode,
               QuadClass, GoldsteinScale, ActionGeo_CountryCode, SOURCEURL,
               causal_in_degree, precursor_ids
        FROM events {where}
        ORDER BY day DESC, GlobalEventID DESC
        LIMIT {limit} OFFSET {offset}
    """).df()

    evs = []
    for _, r in df.iterrows():
        evs.append({
            "id":          str(r["GlobalEventID"]),
            "date":        str(int(r["day"])),
            "actor1":      str(r["Actor1Name"])         if r["Actor1Name"]         else "",
            "actor1_cc":   str(r["Actor1CountryCode"])  if r["Actor1CountryCode"]  else "",
            "actor2":      str(r["Actor2Name"])         if r["Actor2Name"]         else "",
            "actor2_cc":   str(r["Actor2CountryCode"])  if r["Actor2CountryCode"]  else "",
            "event_code":  str(r["EventCode"])          if r["EventCode"]          else "",
            "root_code":   str(r["EventRootCode"])      if r["EventRootCode"]      else "",
            "quad_class":  str(r["QuadClass"])          if r["QuadClass"]          else "",
            "goldstein":   round(float(r["GoldsteinScale"]) if r["GoldsteinScale"] == r["GoldsteinScale"] else 0, 3),
            "geo_country": str(r["ActionGeo_CountryCode"]) if r["ActionGeo_CountryCode"] else "",
            "url":         str(r["SOURCEURL"])          if r["SOURCEURL"]          else "",
            "causal_degree": int(r["causal_in_degree"]) if r["causal_in_degree"] == r["causal_in_degree"] else 0,
            "precursor_ids": str(r["precursor_ids"])    if r["precursor_ids"]      else "",
        })

    return {"total": int(total), "page": page, "limit": limit, "events": evs}

# ── Heatmap ───────────────────────────────────────────────────────────────────
@app.get("/api/heatmap")
async def heatmap():
    con = get_con()

    df = con.execute("""
        SELECT Actor1CountryCode AS c1, Actor2CountryCode AS c2,
               COUNT(*) AS n, AVG(GoldsteinScale) AS avg_g
        FROM events
        WHERE Actor1CountryCode IS NOT NULL AND Actor1CountryCode != ''
          AND Actor2CountryCode IS NOT NULL AND Actor2CountryCode != ''
        GROUP BY c1, c2
    """).df()

    # Build 10×10 matrix
    matrix     = [[0]   * 10 for _ in range(10)]
    gold_matrix= [[0.0] * 10 for _ in range(10)]
    idx = {c: i for i, c in enumerate(TOP10)}

    for _, r in df.iterrows():
        c1 = ISO_FIPS.get(str(r["c1"]), "")
        c2 = ISO_FIPS.get(str(r["c2"]), "")
        if c1 in idx and c2 in idx:
            i, j = idx[c1], idx[c2]
            matrix[i][j]      += int(r["n"])
            gold_matrix[i][j]  = round(float(r["avg_g"]) if r["avg_g"] == r["avg_g"] else 0, 2)

    return {
        "countries":       TOP10,
        "names":           [FIPS_NAME.get(c, c)  for c in TOP10],
        "flags":           [FIPS_FLAG.get(c, "🌍") for c in TOP10],
        "count_matrix":    matrix,
        "goldstein_matrix": gold_matrix,
    }

# ── Serve frontend static assets if any ──────────────────────────────────────
if (ROOT / "frontend").exists():
    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
