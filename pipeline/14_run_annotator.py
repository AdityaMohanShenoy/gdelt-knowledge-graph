"""P2.3 — the annotation tool. Humans judge; they do not search.

    python pipeline/14_run_annotator.py seed --targets 40
    python pipeline/14_run_annotator.py serve --annotator ada

A local server rather than routes in app.py, which the plan assumed. app.py is
the Vercel function and CLAUDE.md keeps it to one runtime data source; it also
could not reach this Postgres. Same shape as 08_run_viewer.py.

Seeding turns the scorer's candidates into real evidence-store rows — an
`events` row per event, a `claims` row per pair including the ones the scorer
would drop, and `claim_channels` per channel — so what gets judged is the
record, not a scratch file.
"""

import argparse
import asyncio
import os
import secrets
from contextlib import asynccontextmanager
import datetime
import json
import sys
from pathlib import Path

import asyncpg
import duckdb
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scoring  # noqa: E402
from store.db import search_path_setup  # noqa: E402
from scoring.sql import num, rows, safe  # noqa: E402

FRONTEND = ROOT / "frontend" / "annotate.html"
DEFAULT_PARQUET = ROOT / "out" / "step2_causal_filtered.parquet"
DEFAULT_DATABASE_URL = "postgresql://gdelt:gdelt_local@localhost:5433/gdelt"

REJECT_REASONS = [
    "NO_CAUSAL_EVIDENCE", "TEMPORALLY_INVALID", "WRONG_EVENT_MATCH",
    "DUPLICATE_EVENT", "CORRELATED_ONLY", "INSUFFICIENT_EVIDENCE",
    "WRONG_DIRECTION", "OTHER",
]
ANNOTATORS = ["pabo", "nambi", "akka", "shenoy"]

# Unset, the tool is open — which is fine on localhost. Set it before putting
# this on a public URL: `annotations` refuses DELETE, so anything a stranger
# writes is permanent in the set P3.4's calibration rests on.
ANNOTATOR_TOKEN = os.environ.get("ANNOTATOR_TOKEN", "")
DEFAULT_SCHEMA = os.environ.get("EVIDENCE_SCHEMA", "public")
DOUBLE_ANNOTATED_EVERY = 4   # P2.4 wants a quarter judged twice, for agreement

RELATION_TYPES = [
    "TRIGGERS", "MOTIVATES", "MOBILIZES", "ENABLES",
    "ESCALATES", "PROMPTS_RESPONSE", "CONTRIBUTES_TO",
]


def day_to_utc(day: int) -> datetime.datetime:
    """A GDELT day is a UTC day. best_time is TIMESTAMPTZ, so a bare date would
    be read as local midnight and stored shifted — an IST run put every event on
    the previous UTC day."""
    d = datetime.datetime.strptime(str(int(day)), "%Y%m%d")
    return d.replace(tzinfo=datetime.timezone.utc)


# ── seeding ──────────────────────────────────────────────────────────────────

async def upsert_event(pool, external_id: str, event_type: str, description: str,
                       when: datetime.date) -> int:
    return await pool.fetchval(
        """
        INSERT INTO events (external_id, event_type, description, best_time,
                            time_range_start, time_range_end, time_confidence)
        VALUES ($1, $2, $3, $4, $4, $4, 1.0)
        ON CONFLICT (external_id) DO UPDATE SET external_id = EXCLUDED.external_id
        RETURNING event_id
        """,
        external_id, event_type, description, when)


async def seed(args) -> dict:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{args.parquet.as_posix()}')")
    cc = args.country
    targets = rows(con.execute(f"""
        WITH ranked AS (
            SELECT GlobalEventID, day, EventRootCode, Actor1Name, Actor2Name,
                   precursor_ids, GoldsteinScale,
                   ROW_NUMBER() OVER (PARTITION BY day
                                      ORDER BY ABS(GoldsteinScale) DESC, GlobalEventID) AS rn
            FROM events
            WHERE ActionGeo_CountryCode = '{safe(cc)}'
              AND EventRootCode = '{safe(args.root_code)}'
              AND precursor_ids <> '' AND day > 20240108
        )
        SELECT * FROM ranked WHERE rn = 1
        ORDER BY ABS(GoldsteinScale) DESC, day LIMIT {int(args.targets)}
    """))

    pool = await asyncpg.create_pool(
        args.database_url, min_size=1, max_size=4,
        setup=search_path_setup(args.schema), statement_cache_size=0)
    made = {"targets": 0, "claims": 0, "channels": 0}
    try:
        build_id = await pool.fetchval(
            """
            INSERT INTO build_versions (config_hash, config, graph_version)
            VALUES ($1, $2, 'annotation-seed.v1')
            ON CONFLICT (config_hash) DO UPDATE SET graph_version = EXCLUDED.graph_version
            RETURNING build_id
            """,
            f"seed-{cc}-{args.root_code}-w{scoring.CAUSAL_WINDOW_DAYS}",
            json.dumps({"country": cc, "window_days": scoring.CAUSAL_WINDOW_DAYS,
                        "weights": scoring.CAUSAL_W, "intercept": scoring.CAUSAL_INTERCEPT}))

        midx = scoring.matrix_index(scoring.matrix_rows(con, cc))
        for t in targets:
            t_day = int(num(t["day"]))
            t_rc = str(t["EventRootCode"]).zfill(2)
            t_actors = " / ".join(x for x in (t["Actor1Name"], t["Actor2Name"]) if x)
            effect_id = await upsert_event(
                pool, str(int(num(t["GlobalEventID"]))),
                scoring.ROOT_LABEL.get(t_rc, t_rc), t_actors, day_to_utc(t_day))
            made["targets"] += 1

            documented = set()
            ids = [p.strip() for p in str(t["precursor_ids"] or "").split(",")
                   if p.strip().isdigit()][:20]
            if ids:
                for r in rows(con.execute(
                        f"SELECT day, COALESCE(NULLIF(EventRootCode,''),'00') AS rc"
                        f" FROM events WHERE GlobalEventID IN ({','.join(ids)})")):
                    documented.add((int(num(r["day"])), str(r["rc"]).zfill(2)))

            tokens = scoring.actor_tokens(t["Actor1Name"], t["Actor2Name"])
            tok_idf = scoring.token_idf(con, sorted(tokens))
            probe = scoring.pick_probes(tok_idf)
            idf_sum = sum(tok_idf[x]["idf"] for x in probe) or 1.0

            for cand in scoring.candidate_groups(
                    con, cc, t_day - scoring.CAUSAL_WINDOW_DAYS, t_day, probe):
                if int(num(cand["n"])) < scoring.MIN_GROUP_EVENTS:
                    continue
                ch, feat = scoring.channels.score(
                    cand, target_rc=t_rc, matrix_index=midx, probe=probe,
                    token_idf=tok_idf, idf_sum=idf_sum, documented_groups=documented)
                _, conf = scoring.fuse(ch)
                grade, rule = scoring.grade(
                    feat["documented"], feat["corroboration"], feat["prior"],
                    feat["contrastive"], feat["actors"], feat["suff"], conf, feat["domains"])
                why = scoring.channels.explain(
                    feat, target_rc=t_rc, probe=probe, token_idf=tok_idf)

                cause_id = await upsert_event(
                    pool, str(int(num(cand["rep_id"]))),
                    scoring.ROOT_LABEL.get(feat["c_rc"], feat["c_rc"]),
                    f'{int(num(cand["n"]))} events, {feat["domains"]} outlets',
                    day_to_utc(feat["c_day"]))

                claim_id = await pool.fetchval(
                    """
                    INSERT INTO claims (cause_kind, cause_id, effect_kind, effect_id,
                                        machine_strength, confidence, grade, verdict, build_id)
                    VALUES ('event', $1, 'event', $2, $3, $3, $4, 'unreviewed', $5)
                    ON CONFLICT (cause_kind, cause_id, effect_kind, effect_id, build_id)
                    DO UPDATE SET confidence = EXCLUDED.confidence
                    RETURNING claim_id
                    """,
                    cause_id, effect_id, round(conf, 4), grade, build_id)
                made["claims"] += 1

                for entry in why:
                    await pool.execute(
                        """
                        INSERT INTO claim_channels (claim_id, channel_key, score,
                                                    available, raw_inputs)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (claim_id, channel_key) DO UPDATE
                          SET score = EXCLUDED.score, raw_inputs = EXCLUDED.raw_inputs
                        """,
                        claim_id, entry["key"], entry["score"],
                        entry["strength"] != "unavailable",
                        json.dumps({"plain": entry["plain"], "math": entry["math"],
                                    "question": entry["question"],
                                    "strength": entry["strength"],
                                    "grade_rule": rule, "lag_days": t_day - feat["c_day"]}))
                    made["channels"] += 1
        made["assignment"] = await assign(pool, ANNOTATORS)
    finally:
        await pool.close()
    return made


async def assign(pool, annotators: list[str]) -> dict:
    """Deal unassigned claims round-robin, and give every fourth one a second
    reader so inter-annotator agreement has something to measure.

    Deterministic on claim_id, so re-running deals the same hands rather than
    reshuffling work people have already started.
    """
    await pool.execute(
        """
        WITH ranked AS (
            SELECT claim_id, row_number() OVER (ORDER BY claim_id) - 1 AS n
            FROM claims
            WHERE primary_annotator IS NULL
        )
        UPDATE claims c
        SET primary_annotator = ($1::text[])[(r.n % array_length($1::text[], 1)) + 1],
            -- Selecting on r.n % 4 would be perfectly correlated with the
            -- rotation above and every double-check would land on one person's
            -- pile. Select whole blocks instead: one block in four is 25% of
            -- claims, and each block already contains one claim per annotator.
            review_annotator = CASE
                WHEN (r.n / array_length($1::text[], 1)) % $2 = 0
                THEN ($1::text[])[((r.n + 1) % array_length($1::text[], 1)) + 1]
                ELSE NULL END
        FROM ranked r
        WHERE c.claim_id = r.claim_id
        """,
        annotators, DOUBLE_ANNOTATED_EVERY)
    got = await pool.fetch(
        """
        SELECT who,
               count(*) FILTER (WHERE role = 'primary') AS primary_load,
               count(*) FILTER (WHERE role = 'review')  AS review_load
        FROM (
            SELECT primary_annotator AS who, 'primary' AS role FROM claims
            WHERE primary_annotator IS NOT NULL
            UNION ALL
            SELECT review_annotator, 'review' FROM claims
            WHERE review_annotator IS NOT NULL
        ) t GROUP BY who ORDER BY who
        """)
    return {r["who"]: {"primary": r["primary_load"], "second_reader": r["review_load"]}
            for r in got}


# ── serving ──────────────────────────────────────────────────────────────────

class Judgement(BaseModel):
    action: str
    annotator: str
    relation_type: str | None = None
    human_strength: float | None = None
    reject_reason: str | None = None
    reason_text: str | None = None


def require_token(
    token: str = "",
    x_annotator_token: str | None = Header(default=None),
) -> None:
    """Query param or header, compared in constant time. A no-op when no token
    is configured, so local use is unchanged."""
    if not ANNOTATOR_TOKEN:
        return
    offered = x_annotator_token or token or ""
    if not secrets.compare_digest(offered, ANNOTATOR_TOKEN):
        raise HTTPException(401, "this link needs a valid token")


def build_app(pool_holder: dict, lifespan=None) -> FastAPI:
    api = FastAPI(title="Causal claim annotation", lifespan=lifespan)

    @api.get("/")
    async def index():
        return FileResponse(FRONTEND)

    @api.get("/api/meta", dependencies=[Depends(require_token)])
    async def meta():
        return {"reject_reasons": REJECT_REASONS, "relation_types": RELATION_TYPES,
                "annotators": ANNOTATORS}

    @api.get("/api/progress", dependencies=[Depends(require_token)])
    async def progress(annotator: str = ""):
        pool = pool_holder["pool"]
        mine = await pool.fetchrow("""
            SELECT count(*) AS assigned,
                   count(*) FILTER (WHERE judged) AS judged,
                   count(DISTINCT effect_id) FILTER (WHERE NOT judged) AS targets_left
            FROM (
                SELECT c.claim_id, c.effect_id,
                       EXISTS (SELECT 1 FROM annotations a
                               WHERE a.claim_id = c.claim_id AND a.annotator = $1) AS judged
                FROM claims c
                WHERE $1 = ANY (ARRAY[c.primary_annotator, c.review_annotator])
            ) t
        """, annotator)
        team = await pool.fetch("""
            SELECT annotator, count(*) AS judged FROM annotations GROUP BY 1 ORDER BY 1
        """)
        return {"annotator": annotator, **dict(mine),
                "team": {r["annotator"]: r["judged"] for r in team}}

    @api.get("/api/claims/next", dependencies=[Depends(require_token)])
    async def next_claim(annotator: str = ""):
        if annotator not in ANNOTATORS:
            raise HTTPException(400, f"pick one of {', '.join(ANNOTATORS)}")
        # Every candidate is stored, including the ones the scorer would drop —
        # they are the hard negatives. But judging all 80-odd per target would
        # exhaust one event before touching the next, so serve each target's
        # strongest unjudged candidate and take the best of those. Coverage
        # spreads across targets instead of down one.
        row = await pool_holder["pool"].fetchrow("""
            WITH mine AS (
                SELECT c.*
                FROM claims c
                WHERE ($1 = ANY (ARRAY[c.primary_annotator, c.review_annotator]))
                  AND NOT EXISTS (
                      SELECT 1 FROM annotations a
                      WHERE a.claim_id = c.claim_id AND a.annotator = $1)
            ), best AS (
                SELECT DISTINCT ON (m.effect_id) m.claim_id, m.machine_strength
                FROM mine m
                ORDER BY m.effect_id, m.machine_strength DESC NULLS LAST, m.claim_id
            )
            SELECT c.claim_id, c.machine_strength, c.grade,
                   cause.description AS cause_actors, cause.event_type AS cause_type,
                   cause.best_time AS cause_time, cause.external_id AS cause_ref,
                   eff.description AS effect_actors, eff.event_type AS effect_type,
                   eff.best_time AS effect_time, eff.external_id AS effect_ref
            FROM best b
            JOIN claims c ON c.claim_id = b.claim_id
            JOIN events cause ON cause.event_id = c.cause_id
            JOIN events eff   ON eff.event_id   = c.effect_id
            ORDER BY b.machine_strength DESC NULLS LAST, c.claim_id
            LIMIT 1
        """, annotator)
        if row is None:
            return JSONResponse({"done": True})
        channels = await pool_holder["pool"].fetch(
            "SELECT channel_key, score, available, raw_inputs FROM claim_channels"
            " WHERE claim_id = $1 ORDER BY score DESC", row["claim_id"])
        claim = dict(row)
        claim["cause_time"] = claim["cause_time"].date().isoformat()
        claim["effect_time"] = claim["effect_time"].date().isoformat()
        claim["lag_days"] = (row["effect_time"] - row["cause_time"]).days
        claim["channels"] = [
            {**dict(c), "raw_inputs": json.loads(c["raw_inputs"])} for c in channels
        ]
        claim["done"] = False
        return claim

    @api.post("/api/claims/{claim_id}/judge", dependencies=[Depends(require_token)])
    async def judge(claim_id: int, body: Judgement):
        if body.action not in {"accept", "edit", "reject"}:
            raise HTTPException(400, "action must be accept, edit or reject")
        if body.action == "reject" and body.reject_reason not in REJECT_REASONS:
            raise HTTPException(400, "a rejection needs a reason from the taxonomy")
        pool = pool_holder["pool"]
        machine = await pool.fetchval(
            "SELECT machine_strength FROM claims WHERE claim_id = $1", claim_id)
        if machine is None and not await pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM claims WHERE claim_id = $1)", claim_id):
            raise HTTPException(404, "no such claim")
        async with pool.acquire() as conn, conn.transaction():
            # The machine value is copied in, never overwritten: P3.4 measures
            # calibration by comparing the two.
            await conn.execute(
                """
                INSERT INTO annotations (claim_id, annotator, action, reject_reason,
                                         reason_text, machine_strength, human_strength,
                                         relation_type)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                claim_id, body.annotator, body.action, body.reject_reason,
                body.reason_text, machine, body.human_strength, body.relation_type)
            await conn.execute(
                "UPDATE claims SET verdict = $2, relation_type = COALESCE($3, relation_type)"
                " WHERE claim_id = $1",
                claim_id, "rejected" if body.action == "reject" else "accepted",
                body.relation_type)
        return {"ok": True, "claim_id": claim_id}

    @api.get("/api/claims/rejected", dependencies=[Depends(require_token)])
    async def rejected(limit: int = 200):
        got = await pool_holder["pool"].fetch("""
            SELECT c.claim_id, c.machine_strength, c.grade,
                   a.reject_reason, a.reason_text, a.annotator, a.created_at
            FROM claims c
            JOIN annotations a ON a.claim_id = c.claim_id AND a.action = 'reject'
            WHERE c.verdict = 'rejected'
            ORDER BY c.claim_id
            LIMIT $1
        """, limit)
        return {"count": len(got), "rejected": [dict(r) | {"created_at": str(r["created_at"])}
                                                for r in got]}

    return api


def serve(args) -> None:
    holder: dict = {}

    @asynccontextmanager
    async def lifespan(_app):
        holder["pool"] = await asyncpg.create_pool(
            args.database_url, min_size=1, max_size=4,
            setup=search_path_setup(args.schema),
            # Supabase's transaction pooler cannot carry prepared statements,
            # which asyncpg caches by default.
            statement_cache_size=0)
        try:
            yield
        finally:
            await holder["pool"].close()

    uvicorn.run(build_app(holder, lifespan), host=args.host, port=args.port,
                log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("seed", help="turn scorer candidates into claims to judge")
    s.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    s.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    s.add_argument("--country", default="IN")
    s.add_argument("--root-code", default="14")
    s.add_argument("--targets", type=int, default=40)
    s.add_argument("--schema", default=DEFAULT_SCHEMA)

    a = sub.add_parser("assign", help="deal unassigned claims across the four annotators")
    a.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    a.add_argument("--schema", default=DEFAULT_SCHEMA)

    v = sub.add_parser("serve", help="run the annotation UI")
    v.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8200)
    v.add_argument("--annotator", default="anonymous")
    v.add_argument("--schema", default=DEFAULT_SCHEMA)

    args = parser.parse_args()
    if args.command == "seed":
        print(json.dumps(asyncio.run(seed(args)), indent=2))
    elif args.command == "assign":
        async def go():
            pool = await asyncpg.create_pool(
                args.database_url, min_size=1, max_size=2,
                setup=search_path_setup(args.schema), statement_cache_size=0)
            try:
                return await assign(pool, ANNOTATORS)
            finally:
                await pool.close()
        print(json.dumps(asyncio.run(go()), indent=2))
    else:
        print(f"annotating at http://{args.host}:{args.port}")
        serve(args)


if __name__ == "__main__":
    main()
