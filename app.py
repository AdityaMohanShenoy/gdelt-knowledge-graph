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

import scoring
from scoring.sql import num, rows, safe

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

# num/safe/_rows live in scoring.sql so the package does not import the app.
_rows = rows

# app.py owned these until P3.1 moved them into scoring/. Re-exported so one
# import surface keeps working — test_app.py is the deploy gate and the plan
# requires it to pass unchanged.
_token_idf = scoring.token_idf
_pick_probes = scoring.pick_probes
ACTOR_PROBES = scoring.ACTOR_PROBES
ACTOR_MAX_SHARE = scoring.ACTOR_MAX_SHARE

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
# being silently scored zero -- see scoring.CHANNEL_META below.
#
def _cc_or_default(country: str) -> str:
    cc = (country or "IN").strip().upper()
    return cc if cc in TOP10 else "IN"


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
            "root_label": scoring.ROOT_LABEL.get(rc, rc),
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
    rows = scoring.matrix_rows(con, cc)

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
            "cause": crc, "cause_label": scoring.ROOT_LABEL.get(crc, crc),
            "effect": erc, "effect_label": scoring.ROOT_LABEL.get(erc, erc),
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
        "window_days": scoring.CAUSAL_WINDOW_DAYS,
        "pairs": pairs[:40],
    }


@app.get("/api/causal/score")
async def causal_score(event_id: str = "", country: str = "IN"):
    """Six-channel scoring of every candidate cause for one target event."""
    con = get_con()
    cc = _cc_or_default(country)

    eid = "".join(ch for ch in str(event_id) if ch.isdigit())
    if not eid:
        return {"error": "no_event", "channels": scoring.CHANNEL_META, "target": None,
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
        return {"error": "not_found", "channels": scoring.CHANNEL_META, "target": None,
                "candidates": [], "coverage": 0.0}

    t_day  = int(num(tgt[1]))
    t_rc   = str(tgt[2]).zfill(2) if tgt[2] else "00"
    t_prec = str(tgt[8]) if tgt[8] else ""
    t_tokens = scoring.actor_tokens(tgt[5], tgt[6])

    target = {
        "id":         str(int(num(tgt[0]))),
        "date":       str(t_day),
        "root_code":  t_rc,
        "root_label": scoring.ROOT_LABEL.get(t_rc, t_rc),
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

    # Weight actor overlap by how rare each name is in the corpus, so a match
    # on "SAMYUKTA KISAN MORCHA" counts far more than one on "UNITED".
    tok_idf = scoring.token_idf(con, sorted(t_tokens))
    probe = scoring.pick_probes(tok_idf)
    idf_sum = sum(tok_idf[t]["idf"] for t in probe) or 1.0
    if probe:
        hit_cols = ", ".join(
            f"COUNT(*) FILTER (WHERE Actor1Name ILIKE '%{safe(t)}%'"
            f" OR Actor2Name ILIKE '%{safe(t)}%') AS hit{i}"
            for i, t in enumerate(probe))
    else:
        hit_cols = "0 AS hit0"

    # Candidate groups: one per (day, root code) in the preceding window.
    lo = t_day - scoring.CAUSAL_WINDOW_DAYS
    cands = _rows(con.execute(f"""
        SELECT day,
               COALESCE(NULLIF(EventRootCode, ''), '00') AS rc,
               COUNT(*) AS n,
               COUNT(DISTINCT regexp_extract(SOURCEURL, '://([^/]+)', 1)) AS domains,
               AVG(GoldsteinScale) AS avg_g,
               MIN(GlobalEventID) AS rep_id,
               {hit_cols}
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
    cands = [r for r in cands if int(num(r["n"])) >= scoring.MIN_GROUP_EVENTS]

    midx = scoring.matrix_index(scoring.matrix_rows(con, cc))

    scored = []
    for r in cands:
        ch, feat = scoring.channels.score(
            r, target_rc=t_rc, matrix_index=midx, probe=probe,
            token_idf=tok_idf, idf_sum=idf_sum, documented_groups=documented_groups,
        )
        z, conf = scoring.fuse(ch)
        why = scoring.channels.explain(
            feat, target_rc=t_rc, probe=probe, token_idf=tok_idf,
        )
        c_day, c_rc = feat["c_day"], feat["c_rc"]
        stat, suff, domains, hits = feat["stat"], feat["suff"], feat["domains"], feat["hits"]
        grade, rule = scoring.grade(
            feat["documented"], feat["corroboration"], feat["prior"],
            feat["contrastive"], feat["actors"], suff, conf, domains,
        )
        qmap = {w["key"]: w["question"] for w in why}
        terms = scoring.terms(ch, qmap)

        scored.append({
            "group_id":    f"{c_day}-{c_rc}",
            "_rc":         c_rc,
            "rep_id":      str(int(num(r["rep_id"]))),
            "date":        str(c_day),
            "lag_days":    max(t_day - c_day, 0),
            "root_code":   c_rc,
            "root_label":  scoring.ROOT_LABEL.get(c_rc, c_rc),
            "event_count": int(num(r["n"])),
            "domains":     domains,
            "avg_goldstein": round(num(r["avg_g"]), 2),
            "actor_hits":  {t: hits[t] for t in probe},
            "channels":    ch,
            "confidence":  round(conf, 4),
            "grade":       grade,
            "sufficiency": round(num(stat.get("sufficiency")), 3),
            "necessity":   round(num(stat.get("necessity")), 3),
            "lift":        round(num(stat.get("lift")), 3),
            "trace": {
                "why":        why,
                "terms":      terms,
                "intercept":  scoring.CAUSAL_INTERCEPT,
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
            "min_group":   scoring.MIN_GROUP_EVENTS,
            "actor_probe": probe,
            "actor_tokens": [
                {"token": t,
                 "df": tok_idf[t]["df"],
                 "share": round(tok_idf[t]["share"], 5),
                 "idf": round(tok_idf[t]["idf"], 2),
                 "used": t in probe,
                 "reason": ("selected" if t in probe else
                            "never appears in the corpus" if tok_idf[t]["df"] == 0 else
                            f"too common — in {tok_idf[t]['share']*100:.1f}% of events"
                            if tok_idf[t]["share"] > scoring.ACTOR_MAX_SHARE else
                            "usable but not among the rarest")}
                for t in sorted(tok_idf, key=lambda x: (-tok_idf[x]["idf"], x))
            ],
        },
        "channels":   scoring.CHANNEL_META,
        "weights":    scoring.CAUSAL_W,
        "intercept":  scoring.CAUSAL_INTERCEPT,
        "window_days": scoring.CAUSAL_WINDOW_DAYS,
        "candidates": scored[:14],
        "grade_counts": counts,
        "coverage":   round(coverage, 3),
        "calibrated": False,
    }

# ── Serve frontend static assets if any ──────────────────────────────────────
if (ROOT / "frontend").exists():
    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
