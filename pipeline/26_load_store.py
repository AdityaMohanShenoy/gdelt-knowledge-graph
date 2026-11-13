"""Phase 12: load the text pipeline (Phases 7–11) into the evidence store.

    .venv/bin/python pipeline/26_load_store.py --schema text_graph

Inputs default to the current artifacts in data/evidence/; see `DEFAULTS`. The
target schema is created if absent. Idempotent: a second run inserts nothing.
The store's own `public` rows (GDELT events, scorer claims) are never touched
unless `--schema public` is given.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_store import gather, load  # noqa: E402

from store.db import DEFAULT_DATABASE_URL, describe, init  # noqa: E402

E = ROOT / "data" / "evidence" / "events" / "protest-review-300"
DEFAULTS = {
    "annotations": ROOT / "data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl",
    "mentions": Path(f"{E}.conditions.v1.mentions.jsonl"),
    "canonical": Path(f"{E}.canonical.v4.jsonl"),
    "conditions": Path(f"{E}.canonical-conditions.v1.jsonl"),
    "condition_mentions": Path(f"{E}.conditions.v1.jsonl"),
    "status": Path(f"{E}.expansion.l3.status.jsonl"),
    "spot_check": Path(f"{E}.edges.v1.human-spotcheck.jsonl"),
    "merges": ROOT / "data/evidence/graph/node-merges.v2.jsonl",
    "human_review": ROOT / "data/evidence/graph/human-edge-review.v3.jsonl",
}
LEVELS = [
    (Path(f"{E}.claims.v4.jsonl"), Path(f"{E}.edges.v1.jsonl"), Path(f"{E}.edges.v1.second.jsonl")),
    (Path(f"{E}.claims.l2.jsonl"), Path(f"{E}.edges.l2.jsonl"), Path(f"{E}.edges.l2.second.jsonl")),
    (Path(f"{E}.claims.l3.jsonl"), Path(f"{E}.edges.l3.jsonl"), Path(f"{E}.edges.l3.second.jsonl")),
]


async def main_async(args: argparse.Namespace) -> dict:
    levels = [tuple(level) for level in args.level] if args.level else LEVELS
    data = gather(levels=levels, **{k: getattr(args, k) for k in DEFAULTS})
    # Blind re-check judgements load as annotations with role "blind"; the build
    # drops an AI-accepted claim a blind judge rejected unless a person accepted it.
    data["edges"] += [{**e, "annotation_role": "blind"} for path in args.blind
                      for e in map(json.loads, path.read_text().splitlines())]
    connection = await asyncpg.connect(args.database_url, statement_cache_size=0)
    try:
        await init(connection, args.schema)
        inserted = await load(connection, data)
        return {"schema": args.schema, "inserted": inserted,
                "rows": await describe(connection, args.schema)}
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="text_graph")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    for name, default in DEFAULTS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", dest=name, type=Path, default=default)
    parser.add_argument("--level", nargs=3, type=Path, action="append",
                        metavar=("CLAIMS", "PRIMARY", "SECOND"),
                        help="one per expansion level, in order (default: the 300-article run)")
    parser.add_argument("--blind", type=Path, action="append", default=[],
                        help="edges files from a blind re-check pass")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main_async(args)), indent=2))


if __name__ == "__main__":
    main()
