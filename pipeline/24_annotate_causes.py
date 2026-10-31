"""Phase 10: judge candidate causes into edges, with rejections and agreement.

    .venv/bin/python pipeline/24_annotate_causes.py packets \\
      --annotations data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl \\
      --claims data/evidence/events/protest-review-300.claims.v4.jsonl \\
      --canonical data/evidence/events/protest-review-300.canonical.v4.jsonl \\
      --conditions data/evidence/events/protest-review-300.canonical-conditions.v1.jsonl \\
      --tuning-claims data/evidence/events/protest-review-300.claims.v1.jsonl \\
      --tuning-key data/evidence/events/protest-review-300.claims.v1.cause-review-key.json \\
      --out-dir <dir>
    .venv/bin/python pipeline/24_annotate_causes.py apply \\
      --annotations ... --claims ... --key <dir>/key.json \\
      --primary <dir>/batch_*.judgements.jsonl --second <dir>/double_*.judgements.jsonl \\
      --output data/evidence/events/protest-review-300.edges.v1.jsonl

`packets` writes blind batches (no retrieval signals or scores) under
docs/causal-annotation-rubric.md, with whole protests double-annotated for a
quarter of the claims. `apply` turns judgements into edges, refusing any that
break the rubric, and reports agreement and recall. Never overwrites.
"""

import argparse
import json
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from causal_annotation import agreement, double_sample, edge, locate_quote
from focal_event_evaluation import read_jsonl
from focal_event_screening import file_hash

BATCH_CLAIMS = 140  # what one judge reads comfortably in a sitting
DOUBLE_SHARE = 0.25


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")


def balanced(seeds: list[str], size: Counter, n: int) -> list[list[str]]:
    batches: list[list[str]] = [[] for _ in range(n)]
    for seed in sorted(seeds, key=lambda s: (-size[s], s)):
        min(batches, key=lambda b: sum(size[s] for s in b)).append(seed)
    return batches


def packets(args: argparse.Namespace) -> dict:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if any(args.out_dir.iterdir()):
        raise FileExistsError(f"{args.out_dir} is not empty")
    articles = {g["article_id"]: g for g in read_jsonl(args.annotations)}
    claims = rows(args.claims)
    events = {e["canonical_event_id"]: e for e in rows(args.canonical)}
    conditions = {c["canonical_condition_id"]: c for c in rows(args.conditions)}
    mentions = lambda side: {e["mention_id"] for e in side}  # noqa: E731

    tuning_effects: list[set] = []
    if args.tuning_claims:
        old = {c["claim_id"]: c for c in rows(args.tuning_claims)}
        tuning_effects = [
            mentions(old[c]["evidence"]["effect"])
            for c in json.loads(args.tuning_key.read_text()).values()
        ]

    by_seed: dict[str, list[dict]] = {}
    for c in claims:
        by_seed.setdefault(c["effect_event_id"], []).append(c)
    short = {s: s.removeprefix("ce:")[:6] for s in by_seed}
    if len(set(short.values())) != len(short):
        raise ValueError("Seed id prefixes collide")

    key: dict = {"candidates": {}, "seeds": {}}
    double = double_sample(claims, args.double, "phase-10")
    packets_by_seed = {}
    for seed_id, group in by_seed.items():
        seed = events[seed_id]
        effect_mentions = mentions(group[0]["evidence"]["effect"])
        effect_articles = sorted({e["article_id"] for e in group[0]["evidence"]["effect"]})
        candidates = []
        order = sorted(group, key=lambda c: c["claim_id"])
        random.Random(seed_id).shuffle(order)
        for n, c in enumerate(order, 1):
            blind = f"{short[seed_id]}:c{n}"
            key["candidates"][blind] = c["claim_id"]
            sentences = sorted({e["sentence"] for e in c["evidence"]["cause"]})[:4]
            if c["cause_kind"] == "condition":
                node = conditions[c["cause_event_id"]]
                fields = {
                    "condition": node["description"],
                    "holders": node["holders"],
                    "locations": node["locations"],
                    "first_reported": node["observed"][0],
                }
            else:
                node = events[c["cause_event_id"]]
                fields = {
                    "date": node["best_time"],
                    "event_type": node["event_type"],
                    "status": node["status"],
                    "actors": node["actors"],
                    "targets": node["targets"],
                    "locations": node["locations"],
                }
            candidates.append({"candidate_id": blind, "kind": c["cause_kind"], **fields,
                               "sentences": sentences})
        key["seeds"][short[seed_id]] = {
            "effect_event_id": seed_id,
            "tuning": any(effect_mentions & t for t in tuning_effects),
            "double": seed_id in double,
        }
        packets_by_seed[seed_id] = {
            "seed_id": short[seed_id],
            "effect": {
                "date": seed["best_time"],
                "actors": seed["actors"],
                "locations": seed["locations"],
                "sentences": sorted({e["sentence"] for e in group[0]["evidence"]["effect"]}),
            },
            "effect_articles": [
                {"article_id": a, "headline": articles[a]["headline"],
                 "text": articles[a]["article_text"]}
                for a in effect_articles
            ],
            "candidates": candidates,
        }

    size = Counter({s: len(g) for s, g in by_seed.items()})
    primary = balanced(list(by_seed), size, max(1, round(len(claims) / BATCH_CLAIMS)))
    second_claims = sum(size[s] for s in double)
    second = balanced(sorted(double), size, max(1, round(second_claims / BATCH_CLAIMS)))
    for name, batches in (("batch", primary), ("double", second)):
        for i, batch in enumerate(batches, 1):
            write_jsonl(args.out_dir / f"{name}_{i}.jsonl", [packets_by_seed[s] for s in batch])
    with (args.out_dir / "key.json").open("x", encoding="utf-8") as handle:
        json.dump(key, handle, indent=1)
    return {
        "claims": len(claims),
        "seeds": len(by_seed),
        "tuning_seeds": sum(v["tuning"] for v in key["seeds"].values()),
        "primary_batches": [sum(size[s] for s in b) for b in primary],
        "double_batches": [sum(size[s] for s in b) for b in second],
        "double_claims": second_claims,
    }


def judged(paths: list[Path], key: dict, claims: dict) -> tuple[dict, dict]:
    """Judgements by claim id, and missed causes by seed, from a set of batch files."""
    found: dict[str, dict] = {}
    missed: dict[str, list] = {}
    for path in paths:
        for line in rows(path):
            missed[line["seed_id"]] = line.get("missed_causes") or []
            for j in line["candidates"]:
                claim_id = key["candidates"][j["candidate_id"]]
                if claim_id in found:
                    raise ValueError(f"{j['candidate_id']} judged twice")
                found[claim_id] = j
    return found, missed


def apply(args: argparse.Namespace) -> dict:
    second_out = args.output.with_name(args.output.stem + ".second.jsonl")
    missed_out = args.output.with_name(args.output.stem + ".missed.jsonl")
    for path in (args.output, second_out, missed_out, args.output.with_suffix(".manifest.json")):
        if path.exists():
            raise FileExistsError(f"{path} already exists")
    articles = {g["article_id"]: g for g in read_jsonl(args.annotations)}
    claims = {c["claim_id"]: c for c in rows(args.claims)}
    key = json.loads(args.key.read_text())
    stamp = datetime.now(UTC).isoformat()

    def outlet(article_id: str) -> str:
        url = articles[article_id]["source_metadata"].get("url_key") or ""
        return (urlsplit(url).hostname or "").removeprefix("www.")

    def texts(claim: dict) -> dict:
        ids = {e["article_id"] for side in claim["evidence"].values() for e in side}
        return {a: articles[a]["article_text"] for a in ids}

    first, missed = judged(args.primary, key, claims)
    if set(first) != set(claims):
        raise ValueError(f"Primary judgements cover {len(first)} of {len(claims)} claims")
    double_seeds = {v["effect_event_id"] for v in key["seeds"].values() if v["double"]}
    second, _ = judged(args.second, key, claims)
    if {claims[c]["effect_event_id"] for c in second} != double_seeds or not set(second) <= set(
        claims
    ):
        raise ValueError("Second judgements must cover exactly the double-annotated seeds")
    edges = [
        edge(claims[c], first[c], texts(claims[c]), outlet, "Claude (AI) A", "primary", stamp)
        for c in sorted(claims)
    ]
    seconds = [
        edge(claims[c], second[c], texts(claims[c]), outlet, "Claude (AI) B", "second", stamp)
        for c in sorted(second)
    ]

    missed_rows = []
    for short, items in sorted(missed.items()):
        seed_id = key["seeds"][short]["effect_event_id"]
        effect_texts = {
            e["article_id"]: articles[e["article_id"]]["article_text"]
            for c in claims.values()
            if c["effect_event_id"] == seed_id
            for e in c["evidence"]["effect"]
        }
        for item in items:
            span = locate_quote(item["quote"], effect_texts)
            if span is None:
                raise ValueError(f"{short}: missed-cause quote is not in the article")
            missed_rows.append({"target_event_id": seed_id, "what": item["what"],
                                "evidence": span, "reviewer_id": "Claude (AI) A",
                                "reviewed_at": stamp, "label_source": "ai_assisted"})

    def recall(tuning: bool) -> dict:
        seeds = {v["effect_event_id"] for v in key["seeds"].values() if v["tuning"] == tuning}
        hit = sum(e["review_status"] == "ACCEPTED" for e in edges if e["target_event_id"] in seeds)
        miss = sum(m["target_event_id"] in seeds for m in missed_rows)
        return {"seeds": len(seeds), "accepted": hit, "missed": miss,
                "recall": round(hit / (hit + miss), 4) if hit + miss else None}

    for path, items in ((args.output, edges), (second_out, seconds), (missed_out, missed_rows)):
        write_jsonl(path, items)
    accepted = [e for e in edges if e["review_status"] == "ACCEPTED"]
    per_seed = Counter(e["target_event_id"] for e in accepted)
    manifest = {
        "schema_version": "causal-edges.v1",
        "created_at": stamp,
        "inputs": {
            name: {"path": str(p.resolve()), "sha256": file_hash(p)}
            for name, p in (("annotations", args.annotations), ("claims", args.claims),
                            ("key", args.key), *((p.name, p) for p in args.primary + args.second))
        },
        "outputs": {p.name: file_hash(p) for p in (args.output, second_out, missed_out)},
        "claims": len(edges),
        "accepted": len(accepted),
        "rejected": len(edges) - len(accepted),
        "accepted_by_kind": dict(Counter(e["source_kind"] for e in accepted)),
        "relations": dict(Counter(e["relation_type"] for e in accepted).most_common()),
        "reject_reasons": dict(
            Counter(e["reject_reason"] for e in edges if e["reject_reason"]).most_common()
        ),
        "strength": dict(sorted(Counter(e["final_strength"] for e in accepted).items())),
        "evidence_quality": dict(Counter(e["evidence_quality"] for e in accepted)),
        "corroboration": dict(sorted(Counter(e["corroboration_count"] for e in accepted).items())),
        "seeds_with_an_edge": len(per_seed),
        "edges_per_seed_max": max(per_seed.values(), default=0),
        "missed_causes": len(missed_rows),
        "recall": {"tuning_seeds": recall(True), "fresh_seeds": recall(False)},
        "agreement": agreement(edges, seconds),
    }
    with args.output.with_suffix(".manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 10 causal annotation")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("packets")
    for name in ("annotations", "claims", "canonical", "conditions", "out_dir"):
        p.add_argument(f"--{name.replace('_', '-')}", dest=name, type=Path, required=True)
    p.add_argument("--tuning-claims", type=Path)
    p.add_argument("--tuning-key", type=Path)
    p.add_argument("--double", type=float, default=DOUBLE_SHARE)
    a = commands.add_parser("apply")
    for name in ("annotations", "claims", "key", "output"):
        a.add_argument(f"--{name}", type=Path, required=True)
    a.add_argument("--primary", type=Path, nargs="+", required=True)
    a.add_argument("--second", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    result = packets(args) if args.command == "packets" else apply(args)
    print(json.dumps(result, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
