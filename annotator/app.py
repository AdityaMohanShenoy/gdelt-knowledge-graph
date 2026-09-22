"""The annotation server. One source of truth for both the local CLI and the
deployed function.

Deliberately free of duckdb and the scoring package: seeding needs those, but
serving reads rows that are already there, and a serverless bundle should not
carry a query engine it never calls.
"""

import json
import os
import secrets

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from pathlib import Path

FRONTEND = Path(__file__).resolve().parent / "annotate.html"

ANNOTATORS = ["pabo", "nambi", "akka", "shenoy"]
DOUBLE_ANNOTATED_EVERY = 4   # P2.4 wants a quarter judged twice, for agreement

# Unset, the tool is open — which is fine on localhost. Set it before putting
# this on a public URL: `annotations` refuses DELETE, so anything a stranger
# writes is permanent in the set P3.4's calibration rests on.
ANNOTATOR_TOKEN = os.environ.get("ANNOTATOR_TOKEN", "")
DEFAULT_SCHEMA = os.environ.get("EVIDENCE_SCHEMA", "public")

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




def suggest_relation(cause_type: str, effect_type: str, lag_days: int) -> str:
    """A rule of thumb from lag and event type — not a model output.

    P2.3 asks the screen to suggest a relation, and accepting should mean
    agreeing with something specific rather than with an unstated proposition.
    P0.3 will decide whether these seven types survive annotator agreement at
    all, so this is a starting point to disagree with, not an answer.
    """
    if cause_type and cause_type == effect_type:
        # Same type both sides: the effect already existed in some form, which
        # is the only thing separating ESCALATES from TRIGGERS.
        return "ESCALATES"
    if lag_days <= 3:
        return "TRIGGERS"
    if lag_days <= 21:
        return "MOBILIZES"
    return "CONTRIBUTES_TO"


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
        claim["suggested_relation"] = suggest_relation(
            row["cause_type"], row["effect_type"], claim["lag_days"])
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


def search_path_setup(schema: str):
    import re
    if not re.match(r"^[a-z_][a-z0-9_]*$", schema or ""):
        raise ValueError(f"not a usable schema name: {schema!r}")

    async def setup(connection):
        await connection.execute(f'SET search_path TO "{schema}", public')

    return setup
