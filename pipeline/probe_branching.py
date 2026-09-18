"""P0.2 — real branching factor.

docs/BUILD_PLAN.md says this task needs no new code: use /api/causal/score as a
retrieval aid and record acceptance by hand. This harness does the mechanical
half — seed selection, depth-3 expansion, and the arithmetic — and leaves
exactly one human judgement per row: is this candidate a real cause.

Deliberately unnumbered: the plan reserves pipeline/11 and 12 for Phase 1.

    python pipeline/probe_branching.py expand
    # fill in the `accept` column of out/branching_worksheet.csv with y/n
    python pipeline/probe_branching.py summarize

What the number means. /api/causal/score returns (day, root_code) GROUPS, not
individual events, and caps the list at 14. So the branching factor measured
here is accepted parent groups per event. Instance-level edges are larger by
roughly the mean event_count, which summarize reports alongside it.
"""

import argparse
import asyncio
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPANSION_PATH = ROOT / "out" / "branching_expansion.json"
WORKSHEET_PATH = ROOT / "out" / "branching_worksheet.csv"
REPORT_PATH = ROOT / "docs" / "measurements" / "branching.md"

GATE_THRESHOLD = 4.0
# Marks a target that returned nothing to judge. Distinct from a human "n",
# so an untouched worksheet can never look like a completed one.
NO_CANDIDATES = "-"
PROJECTION_SEEDS = 500
PROJECTION_DEPTH = 3

SEED_SQL = """
WITH ranked AS (
    SELECT GlobalEventID, day, EventRootCode, Actor1Name, Actor2Name,
           GoldsteinScale, SOURCEURL,
           ROW_NUMBER() OVER (
               PARTITION BY day ORDER BY ABS(GoldsteinScale) DESC, GlobalEventID
           ) AS rn
    FROM events
    WHERE ActionGeo_CountryCode = '{country}'
      AND EventRootCode = '{root_code}'
      AND precursor_ids <> ''
      AND day > 20240108
)
SELECT GlobalEventID, day, Actor1Name, Actor2Name, GoldsteinScale, SOURCEURL
FROM ranked
WHERE rn = 1
ORDER BY ABS(GoldsteinScale) DESC, day
LIMIT {limit}
"""


def select_seeds(app, country: str, root_code: str, limit: int) -> list[dict]:
    """One seed per distinct day, so 20 seeds are 20 situations and not 5
    duplicates of the same wire story."""
    sql = SEED_SQL.format(country=country, root_code=root_code, limit=limit)
    rows = app._rows(app.get_con().execute(sql))
    return [
        {
            "id": str(int(app.num(r["GlobalEventID"]))),
            "date": str(int(app.num(r["day"]))),
            "actors": " / ".join(x for x in (r["Actor1Name"], r["Actor2Name"]) if x),
            "goldstein": round(app.num(r["GoldsteinScale"]), 2),
            "url": r["SOURCEURL"] or "",
        }
        for r in rows
    ]


def top_reasons(candidate: dict, keep: int = 3) -> str:
    """The strongest channels in plain words — the basis a human judges on."""
    why = candidate.get("trace", {}).get("why", [])
    scored = [w for w in why if w.get("strength") != "unavailable"]
    scored.sort(key=lambda w: w.get("score", 0), reverse=True)
    return " | ".join(f"{w['key']}={w.get('score', 0):.2f}: {w.get('plain', '')}" for w in scored[:keep])


async def expand(app, seeds: list[dict], country: str, depth: int, follow: int) -> dict:
    cache: dict[str, dict] = {}

    async def score(event_id: str) -> dict:
        if event_id not in cache:
            cache[event_id] = await app.causal_score(event_id=event_id, country=country)
        return cache[event_id]

    rows: list[dict] = []
    # Walk level by level across every seed at once. Depth-first per seed let a
    # later seed be swallowed as an earlier seed's grandchild, which recorded its
    # expansion at the wrong depth.
    emitted: set[str] = set()
    empty_targets: list[str] = []
    frontier = {
        s["id"]: (s["id"], s["date"], "seed", s["actors"], s["id"]) for s in seeds
    }

    for level in range(depth):
        next_frontier: dict[str, tuple] = {}
        for target_id, target_date, target_label, target_actors, via_seed in frontier.values():
            if target_id in emitted:
                continue
            emitted.add(target_id)
            payload = await score(target_id)
            candidates = payload.get("candidates", [])

            if not candidates:
                empty_targets.append(target_id)
                # A target with no retrievable cause is a branching factor of
                # zero, not a missing observation. Dropping it would average
                # only over events that happen to have parents.
                rows.append(
                    {
                        "seed_id": via_seed, "depth": level + 1, "target_id": target_id,
                        "target_date": target_date, "target_label": target_label,
                        "target_actors": target_actors, "cand_group_id": "",
                        "cand_rep_id": "", "cand_date": "", "lag_days": "",
                        "cand_label": "(no candidates returned)", "event_count": 0,
                        "distinct_domains": 0, "confidence": "", "grade": "",
                        "top_reasons": "", "accept": NO_CANDIDATES,
                    }
                )
                continue

            for rank, c in enumerate(candidates):
                rows.append(
                    {
                        "seed_id": via_seed, "depth": level + 1, "target_id": target_id,
                        "target_date": target_date, "target_label": target_label,
                        "target_actors": target_actors, "cand_group_id": c["group_id"],
                        "cand_rep_id": c["rep_id"], "cand_date": c["date"],
                        "lag_days": c["lag_days"], "cand_label": c["root_label"],
                        "event_count": c["event_count"],
                        "distinct_domains": int(c.get("domains") or 0),
                        "confidence": c["confidence"], "grade": c["grade"],
                        "top_reasons": top_reasons(c), "accept": "",
                    }
                )
                # Recurse only into the strongest few: all 14 at every level is
                # 14^3 per seed and buys nothing, since the gate turns on
                # accepted parents rather than retrieved ones.
                if rank < follow and level + 1 < depth:
                    next_frontier.setdefault(
                        c["rep_id"],
                        (c["rep_id"], c["date"], c["root_label"], "", via_seed),
                    )
        print(f"  depth {level + 1}: {len(emitted)} targets scored, {len(rows)} rows")
        frontier = next_frontier
        if not frontier:
            break

    return {
        "country": country, "depth": depth, "follow": follow, "seeds": seeds,
        "targets_scored": len(cache), "targets_recorded": len(emitted),
        "targets_with_no_candidates": empty_targets, "rows": rows,
    }


def sample_for_judging(rows: list[dict], targets_per_depth: int, seed: int = 0) -> list[dict]:
    """Judging must be complete per target — a half-judged target understates its
    accepted count — so sample whole targets, not rows."""
    import random

    by_depth: dict[int, list[str]] = {}
    for r in rows:
        d = int(r["depth"])
        if r["target_id"] not in by_depth.setdefault(d, []):
            by_depth[d].append(r["target_id"])

    rng = random.Random(seed)
    chosen: set[str] = set()
    for d, targets in by_depth.items():
        pick = targets if len(targets) <= targets_per_depth else rng.sample(targets, targets_per_depth)
        chosen.update(pick)
    return [r for r in rows if r["target_id"] in chosen]


def write_worksheet(rows: list[dict]) -> None:
    WORKSHEET_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with WORKSHEET_PATH.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows: list[dict]) -> dict:
    """Branching factor = accepted candidates per scored target, by depth."""
    def verdict(r):
        return str(r.get("accept", "")).strip().lower()

    # A target with only some rows judged would understate its accepted count,
    # so drop it entirely rather than bias the mean downward.
    per_target: dict[str, list[dict]] = {}
    for r in rows:
        per_target.setdefault(r["target_id"], []).append(r)
    done = {"y", "n", NO_CANDIDATES}
    complete = {t for t, rs in per_target.items() if all(verdict(r) in done for r in rs)}
    judged = [r for r in rows if r["target_id"] in complete]
    partial = sum(
        1 for t, rs in per_target.items()
        if t not in complete and any(verdict(r) in {"y", "n"} for r in rs)
    )
    # Targets that actually presented something to judge. The gate must never be
    # computed from sentinels alone, or an untouched worksheet reports a
    # branching factor of zero and "passes".
    with_candidates = {
        t for t in complete
        if any(str(r.get("cand_group_id", "")).strip() for r in per_target[t])
    }

    by_depth: dict[int, dict[str, list]] = {}
    # Per accepted GROUP, not summed per target: instance edges are
    # group_edges x mean group size, so summing here would double count.
    accepted_group_sizes: list[int] = []
    for r in judged:
        d = int(r["depth"])
        slot = by_depth.setdefault(d, {"targets": {}, "counts": []})
        key = r["target_id"]
        slot["targets"].setdefault(key, {"retrieved": 0, "accepted": 0, "events": 0})
        if not str(r.get("cand_group_id", "")).strip():
            continue  # sentinel: target had no candidates at all
        slot["targets"][key]["retrieved"] += 1
        if verdict(r) == "y":
            slot["targets"][key]["accepted"] += 1
            accepted_group_sizes.append(int(r.get("event_count") or 0))

    depth_stats = {}
    all_accepted: list[int] = []
    for d, slot in sorted(by_depth.items()):
        per_target = [t["accepted"] for t in slot["targets"].values()]
        retrieved = [t["retrieved"] for t in slot["targets"].values()]
        all_accepted.extend(per_target)
        depth_stats[d] = {
            "targets": len(per_target),
            "mean_retrieved": round(statistics.mean(retrieved), 2) if retrieved else 0,
            "mean_accepted": round(statistics.mean(per_target), 2) if per_target else 0,
            "median_accepted": statistics.median(per_target) if per_target else 0,
            "min_accepted": min(per_target) if per_target else 0,
            "max_accepted": max(per_target) if per_target else 0,
        }

    b = statistics.mean(all_accepted) if all_accepted else 0.0
    spread = statistics.stdev(all_accepted) if len(all_accepted) > 1 else 0.0
    group_edges = sum(b**k for k in range(1, PROJECTION_DEPTH + 1)) * PROJECTION_SEEDS
    mean_events = statistics.mean(accepted_group_sizes) if accepted_group_sizes else 0.0

    return {
        "judged_rows": len(judged),
        "unjudged_rows": len(rows) - len(judged),
        "targets_judged": len(complete),
        "targets_with_candidates_judged": len(with_candidates),
        "targets_partially_judged": partial,
        "by_depth": depth_stats,
        "branching_factor": round(b, 2),
        "stdev": round(spread, 2),
        "gate_threshold": GATE_THRESHOLD,
        "gate_passed": b <= GATE_THRESHOLD,
        "projected_group_edges": int(group_edges),
        "mean_events_per_accepted_group": round(mean_events, 1),
        "projected_instance_edges": int(group_edges * mean_events) if mean_events else None,
    }


def write_report(s: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    verdict = "PASSED" if s["gate_passed"] else "FAILED"
    lines = [
        "# P0.2 — Real branching factor",
        "",
        f"Judged candidate rows: **{s['judged_rows']}**"
        + (f" ({s['unjudged_rows']} left unjudged)" if s["unjudged_rows"] else ""),
        "",
        f"## GATE 0.2 — {verdict}",
        "",
        f"Mean branching factor: **{s['branching_factor']}** "
        f"(± {s['stdev']}), against a threshold of {s['gate_threshold']}.",
        "",
        f"Projected for a {PROJECTION_SEEDS}-seed run at depth {PROJECTION_DEPTH}: "
        f"**{s['projected_group_edges']:,} parent-group edges**.",
    ]
    if s["projected_instance_edges"]:
        lines += [
            "",
            f"Each accepted candidate is a (day, root code) group averaging "
            f"{s['mean_events_per_accepted_group']} events, so the instance graph is "
            f"nearer **{s['projected_instance_edges']:,} edges**.",
        ]
    lines += ["", "## By depth", "", "| Depth | Targets | Mean retrieved | Mean accepted | Median | Min | Max |", "|---|---|---|---|---|---|---|"]
    for d, v in s["by_depth"].items():
        lines.append(
            f"| {d} | {v['targets']} | {v['mean_retrieved']} | {v['mean_accepted']} "
            f"| {v['median_accepted']} | {v['min_accepted']} | {v['max_accepted']} |"
        )
    lines += ["", "## Decision", ""]
    if s["gate_passed"]:
        lines += [
            "Branching is within budget. Hand annotation at depth 3 is feasible, and "
            "the P3.4 calibration stays optional rather than mandatory.",
        ]
    else:
        lines += [
            f"Branching above {s['gate_threshold']} projects past 100k edges at depth 3. "
            "That is not annotatable by hand at any realistic team size, so the P3.4 "
            "calibration is **mandatory**, and P2.4's seed set must stay bounded.",
        ]
    lines += [
        "",
        "## Caveats",
        "",
        "- `/api/causal/score` caps its candidate list at 14, so *retrieved* is censored "
        "at that value. *Accepted* is what the gate turns on and is unaffected unless a "
        "target genuinely has more than 14 real parents.",
        "- Candidates are (day, root code) groups, not individual events.",
        "- Expansion follows only the strongest few candidates per level; see "
        "`out/branching_expansion.json` for the exact parameters.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("expand", help="select seeds and walk the causal tree")
    exp.add_argument("--country", default="IN")
    exp.add_argument("--root-code", default="14", help="CAMEO root code; 14 is Protest")
    exp.add_argument("--seeds", type=int, default=20)
    exp.add_argument("--depth", type=int, default=3)
    exp.add_argument("--follow", type=int, default=5)
    exp.add_argument("--judge-targets", type=int, default=8,
                     help="targets per depth to put in the worksheet; 0 = all")

    sub.add_parser("summarize", help="read the judged worksheet and write the report")

    args = parser.parse_args()

    if args.command == "expand":
        import app

        seeds = select_seeds(app, args.country, args.root_code, args.seeds)
        if not seeds:
            raise SystemExit(f"no seeds for country={args.country} root={args.root_code}")
        print(f"{len(seeds)} seeds, depth {args.depth}, following top {args.follow}")
        result = asyncio.run(expand(app, seeds, args.country, args.depth, args.follow))
        EXPANSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPANSION_PATH.write_text(json.dumps(result, indent=2))
        sheet = (
            sample_for_judging(result["rows"], args.judge_targets)
            if args.judge_targets
            else result["rows"]
        )
        write_worksheet(sheet)
        sheet_targets = len({r["target_id"] for r in sheet})
        print(
            f"\n{len(result['rows'])} candidate rows from {result['targets_recorded']} targets\n"
            f"  {EXPANSION_PATH.relative_to(ROOT)}   full record\n"
            f"  {WORKSHEET_PATH.relative_to(ROOT)}   {len(sheet)} rows / {sheet_targets} "
            f"targets to judge -> mark `accept` y or n"
        )
        return

    if not WORKSHEET_PATH.exists():
        raise SystemExit(f"{WORKSHEET_PATH} not found — run `expand` first")
    with WORKSHEET_PATH.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    s = summarize(rows)
    if not s["targets_with_candidates_judged"]:
        raise SystemExit(
            "nothing judged yet — fill the `accept` column with y or n.\n"
            f"({s['targets_judged']} targets are complete but returned no candidates; "
            "those alone cannot decide the gate.)"
        )
    write_report(s)
    print(json.dumps(s, indent=2))
    print(f"\nGATE 0.2 {'PASSED' if s['gate_passed'] else 'FAILED'} -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
