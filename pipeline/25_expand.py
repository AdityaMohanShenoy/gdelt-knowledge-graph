"""Phase 11: the state of the recursive expansion after each judged level.

    .venv/bin/python pipeline/25_expand.py \\
      --canonical data/evidence/events/protest-review-300.canonical.v4.jsonl \\
      --conditions data/evidence/events/protest-review-300.canonical-conditions.v1.jsonl \\
      --claims data/evidence/events/protest-review-300.claims.v4.jsonl ... \\
      --edges data/evidence/events/protest-review-300.edges.v1.jsonl ... \\
      [--targets <earlier .targets.json> ...] \\
      --output data/evidence/events/protest-review-300.expansion.l1.json

Reads every level's claims (one file per level, in order) and primary edges, and
writes the next frontier (`<stem>.targets.json`, input to 22_retrieve_causes.py
--targets), each reached node's search status (`<stem>.status.jsonl`), and a
summary with depth, convergence and a cycle check. Never overwrites.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from causal_expansion import convergence, depths, find_cycle, frontier, statuses
from focal_event_screening import file_hash


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 11 expansion state")
    for name in ("canonical", "conditions", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--claims", type=Path, nargs="+", required=True)
    parser.add_argument("--edges", type=Path, nargs="+", required=True)
    parser.add_argument("--targets", type=Path, nargs="*", default=[],
                        help="the targets files retrieval ran on, after level 1")
    args = parser.parse_args()
    targets_out = args.output.with_name(args.output.stem + ".targets.json")
    status_out = args.output.with_name(args.output.stem + ".status.jsonl")
    for path in (args.output, targets_out, status_out):
        if path.exists():
            raise FileExistsError(f"{path} already exists")

    nodes = {e["canonical_event_id"]: e for e in rows(args.canonical)}
    nodes |= {c["canonical_condition_id"]: c for c in rows(args.conditions)}
    levels = [rows(p) for p in args.claims]
    claims = [c for level in levels for c in level]
    edges = [e for p in args.edges for e in rows(p)]
    if len({e["claim_id"] for e in edges}) != len(edges):
        raise ValueError("A claim is judged in more than one edges file")
    seeds = {c["effect_event_id"] for c in levels[0]}
    # A node is expanded once retrieval has run for it, even if it found nothing:
    # targets with no candidate appear in no claims file, only in the targets list.
    targets = {c["effect_event_id"] for c in claims}
    targets |= {t for p in args.targets for t in json.loads(p.read_text())}
    expanded = targets

    accepted = [e for e in edges if e["review_status"] == "ACCEPTED"]
    reached = seeds | {e["source_event_id"] for e in accepted}
    nxt, stopped = frontier(edges, expanded, nodes)
    status = statuses(reached, targets, claims, edges, stopped)
    depth = depths(edges, seeds)
    cycle = find_cycle(edges)
    shared = convergence(edges)

    with targets_out.open("x", encoding="utf-8") as handle:
        json.dump(nxt, handle, indent=1)
    with status_out.open("x", encoding="utf-8") as handle:
        for node in sorted(status):
            kind = "condition" if node.startswith("cc:") else "event"
            handle.write(json.dumps({
                "node_id": node, "kind": kind, "search_status": status[node],
                "depth": depth.get(node), "effects_explained": shared.get(node, 0),
            }) + "\n")
    summary = {
        "schema_version": "causal-expansion.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {p.name: file_hash(p) for p in [args.canonical, args.conditions,
                                                    *args.claims, *args.edges, *args.targets]},
        "levels_judged": len(levels),
        "seeds": len(seeds),
        "nodes_reached": len(reached),
        "accepted_edges": len(accepted),
        "edges_by_level": [
            sum(e["review_status"] == "ACCEPTED" for e in edges
                if e["claim_id"] in {c["claim_id"] for c in level})
            for level in levels
        ],
        "max_depth": max(depth.values(), default=0),
        "nodes_by_depth": dict(sorted(Counter(depth.values()).items())),
        "search_status": dict(Counter(status.values())),
        "shared_causes": sum(n > 1 for n in shared.values()),
        "most_shared": shared.most_common(5),
        "cycle": cycle,
        "next_frontier": len(nxt),
        "outputs": {p.name: file_hash(p) for p in (targets_out, status_out)},
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print(json.dumps(summary, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
