"""Candidate retrieval and the features the channels score over."""

import math

from .config import ACTOR_MAX_SHARE, ACTOR_PROBES, CAUSAL_WINDOW_DAYS, STOP_ACTORS
from .sql import num, rows, safe


def matrix_rows(con, cc: str) -> list[dict]:
    """Type-pair statistics for one country, computed on spike days."""
    return rows(con.execute(f"""
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


def matrix_index(matrix: list[dict]) -> dict:
    """(cause_rc, effect_rc) -> {sufficiency, necessity, lift}"""
    idx = {}
    for r in matrix:
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


def actor_tokens(*names) -> set:
    out = set()
    for n in names:
        if not n:
            continue
        for raw in str(n).replace(",", " ").split():
            tok = "".join(ch for ch in raw.upper() if ch.isalnum())
            if len(tok) > 2 and tok not in STOP_ACTORS:
                out.add(tok)
    return out


def token_idf(con, tokens: list[str]) -> dict:
    """Document frequency and inverse document frequency per token, one scan.

    Token length is a terrible proxy for how much a name narrows things down:
    UNITED appears in 10.9% of events and POLICE in 0.9%, but UNITED is the
    longer string. Counting is cheap, so count.
    """
    if not tokens:
        return {}
    sel = ", ".join(
        f"COUNT(*) FILTER (WHERE Actor1Name ILIKE '%{safe(t)}%'"
        f" OR Actor2Name ILIKE '%{safe(t)}%') AS t{i}"
        for i, t in enumerate(tokens))
    row = con.execute(f"SELECT COUNT(*) AS total, {sel} FROM events").fetchone()
    total = max(int(num(row[0])), 1)
    out = {}
    for i, t in enumerate(tokens):
        df = int(num(row[i + 1]))
        out[t] = {"df": df, "share": df / total, "idf": math.log(total / (1 + df))}
    return out


def pick_probes(idf: dict) -> list[str]:
    """Rarest usable tokens. Sorted with a tiebreaker so the pick is stable."""
    usable = [t for t, v in idf.items()
              # df == 0 would score maximum idf while being unable to match
              # anything at all, so it is useless rather than informative.
              if v["df"] > 0 and v["share"] <= ACTOR_MAX_SHARE]
    return sorted(usable, key=lambda t: (-idf[t]["idf"], t))[:ACTOR_PROBES]


def actor_hit_columns(probe: list[str]) -> str:
    """Per-probe hit counts, or a constant when no token is worth matching."""
    if not probe:
        return "0 AS hit0"
    return ", ".join(
        f"COUNT(*) FILTER (WHERE Actor1Name ILIKE '%{safe(t)}%'"
        f" OR Actor2Name ILIKE '%{safe(t)}%') AS hit{i}"
        for i, t in enumerate(probe))


def candidate_groups(con, cc: str, lo: int, hi: int, probe: list[str]) -> list[dict]:
    """One candidate per (day, root code) in a window. Shared with the negative
    controls, which score the same shape of group over a window that cannot be
    a cause."""
    return rows(con.execute(f"""
        SELECT day,
               COALESCE(NULLIF(EventRootCode, ''), '00') AS rc,
               COUNT(*) AS n,
               COUNT(DISTINCT regexp_extract(SOURCEURL, '://([^/]+)', 1)) AS domains,
               AVG(GoldsteinScale) AS avg_g,
               MIN(GlobalEventID) AS rep_id,
               {actor_hit_columns(probe)}
        FROM events
        WHERE ActionGeo_CountryCode = '{safe(cc)}'
          AND day >= {lo} AND day < {hi}
        GROUP BY day, rc
        ORDER BY day DESC, rc
    """))
