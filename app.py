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
import os
import duckdb
import math

app = FastAPI(title="GDELT Intel API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.middleware("http")
async def cache_api(request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "public, max-age=0, s-maxage=31536000, stale-while-revalidate=86400"
    return resp


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
    "US": "United States", "IS": "Israel",   "UP": "Ukraine",
    "RS": "Russia",        "IN": "India",    "UK": "United Kingdom",
    "PK": "Pakistan",      "NI": "Nigeria",  "DJ": "Djibouti", "AS": "Australia",
}
FIPS_FLAG = {
    "US": "🇺🇸", "IS": "🇮🇱", "UP": "🇺🇦", "RS": "🇷🇺", "IN": "🇮🇳",
    "UK": "🇬🇧", "PK": "🇵🇰", "NI": "🇳🇬", "DJ": "🇩🇯", "AS": "🇦🇺",
}
ISO_FIPS = {
    "USA":"US","ISR":"IS","UKR":"UP","RUS":"RS","IND":"IN",
    "GBR":"UK","PAK":"PK","NGA":"NI","DJI":"DJ","AUS":"AS",
}
TOP10 = list(FIPS_NAME.keys())
TOP10_SQL = ",".join(f"'{c}'" for c in TOP10)
QUAD_LABEL = {"1":"Verbal Cooperation","2":"Material Cooperation","3":"Verbal Conflict","4":"Material Conflict"}

# ── DB connection (lazy, reused) ─────────────────────────────────────────────
_con: duckdb.DuckDBPyConnection | None = None

def get_con() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        # Vercel: only /tmp is writable, and DuckDB sizes itself from the host's
        # /proc/meminfo rather than the container's cgroup limit -- left alone it
        # over-commits RAM and the function gets OOM-killed.
        cfg = {"memory_limit": "1GB", "threads": "1",
               "temp_directory": "/tmp", "home_directory": "/tmp"} if os.environ.get("VERCEL") else {}
        _con = duckdb.connect(config=cfg)
        path = str(DATA_FILE).replace("\\", "/")
        _con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{path}')")
    return _con

def num(v, default=0.0) -> float:
    """AVG() over zero rows is SQL NULL, which reaches us as None from
    fetchone() tuples and as NaN from _rows() dicts. Guard both."""
    return default if v is None or v != v else float(v)


def safe(s: str) -> str:
    return s.replace("'", "''")

# DuckDB rows as dicts. SQL NULL -> NaN in numeric columns so the `x == x`
# guards below keep behaving exactly as they did with pandas DataFrames.
_NUMERIC = {"TINYINT","SMALLINT","INTEGER","BIGINT","HUGEINT","UTINYINT","USMALLINT",
            "UINTEGER","UBIGINT","FLOAT","DOUBLE","DECIMAL","REAL"}

def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    numeric = {i for i, d in enumerate(cur.description)
               if str(d[1]).split("(")[0] in _NUMERIC}
    nan = float("nan")
    return [
        {c: (nan if (i in numeric and v is None) else v)
         for i, (c, v) in enumerate(zip(cols, row))}
        for row in cur.fetchall()
    ]

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
    date_from: int = 19790101,
    date_to: int = 20991231,
):
    con = get_con()
    cf = _country_filter(country)
    qf = _quad_filter(quad_class)
    df_range = _date_filter(date_from, date_to)

    # Node stats per country
    nodes_df = _rows(con.execute(f"""
        SELECT ActionGeo_CountryCode AS cc,
               COUNT(*) AS n,
               AVG(GoldsteinScale) AS avg_g,
               COUNT(CASE WHEN QuadClass IN ('3','4') THEN 1 END) AS n_conflict
        FROM events WHERE 1=1 {df_range} {cf} {qf}
        GROUP BY cc
        ORDER BY cc
    """))

    ROOT_CODE_SHORT = {
        "01":"STATEMENT","02":"APPEAL","03":"INTENT","04":"CONSULT","05":"DIPLOMACY",
        "06":"MAT·COOP","07":"AID","08":"YIELD","09":"INVESTIGATE","10":"DEMAND",
        "11":"DISAPPROVE","12":"REJECT","13":"THREATEN","14":"PROTEST","15":"MIL·POSTURE",
        "16":"REDUCE REL","17":"COERCE","18":"ASSAULT","19":"FIGHT","20":"MASS VIOLENCE",
    }

    # Edge stats with dominant EventRootCode per pair
    edges_df = _rows(con.execute(f"""
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
            SELECT b.*, ROW_NUMBER() OVER (PARTITION BY b.c1, b.c2 ORDER BY b.n DESC, b.rc) AS rn
            FROM base b
        )
        SELECT r.c1, r.c2, r.q AS dominant_q, r.rc AS dominant_rc,
               p.total_n, p.pair_avg_g
        FROM ranked r
        JOIN pair_totals p ON r.c1=p.c1 AND r.c2=p.c2
        WHERE r.rn = 1 AND p.total_n > 5
        ORDER BY r.c1, r.c2
    """))

    nodes = []
    for r in nodes_df:
        cc = r["cc"]
        nodes.append({
            "id": cc, "label": FIPS_NAME.get(cc, cc), "flag": FIPS_FLAG.get(cc, "🌍"),
            "event_count": int(r["n"]),
            "avg_goldstein": round(num(r["avg_g"]), 3),
            "conflict_ratio": round(int(r["n_conflict"]) / max(int(r["n"]), 1), 3),
        })

    edges = []
    for r in edges_df:
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
            "avg_goldstein": round(num(r["pair_avg_g"]), 3),
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
    sample_df = _rows(con.execute(f"""
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
    """))

    samples = []
    for r in sample_df:
        g = num(r["GoldsteinScale"])
        samples.append({
            "date":      str(int(r["day"])),
            "actor1":    str(r["Actor1Name"])  if r["Actor1Name"]  else "—",
            "actor2":    str(r["Actor2Name"])  if r["Actor2Name"]  else "—",
            "event_code":str(r["EventCode"])   if r["EventCode"]   else "",
            "quad":      str(r["QuadClass"])   if r["QuadClass"]   else "",
            "goldstein": round(g, 2),
            "url":       str(r["SOURCEURL"])   if r["SOURCEURL"]   else "",
            "causal_degree": int(num(r["causal_in_degree"])),
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
    causes_df = _rows(con.execute(f"""
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
    """))

    causes = []
    for r in causes_df:
        crc = str(r["cause_rc"]).zfill(2)
        ctitle, _ = CAMEO_FULL.get(crc, (crc, ""))
        causes.append({"root_code": crc, "label": ctitle, "count": int(r["n"]), "inferred": True})

    # ── Monthly frequency ────────────────────────────────────────────────
    monthly_df = _rows(con.execute(f"""
        SELECT CAST(day/100 AS INTEGER) AS month, COUNT(*) AS n
        FROM events
        WHERE EventRootCode = '{rc}'
          AND (Actor1CountryCode = '{src_iso}' OR ActionGeo_CountryCode = '{source}')
        GROUP BY month ORDER BY month
    """))

    monthly = [{"month": f"{str(int(r['month']))[:4]}-{str(int(r['month']))[4:]}", "count": int(r["n"])}
               for r in monthly_df]

    return {
        "source": source,
        "target": target,
        "root_code": rc,
        "event_title": title,
        "event_description": description,
        "stats": {
            "total":       int(stats[0]) if stats[0] else 0,
            "avg_goldstein": round(num(stats[1]), 2),
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

    df = _rows(con.execute(f"""
        SELECT CAST(day / 100 AS INTEGER) AS month,
               QuadClass, COUNT(*) AS n, AVG(GoldsteinScale) AS avg_g
        FROM events WHERE 1=1 {cf} {qf}
        GROUP BY month, QuadClass ORDER BY month, QuadClass
    """))

    months = sorted({r["month"] for r in df})
    labels = [f"{str(m)[:4]}-{str(m)[4:]}" for m in months]
    m_idx  = {m: i for i, m in enumerate(months)}

    quad_data = {q: [0] * len(months) for q in ["1","2","3","4"]}
    gold_acc  = [[0.0, 0] for _ in months]  # [sum, count]

    for r in df:
        idx = m_idx[int(r["month"])]
        q = str(r["QuadClass"])
        if q in quad_data:
            quad_data[q][idx] = int(r["n"])
        g = num(r["avg_g"])
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

        trend = _rows(con.execute(f"""
            SELECT CAST(day/100 AS INTEGER) AS month, COUNT(*) AS cnt
            FROM events WHERE ActionGeo_CountryCode = '{cc}'
            GROUP BY month ORDER BY month
        """))

        total = int(r[0]) or 1
        result.append({
            "code": cc, "name": FIPS_NAME.get(cc, cc), "flag": FIPS_FLAG.get(cc, "🌍"),
            "total_events": int(r[0]),
            "avg_goldstein": round(num(r[1]), 3),
            "quad_breakdown": {"1": int(r[2]), "2": int(r[3]), "3": int(r[4]), "4": int(r[5])},
            "conflict_ratio": round((int(r[4]) + int(r[5])) / total, 3),
            "monthly_trend": [r["cnt"] for r in trend],
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

    df = _rows(con.execute(f"""
        SELECT GlobalEventID, day, Actor1Name, Actor1CountryCode,
               Actor2Name, Actor2CountryCode, EventCode, EventRootCode,
               QuadClass, GoldsteinScale, ActionGeo_CountryCode, SOURCEURL,
               causal_in_degree, precursor_ids
        FROM events {where}
        ORDER BY day DESC, GlobalEventID DESC
        LIMIT {limit} OFFSET {offset}
    """))

    evs = []
    for r in df:
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
            "goldstein":   round(num(r["GoldsteinScale"]), 3),
            "geo_country": str(r["ActionGeo_CountryCode"]) if r["ActionGeo_CountryCode"] else "",
            "url":         str(r["SOURCEURL"])          if r["SOURCEURL"]          else "",
            "causal_degree": int(num(r["causal_in_degree"])),
            "precursor_ids": str(r["precursor_ids"])    if r["precursor_ids"]      else "",
        })

    return {"total": int(total), "page": page, "limit": limit, "events": evs}

# ── Heatmap ───────────────────────────────────────────────────────────────────
@app.get("/api/heatmap")
async def heatmap():
    con = get_con()

    df = _rows(con.execute("""
        SELECT Actor1CountryCode AS c1, Actor2CountryCode AS c2,
               COUNT(*) AS n, AVG(GoldsteinScale) AS avg_g
        FROM events
        WHERE Actor1CountryCode IS NOT NULL AND Actor1CountryCode != ''
          AND Actor2CountryCode IS NOT NULL AND Actor2CountryCode != ''
        GROUP BY c1, c2
    """))

    # Build 10×10 matrix
    matrix     = [[0]   * 10 for _ in range(10)]
    gold_matrix= [[0.0] * 10 for _ in range(10)]
    idx = {c: i for i, c in enumerate(TOP10)}

    for r in df:
        c1 = ISO_FIPS.get(str(r["c1"]), "")
        c2 = ISO_FIPS.get(str(r["c2"]), "")
        if c1 in idx and c2 in idx:
            i, j = idx[c1], idx[c2]
            matrix[i][j]      += int(r["n"])
            gold_matrix[i][j]  = round(num(r["avg_g"]), 2)

    return {
        "countries":       TOP10,
        "names":           [FIPS_NAME.get(c, c)  for c in TOP10],
        "flags":           [FIPS_FLAG.get(c, "🌍") for c in TOP10],
        "count_matrix":    matrix,
        "goldstein_matrix": gold_matrix,
    }


# ── Causal Evidence (two-stage scoring demo) ─────────────────────────────────
# Scores candidate causes for one event across the evidence channels that are
# computable from the shipped parquet. Channels needing article text (direct
# quotation, denial) have no corpus here and report as unavailable rather than
# being silently scored zero -- see CHANNEL_META below.
#
# "Present" for a root code on a day means an unusually active day for that
# code: daily count above its own 75th percentile. Raw presence is useless at
# day granularity because common codes fire nearly every day in a busy country.

CAUSAL_WINDOW_DAYS = 7
CAUSAL_FLOOR = 0.08
MIN_GROUP_EVENTS = 3          # a (day, type) group below this is too thin to score          # below this a candidate is scored but not drawn

# Illustrative weights. In the real design these are fitted on the Stage 1
# labelled decisions; there is no labelled set in this repo, so they are fixed
# and the UI says so.
CAUSAL_W = {
    "documented":    2.6,
    "corroboration": 1.4,
    "prior":         1.1,
    "contrastive":   1.3,
    "actors":        0.9,
    "contradiction": -3.0,
}
CAUSAL_INTERCEPT = -3.2

CHANNEL_META = [
    {"key": "documented",    "label": "Reporter stated it",  "available": True,
     "note": "Proxied by the pipeline's own precursor links"},
    {"key": "corroboration", "label": "Independent outlets",  "available": True,
     "note": "Distinct source domains reporting the group"},
    {"key": "prior",         "label": "Usual pattern",        "available": True,
     "note": "Lift of effect type after cause type"},
    {"key": "contrastive",   "label": "What happened else",   "available": True,
     "note": "Sufficiency and necessity over spike days"},
    {"key": "actors",        "label": "Same people",          "available": True,
     "note": "Shared actor tokens, rare tokens weighted"},
    {"key": "contradiction", "label": "Anyone denied it",     "available": False,
     "note": "Needs article text -- no corpus in this build"},
]

ROOT_LABEL = {
    "01": "Public Statement", "02": "Appeal", "03": "Intent to Cooperate",
    "04": "Consult", "05": "Diplomatic Cooperation", "06": "Material Cooperation",
    "07": "Provide Aid", "08": "Yield", "09": "Investigate", "10": "Demand",
    "11": "Disapprove", "12": "Reject", "13": "Threaten", "14": "Protest",
    "15": "Military Posture", "16": "Reduce Relations", "17": "Coerce",
    "18": "Assault", "19": "Fight", "20": "Mass Violence",
}

# Actor tokens so common they carry no information about a specific link.
_STOP_ACTORS = {
    "THE", "AND", "FOR", "OF", "A", "AN", "IN", "ON", "TO",
    "GOVERNMENT", "PRESIDENT", "MINISTER", "OFFICIAL", "OFFICIALS",
    "AUTHORITY", "AUTHORITIES", "POLICE", "MILITARY", "COUNTRY", "STATE",
}


def _logistic(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _cc_or_default(country: str) -> str:
    cc = (country or "IN").strip().upper()
    return cc if cc in TOP10 else "IN"


def _causal_matrix_rows(con, cc: str) -> list[dict]:
    """Type-pair statistics for one country, computed on spike days."""
    return _rows(con.execute(f"""
        WITH agg AS (
            SELECT COALESCE(NULLIF(EventRootCode, ''), '00') AS rc,
                   day AS dnum, COUNT(*) AS n
            FROM events
            WHERE ActionGeo_CountryCode = '{safe(cc)}'
            GROUP BY rc, dnum
        ),
        thr AS (
            SELECT rc, quantile_cont(n, 0.75) AS t, COUNT(*) AS obs_days
            FROM agg GROUP BY rc
        ),
        pres AS (
            SELECT a.rc AS rc,
                   strptime(CAST(a.dnum AS VARCHAR), '%Y%m%d')::DATE AS d
            FROM agg a JOIN thr ON thr.rc = a.rc
            WHERE a.n > thr.t
        ),
        span AS (SELECT COUNT(DISTINCT d) AS total_days FROM pres),
        tot AS (SELECT rc, COUNT(DISTINCT d) AS spike_days FROM pres GROUP BY rc),
        joined AS (
            SELECT c.rc AS crc, e.rc AS erc, c.d AS cd, e.d AS ed
            FROM pres c JOIN pres e
              ON e.d > c.d AND e.d <= c.d + INTERVAL {CAUSAL_WINDOW_DAYS} DAY
        ),
        pair AS (
            SELECT crc, erc,
                   COUNT(DISTINCT cd) AS cause_hits,
                   COUNT(DISTINCT ed) AS effect_hits
            FROM joined GROUP BY crc, erc
        )
        SELECT p.crc, p.erc, p.cause_hits, p.effect_hits,
               ct.spike_days AS cause_days, et.spike_days AS effect_days,
               s.total_days
        FROM pair p
        JOIN tot ct ON ct.rc = p.crc
        JOIN tot et ON et.rc = p.erc
        CROSS JOIN span s
        ORDER BY p.crc, p.erc
    """))


def _matrix_index(rows: list[dict]) -> dict:
    """(cause_rc, effect_rc) -> {sufficiency, necessity, lift}"""
    idx = {}
    for r in rows:
        cause_days  = max(int(num(r["cause_days"])), 1)
        effect_days = max(int(num(r["effect_days"])), 1)
        total_days  = max(int(num(r["total_days"])), 1)
        suff = int(num(r["cause_hits"]))  / cause_days
        nec  = int(num(r["effect_hits"])) / effect_days
        base = effect_days / total_days
        idx[(str(r["crc"]), str(r["erc"]))] = {
            "sufficiency": round(suff, 4),
            "necessity":   round(nec, 4),
            "lift":        round(suff / base, 4) if base > 0 else 0.0,
            "cause_days":  cause_days,
            "effect_days": effect_days,
        }
    return idx


def _actor_tokens(*names) -> set:
    out = set()
    for n in names:
        if not n:
            continue
        for tok in str(n).replace(",", " ").split():
            tok = tok.strip().upper()
            if len(tok) > 2 and tok not in _STOP_ACTORS:
                out.add(tok)
    return out


@app.get("/api/causal/seeds")
async def causal_seeds(country: str = "IN", limit: int = 12):
    """Target events worth explaining: conflict-heavy days with real precursors."""
    con = get_con()
    cc = _cc_or_default(country)
    limit = max(1, min(int(limit), 40))

    df = _rows(con.execute(f"""
        SELECT GlobalEventID, day, EventCode, EventRootCode, QuadClass,
               GoldsteinScale, Actor1Name, Actor2Name, SOURCEURL, precursor_ids
        FROM events
        WHERE ActionGeo_CountryCode = '{safe(cc)}'
          AND COALESCE(NULLIF(EventRootCode, ''), '') <> ''
          AND precursor_ids <> ''
          AND day > 20240108
        ORDER BY ABS(GoldsteinScale) DESC, day DESC, GlobalEventID DESC
        LIMIT {limit}
    """))

    seeds = []
    for r in df:
        rc = str(r["EventRootCode"]).zfill(2)
        seeds.append({
            "id":        str(int(num(r["GlobalEventID"]))),
            "date":      str(int(num(r["day"]))),
            "root_code": rc,
            "root_label": ROOT_LABEL.get(rc, rc),
            "quad":      str(r["QuadClass"]) if r["QuadClass"] else "",
            "goldstein": round(num(r["GoldsteinScale"]), 2),
            "actor1":    str(r["Actor1Name"]) if r["Actor1Name"] else "",
            "actor2":    str(r["Actor2Name"]) if r["Actor2Name"] else "",
            "url":       str(r["SOURCEURL"]) if r["SOURCEURL"] else "",
        })
    return {"country": cc, "name": FIPS_NAME.get(cc, cc),
            "flag": FIPS_FLAG.get(cc, "🌍"), "seeds": seeds}


@app.get("/api/causal/matrix")
async def causal_matrix(country: str = "IN"):
    """Type-level prior: which event types precede which, for one country."""
    con = get_con()
    cc = _cc_or_default(country)
    rows = _causal_matrix_rows(con, cc)

    pairs = []
    for r in rows:
        crc, erc = str(r["crc"]), str(r["erc"])
        cause_days  = max(int(num(r["cause_days"])), 1)
        effect_days = max(int(num(r["effect_days"])), 1)
        total_days  = max(int(num(r["total_days"])), 1)
        suff = int(num(r["cause_hits"])) / cause_days
        nec  = int(num(r["effect_hits"])) / effect_days
        base = effect_days / total_days
        pairs.append({
            "cause": crc, "cause_label": ROOT_LABEL.get(crc, crc),
            "effect": erc, "effect_label": ROOT_LABEL.get(erc, erc),
            "sufficiency": round(suff, 3),
            "necessity":   round(nec, 3),
            "lift":        round(suff / base, 3) if base > 0 else 0.0,
            "cause_days":  cause_days,
            "effect_days": effect_days,
        })

    pairs = [p for p in pairs if p["cause"] != p["effect"]]
    pairs.sort(key=lambda p: (-p["lift"], p["cause"], p["effect"]))
    return {
        "country": cc, "name": FIPS_NAME.get(cc, cc), "flag": FIPS_FLAG.get(cc, "🌍"),
        "window_days": CAUSAL_WINDOW_DAYS,
        "pairs": pairs[:40],
    }


@app.get("/api/causal/score")
async def causal_score(event_id: str = "", country: str = "IN"):
    """Six-channel scoring of every candidate cause for one target event."""
    con = get_con()
    cc = _cc_or_default(country)

    eid = "".join(ch for ch in str(event_id) if ch.isdigit())
    if not eid:
        return {"error": "no_event", "channels": CHANNEL_META, "target": None,
                "candidates": [], "coverage": 0.0}

    tgt = con.execute(f"""
        SELECT GlobalEventID, day, EventRootCode, QuadClass, GoldsteinScale,
               Actor1Name, Actor2Name, SOURCEURL, precursor_ids
        FROM events
        WHERE GlobalEventID = {eid}
        ORDER BY day, GlobalEventID
        LIMIT 1
    """).fetchone()

    if tgt is None:
        return {"error": "not_found", "channels": CHANNEL_META, "target": None,
                "candidates": [], "coverage": 0.0}

    t_day  = int(num(tgt[1]))
    t_rc   = str(tgt[2]).zfill(2) if tgt[2] else "00"
    t_prec = str(tgt[8]) if tgt[8] else ""
    t_tokens = _actor_tokens(tgt[5], tgt[6])

    target = {
        "id":         str(int(num(tgt[0]))),
        "date":       str(t_day),
        "root_code":  t_rc,
        "root_label": ROOT_LABEL.get(t_rc, t_rc),
        "quad":       str(tgt[3]) if tgt[3] else "",
        "goldstein":  round(num(tgt[4]), 2),
        "actor1":     str(tgt[5]) if tgt[5] else "",
        "actor2":     str(tgt[6]) if tgt[6] else "",
        "url":        str(tgt[7]) if tgt[7] else "",
    }

    # Which (day, root code) groups the pipeline already linked as precursors.
    documented_groups = set()
    prec_ids = [p.strip() for p in t_prec.split(",") if p.strip().isdigit()][:20]
    if prec_ids:
        id_list = ",".join(prec_ids)
        for r in _rows(con.execute(f"""
            SELECT day, COALESCE(NULLIF(EventRootCode, ''), '00') AS rc
            FROM events
            WHERE GlobalEventID IN ({id_list})
            ORDER BY day, rc
        """)):
            documented_groups.add((int(num(r["day"])), str(r["rc"]).zfill(2)))

    # Longer actor tokens are rarer and therefore more informative than short
    # ones, so use them as a cheap stand-in for inverse document frequency.
    probe = sorted(t_tokens, key=lambda x: (-len(x), x))[:3]
    if probe:
        actor_pred = " OR ".join(
            f"Actor1Name ILIKE '%{safe(tok)}%' OR Actor2Name ILIKE '%{safe(tok)}%'"
            for tok in probe)
    else:
        actor_pred = "FALSE"

    # Candidate groups: one per (day, root code) in the preceding window.
    lo = t_day - CAUSAL_WINDOW_DAYS
    cands = _rows(con.execute(f"""
        SELECT day,
               COALESCE(NULLIF(EventRootCode, ''), '00') AS rc,
               COUNT(*) AS n,
               COUNT(DISTINCT regexp_extract(SOURCEURL, '://([^/]+)', 1)) AS domains,
               AVG(GoldsteinScale) AS avg_g,
               MIN(GlobalEventID) AS rep_id,
               COUNT(*) FILTER (WHERE {actor_pred}) AS actor_hits
        FROM events
        WHERE ActionGeo_CountryCode = '{safe(cc)}'
          AND day >= {lo} AND day < {t_day}
        GROUP BY day, rc
        ORDER BY day DESC, rc
    """))

    raw_events = int(num(con.execute(f"""
        SELECT COUNT(*) FROM events
        WHERE ActionGeo_CountryCode = '{safe(cc)}'
          AND day >= {lo} AND day < {t_day}
    """).fetchone()[0]))

    n_groups = len(cands)
    cands = [r for r in cands if int(num(r["n"])) >= MIN_GROUP_EVENTS]

    midx = _matrix_index(_causal_matrix_rows(con, cc))

    scored = []
    for r in cands:
        c_day = int(num(r["day"]))
        c_rc  = str(r["rc"]).zfill(2)
        stat  = midx.get((c_rc, t_rc), {})

        # Lift of 8+ is a strong type-level signal; below ~2 is noise.
        prior = min(max((num(stat.get("lift")) - 1.0) / 7.0, 0.0), 1.0)

        # Sufficiency carries most of the weight. Necessity alone is vacuous for
        # common types -- "every riot had a statement beforehand" is true of
        # almost any pair, because statements fire constantly.
        suff = max(num(stat.get("sufficiency")), 0.0)
        nec  = max(num(stat.get("necessity")), 0.0)
        contrastive = min(0.75 * suff + 0.25 * nec, 1.0)

        # Share of the group's events naming an actor the target also names.
        n_events = max(int(num(r["n"])), 1)
        actors = min(int(num(r["actor_hits"])) / n_events, 1.0)

        # Log scale: 40+ distinct domains is saturation, 8 is unremarkable.
        domains = int(num(r["domains"]))
        corroboration = min(math.log1p(domains) / math.log1p(40), 1.0)

        documented = 1.0 if (c_day, c_rc) in documented_groups else 0.0
        contradiction = 0.0            # no article text in this build

        ch = {
            "documented":    round(documented, 3),
            "corroboration": round(corroboration, 3),
            "prior":         round(prior, 3),
            "contrastive":   round(contrastive, 3),
            "actors":        round(actors, 3),
            "contradiction": round(contradiction, 3),
        }
        z = CAUSAL_INTERCEPT + sum(CAUSAL_W[k] * ch[k] for k in CAUSAL_W)
        conf = _logistic(z)

        # Every intermediate, so a reader can re-derive the number by hand
        # instead of taking the endpoint's word for it.
        lift = num(stat.get("lift"))
        why = [
            {"key": "documented", "score": round(documented, 3),
             "detail": (f"precursor group ({c_day}, {c_rc}) is in the pipeline's own links"
                        if documented >= 0.5 else
                        f"({c_day}, {c_rc}) not among the recorded precursors")},
            {"key": "corroboration", "score": round(corroboration, 3),
             "detail": f"log1p({domains}) / log1p(40) — {domains} distinct source domains"},
            {"key": "prior", "score": round(prior, 3),
             "detail": (f"lift {lift:.3f} → (lift − 1) / 7 · "
                        f"{int(num(stat.get('cause_days')))} cause spike days, "
                        f"{int(num(stat.get('effect_days')))} effect spike days")},
            {"key": "contrastive", "score": round(contrastive, 3),
             "detail": f"0.75 × sufficiency {suff:.3f} + 0.25 × necessity {nec:.3f}"},
            {"key": "actors", "score": round(actors, 3),
             "detail": (f"{int(num(r['actor_hits']))} of {n_events} events name a target token"
                        + (f" {probe}" if probe else " (target has no usable tokens)"))},
            {"key": "contradiction", "score": 0.0,
             "detail": "no article corpus in this build — reported unavailable, not scored 0"},
        ]
        terms = [{"key": k, "score": ch[k], "weight": CAUSAL_W[k],
                  "contribution": round(CAUSAL_W[k] * ch[k], 3)} for k in CAUSAL_W]

        pattern_strength = (prior + contrastive + actors) / 3.0
        if documented >= 0.5 and corroboration >= 0.5:
            grade = "confirmed"
            rule = "documented ≥ 0.5 AND corroboration ≥ 0.5"
        elif documented >= 0.5:
            grade = "reported"
            rule = (f"documented ≥ 0.5, but corroboration {corroboration:.3f} < 0.5 "
                    f"— one bar short of confirmed")
        elif pattern_strength >= 0.45 and suff >= 0.30:
            grade = "pattern"
            rule = (f"not documented, but pattern strength {pattern_strength:.3f} ≥ 0.45 "
                    f"and sufficiency {suff:.3f} ≥ 0.30")
        elif conf >= CAUSAL_FLOOR:
            grade = "weak"
            rule = (f"pattern strength {pattern_strength:.3f} below 0.45 "
                    f"— above the {CAUSAL_FLOOR} floor but nothing carries it")
        else:
            grade = "dropped"
            rule = f"confidence below the {CAUSAL_FLOOR} floor"

        scored.append({
            "group_id":    f"{c_day}-{c_rc}",
            "_rc":         c_rc,
            "rep_id":      str(int(num(r["rep_id"]))),
            "date":        str(c_day),
            "lag_days":    max(t_day - c_day, 0),
            "root_code":   c_rc,
            "root_label":  ROOT_LABEL.get(c_rc, c_rc),
            "event_count": int(num(r["n"])),
            "domains":     domains,
            "avg_goldstein": round(num(r["avg_g"]), 2),
            "actor_hits":  int(num(r["actor_hits"])),
            "channels":    ch,
            "confidence":  round(conf, 4),
            "grade":       grade,
            "sufficiency": round(num(stat.get("sufficiency")), 3),
            "necessity":   round(num(stat.get("necessity")), 3),
            "lift":        round(num(stat.get("lift")), 3),
            "trace": {
                "why":        why,
                "terms":      terms,
                "intercept":  CAUSAL_INTERCEPT,
                "z":          round(z, 3),
                "grade_rule": rule,
                # Same code both sides: cause and effect spike days are the same
                # set, so sufficiency and necessity are structurally identical
                # and this channel measures recurrence, not a distinct relation.
                "self_pair":  c_rc == t_rc,
            },
        })

    # The same event type recurring on five different days is one candidate
    # cause seen five times, not five causes. Keep each type at its best lag.
    scored.sort(key=lambda c: (-c["confidence"], c["lag_days"], c["date"], c["root_code"]))
    best = {}
    for c in scored:
        best.setdefault(c["_rc"], c)
    scored = sorted(best.values(),
                    key=lambda c: (-c["confidence"], c["lag_days"], c["root_code"]))
    for c in scored:
        c.pop("_rc", None)

    counts = {}
    for c in scored:
        counts[c["grade"]] = counts.get(c["grade"], 0) + 1

    # How much of the explanation rests on links we would actually stand behind.
    kept = [c for c in scored if c["grade"] in ("confirmed", "reported", "pattern")]
    coverage = (sum(c["confidence"] for c in kept) /
                sum(c["confidence"] for c in scored)) if scored else 0.0

    return {
        "country":    cc,
        "target":     target,
        "retrieval": {
            "window_from": lo, "window_to": t_day,
            "raw_events":  raw_events,
            "groups":      n_groups,
            "kept":        len(cands),
            "deduped":     len(scored),
            "min_group":   MIN_GROUP_EVENTS,
            "actor_probe": probe,
        },
        "channels":   CHANNEL_META,
        "weights":    CAUSAL_W,
        "intercept":  CAUSAL_INTERCEPT,
        "window_days": CAUSAL_WINDOW_DAYS,
        "candidates": scored[:14],
        "grade_counts": counts,
        "coverage":   round(coverage, 3),
        "calibrated": False,
    }

# ── Serve frontend static assets if any ──────────────────────────────────────
if (ROOT / "frontend").exists():
    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
