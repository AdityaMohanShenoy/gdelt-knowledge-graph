"""P3.5 — negative controls.

Scores pairs that cannot be causal and reports how often the fusion calls them
one. If shuffled data earns the same grades as real data, the scorer is fitting
artifacts of the corpus rather than evidence, and nothing built on top of it
means anything.

GATE 3.5: a high false-positive rate here stops Phase 4.

    python pipeline/31_negative_controls.py --targets 60

Three arms, all scored by the same code path as the live endpoint:

  real      the true 7-day window before the target — the reference, not a control
  shuffled  a 7-day window drawn from elsewhere in the year, so the pairing is
            random while the marginals (event types, volumes, outlets) are real
  future    the 7 days *after* the target, which cannot be a cause of it

`future` is the sharper control. It holds recency, volume and actor overlap
almost fixed and breaks only the arrow of time, so anything it scores highly is
something the fusion is reading that has nothing to do with causation.
"""

import argparse
import collections
import json
import random
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scoring  # noqa: E402
from scoring.sql import num, rows, safe  # noqa: E402

DEFAULT_PARQUET = ROOT / "out" / "step2_causal_filtered.parquet"
REPORT_PATH = ROOT / "docs" / "measurements" / "negative_controls.md"
RESULT_PATH = ROOT / "out" / "negative_controls.json"
KEPT_GRADES = ("confirmed", "reported", "pattern")
GRADE_ORDER = ("confirmed", "reported", "pattern", "weak", "dropped")


def connect(parquet: Path):
    con = duckdb.connect()
    con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{parquet.as_posix()}')")
    return con


def pick_targets(con, cc: str, count: int, seed: int) -> list[dict]:
    got = rows(con.execute(f"""
        SELECT GlobalEventID, day, EventRootCode, Actor1Name, Actor2Name, precursor_ids
        FROM events
        WHERE ActionGeo_CountryCode = '{safe(cc)}'
          AND COALESCE(NULLIF(EventRootCode, ''), '') <> ''
          AND day > 20240115 AND day < 20241215
        ORDER BY GlobalEventID
    """))
    return random.Random(seed).sample(got, min(count, len(got)))


def score_window(con, cc: str, target: dict, lo: int, hi: int, documented_groups: set) -> list[dict]:
    t_rc = str(target["EventRootCode"]).zfill(2)
    tokens = scoring.actor_tokens(target["Actor1Name"], target["Actor2Name"])
    tok_idf = scoring.token_idf(con, sorted(tokens))
    probe = scoring.pick_probes(tok_idf)
    idf_sum = sum(tok_idf[t]["idf"] for t in probe) or 1.0
    midx = scoring.matrix_index(scoring.matrix_rows(con, cc))

    out = []
    for cand in scoring.candidate_groups(con, cc, lo, hi, probe):
        if int(num(cand["n"])) < scoring.MIN_GROUP_EVENTS:
            continue
        ch, feat = scoring.channels.score(
            cand, target_rc=t_rc, matrix_index=midx, probe=probe,
            token_idf=tok_idf, idf_sum=idf_sum, documented_groups=documented_groups)
        _, conf = scoring.fuse(ch)
        grade, _ = scoring.grade(
            feat["documented"], feat["corroboration"], feat["prior"],
            feat["contrastive"], feat["actors"], feat["suff"], conf, feat["domains"])
        out.append({"rc": feat["c_rc"], "grade": grade,
                    "confidence": round(conf, 4), "channels": ch})
    # One candidate per event type, exactly as the endpoint does. Without this
    # a type recurring on five days counts five times and the arms stop being
    # comparable to the live scorer or to each other.
    best: dict[str, dict] = {}
    for c in sorted(out, key=lambda c: (-c["confidence"], c["rc"])):
        best.setdefault(c["rc"], c)
    return list(best.values())


def run(con, cc: str, targets: list[dict], seed: int, window: int) -> dict:
    rng = random.Random(seed + 1)
    arms: dict[str, list[dict]] = collections.defaultdict(list)
    for i, target in enumerate(targets, 1):
        t_day = int(num(target["day"]))
        precursors = str(target["precursor_ids"] or "")
        documented = set()
        ids = [p.strip() for p in precursors.split(",") if p.strip().isdigit()][:20]
        if ids:
            for r in rows(con.execute(f"""
                SELECT day, COALESCE(NULLIF(EventRootCode, ''), '00') AS rc
                FROM events WHERE GlobalEventID IN ({','.join(ids)})
            """)):
                documented.add((int(num(r["day"])), str(r["rc"]).zfill(2)))

        arms["real"] += score_window(con, cc, target, t_day - window, t_day, documented)
        # Shuffled: a window from elsewhere in the year. No precursor link can
        # apply to it, so documented_groups is empty by construction.
        offset = rng.choice([-1, 1]) * rng.randint(60, 250)
        shuffled_day = max(20240110, min(20241220, t_day + offset))
        arms["shuffled"] += score_window(
            con, cc, target, shuffled_day - window, shuffled_day, set())
        # Future: the window after the target. Cannot be its cause.
        arms["future"] += score_window(con, cc, target, t_day + 1, t_day + 1 + window, set())
        if i % 10 == 0:
            print(f"  {i}/{len(targets)} targets")
    return arms


def summarise(arms: dict) -> dict:
    out = {}
    for name, pairs in arms.items():
        counts = collections.Counter(p["grade"] for p in pairs)
        total = len(pairs) or 1
        kept = sum(counts[g] for g in KEPT_GRADES)
        out[name] = {
            "pairs": len(pairs),
            "grades": {g: counts.get(g, 0) for g in GRADE_ORDER},
            "grade_share": {g: round(counts.get(g, 0) / total, 4) for g in GRADE_ORDER},
            "kept_rate": round(kept / total, 4),
            "mean_confidence": round(sum(p["confidence"] for p in pairs) / total, 4),
        }
    for name in ("shuffled", "future"):
        if name in out and "real" in out:
            out[name]["false_positive_rate"] = out[name]["kept_rate"]

    # The headline FPR is not the finding. A grade only means something if it
    # fires more on real pairs than on random ones, so report the ratio per
    # grade: 1.0 is a grade with no discriminative power at all.
    if "real" in out and "shuffled" in out:
        out["discrimination"] = {
            g: (round(out["real"]["grade_share"][g] / out["shuffled"]["grade_share"][g], 2)
                if out["shuffled"]["grade_share"][g] else None)
            for g in GRADE_ORDER
        }
    return out


def write_report(summary: dict, targets: int, window: int) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    real = summary.get("real", {})
    lines = [
        "# P3.5 — Negative controls", "",
        f"{targets} target events, a {window}-day window per arm. "
        "Every arm is scored by the same code path as `/api/causal/score`.", "",
        "| Arm | Pairs | Kept (confirmed+reported+pattern) | Mean confidence |",
        "|---|---|---|---|",
    ]
    for name in ("real", "shuffled", "future"):
        s = summary.get(name)
        if s:
            lines.append(f"| `{name}` | {s['pairs']:,} | {100*s['kept_rate']:.1f}% | {s['mean_confidence']} |")
    lines += ["", "## Grade distribution", "", "| Grade | " +
              " | ".join(f"`{n}`" for n in ("real", "shuffled", "future")) + " |",
              "|---|---|---|---|"]
    for g in GRADE_ORDER:
        cells = " | ".join(
            f"{100*summary[n]['grade_share'].get(g, 0):.1f}%" for n in ("real", "shuffled", "future")
            if n in summary)
        lines.append(f"| {g} | {cells} |")

    fpr = summary.get("future", {}).get("false_positive_rate", 0)
    shuffled_fpr = summary.get("shuffled", {}).get("false_positive_rate", 0)
    disc = summary.get("discrimination", {})

    lines += ["", "## Discrimination per grade", "",
              "How much more often a grade fires on real pairs than on shuffled ones. "
              "**1.0 means the grade cannot tell them apart.**", "",
              "| Grade | real / shuffled |", "|---|---|"]
    for g in GRADE_ORDER:
        v = disc.get(g)
        lines.append(f"| {g} | {'∞ (never fires on shuffled)' if v is None else f'{v}×'} |")

    pattern_ratio = disc.get("pattern")
    lines += ["", "## GATE 3.5", "",
              f"False-positive rate, shuffled: **{100*shuffled_fpr:.1f}%**. "
              f"Future window: **{100*fpr:.1f}%**.", ""]
    if pattern_ratio is not None and pattern_ratio < 1.25:
        lines += [
            f"**The gate fails.** `pattern` fires at {pattern_ratio}× on real pairs "
            "versus shuffled — which is to say, not at all. That grade exists to catch "
            "links Stage 1 never saw, and it is finding them just as readily in "
            "randomness. It is measuring corpus structure: `prior` and `contrastive` "
            "are country-level type-pair statistics that know nothing about the "
            "specific pair being scored.",
            "",
            "The separation visible in `confirmed` and `reported` is not evidence "
            "against this. Those two are carried by the `documented` channel, which is "
            "empty by construction in both control arms, so their gap is guaranteed "
            "rather than measured.",
            "",
            "Per the plan: do not proceed to Phase 4 on a scorer that finds causes in "
            "randomness. The fix belongs in P3.2 and P3.4 — a textual channel that "
            "reads the specific pair, and weights fitted on labelled decisions instead "
            "of the illustrative ones in use now.",
        ]
    else:
        lines.append("Grades separate real pairs from shuffled ones; the gate holds.")
    lines += ["", f"Raw per-pair records: `{RESULT_PATH.relative_to(ROOT)}`.", ""]
    REPORT_PATH.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument("--country", default="IN")
    parser.add_argument("--targets", type=int, default=60)
    parser.add_argument("--window", type=int, default=scoring.CAUSAL_WINDOW_DAYS)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    con = connect(args.parquet)
    targets = pick_targets(con, args.country, args.targets, args.seed)
    print(f"{len(targets)} targets, {args.window}-day windows")
    arms = run(con, args.country, targets, args.seed, args.window)
    summary = summarise(arms)
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps({"summary": summary, "targets": len(targets)}, indent=2))
    write_report(summary, len(targets), args.window)
    print(json.dumps(summary, indent=2))
    print(f"\n-> {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
