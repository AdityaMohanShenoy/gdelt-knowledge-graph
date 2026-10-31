"""Phase 9: retrieve candidate causes for protest seeds from canonical events.

    .venv/bin/python pipeline/22_retrieve_causes.py \\
      --annotations data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl \\
      --mentions data/evidence/events/protest-review-300.mentions.v2.reviewed.jsonl \\
      --canonical data/evidence/events/protest-review-300.canonical.v2.jsonl \\
      --output data/evidence/events/protest-review-300.claims.v1.jsonl

v2 adds conditions in effect on the seed's day and a 180-day grievance stratum:

    .venv/bin/python pipeline/22_retrieve_causes.py --annotations ... \\
      --mentions data/evidence/events/protest-review-300.conditions.v1.mentions.jsonl \\
      --canonical data/evidence/events/protest-review-300.canonical.v3.jsonl \\
      --conditions data/evidence/events/protest-review-300.canonical-conditions.v1.jsonl \\
      --condition-mentions data/evidence/events/protest-review-300.conditions.v1.jsonl \\
      --grievance-days 180 --output data/evidence/events/protest-review-300.claims.v2.jsonl

Writes every candidate as an unreviewed claim, in round-robin queue order, with
the evidence sentences of both events, and a manifest. Never overwrites.
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from causal_candidates import (
    WINDOW_DAYS,
    claim,
    condition_node,
    in_window,
    is_seed,
    proposed,
    queue,
    signals,
)
from focal_event_evaluation import read_jsonl
from focal_event_screening import file_hash

ROOT = Path(__file__).resolve().parents[1]
MODEL_MANIFEST = ROOT / "data" / "evidence" / "focal_events" / "models.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Candidate causes for protest seeds")
    for name in ("annotations", "mentions", "canonical", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--conditions", type=Path, help="canonical conditions (v2)")
    parser.add_argument("--condition-mentions", type=Path)
    parser.add_argument("--grievance-days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--model-manifest", type=Path, default=MODEL_MANIFEST)
    args = parser.parse_args()
    if bool(args.conditions) != bool(args.condition_mentions):
        parser.error("--conditions and --condition-mentions go together")
    v2 = bool(args.conditions) or args.grievance_days > WINDOW_DAYS
    retriever = "text-retrieval.v3" if v2 else "text-retrieval.v1"
    manifest_path = args.output.with_suffix(".manifest.json")
    if args.output.exists() or manifest_path.exists():
        raise FileExistsError("Claims output or manifest already exists")

    articles = {g["article_id"]: g for g in read_jsonl(args.annotations)}
    mentions = {
        m["event_mention_id"]: m
        for m in map(json.loads, args.mentions.read_text().splitlines())
        if m["review_status"] == "REVIEWED"
    }
    events = [json.loads(line) for line in args.canonical.read_text().splitlines()]
    for event in events:
        rows = []
        for mention_id in event["mentions"]:
            m = mentions[mention_id]
            text = articles[m["source_article_id"]]["article_text"]
            rows.append(
                {
                    "article_id": m["source_article_id"],
                    "mention_id": mention_id,
                    "sentence": text[m["evidence_start"] : m["evidence_end"]],
                }
            )
        event["evidence"] = rows
        event["sentences"] = [r["sentence"] for r in rows]
    seeds_only = len(events)
    if args.conditions:
        found = {
            r["condition_mention_id"]: r
            for r in map(json.loads, args.condition_mentions.read_text().splitlines())
        }
        for condition in map(json.loads, args.conditions.read_text().splitlines()):
            rows = []
            for mention_id in condition["mentions"]:
                m = found[mention_id]
                text = articles[m["source_article_id"]]["article_text"]
                rows.append(
                    {
                        "article_id": m["source_article_id"],
                        "mention_id": mention_id,
                        "sentence": text[m["evidence_start"] : m["evidence_end"]],
                    }
                )
            node = condition_node(condition, [r["sentence"] for r in rows])
            events.append({**node, "evidence": rows})

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(json.loads(args.model_manifest.read_text())["embedding"]["path"])
    flat = [(i, s) for i, e in enumerate(events) for s in e["sentences"]]
    vectors = model.encode([s for _, s in flat], batch_size=32, normalize_embeddings=True)
    by_event: dict[int, list] = {}
    for (i, _), vector in zip(flat, vectors, strict=True):
        by_event.setdefault(i, []).append(vector)

    seeds = [i for i in range(seeds_only) if is_seed(events[i], mentions, articles)]
    claims = []
    for s in seeds:
        seed = events[s]
        for c, cause in enumerate(events):
            condition = cause.get("cause_kind") == "condition"
            # A condition qualifies when its validity window covers the seed's day.
            if c == s or not in_window(seed, cause, 0 if condition else args.grievance_days):
                continue
            reach = "condition" if condition else "near" if in_window(seed, cause) else "far"
            similarity = max(float(a @ b) for a in by_event[s] for b in by_event[c])
            found = signals(seed, cause, similarity)
            if proposed(found, reach):
                evidence = {"effect": seed["evidence"], "cause": cause["evidence"]}
                claims.append(claim(seed, cause, found, evidence, retriever))
    ordered = queue(claims)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")

    event_type = {e["canonical_event_id"]: e["event_type"] for e in events}
    kinds = Counter(c["cause_kind"] for c in ordered)
    per_seed = Counter(c["effect_event_id"] for c in ordered)
    counts = [per_seed.get(events[s]["canonical_event_id"], 0) for s in seeds]
    manifest = {
        "schema_version": "causal-candidates.v2" if v2 else "causal-candidates.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {
            name: {"path": str(p.resolve()), "sha256": file_hash(p)}
            for name, p in (
                ("annotations", args.annotations),
                ("mentions", args.mentions),
                ("canonical", args.canonical),
                *(
                    (
                        ("conditions", args.conditions),
                        ("condition_mentions", args.condition_mentions),
                    )
                    if args.conditions
                    else ()
                ),
            )
        },
        "retriever": retriever,
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
        "window_days": WINDOW_DAYS,
        "grievance_days": args.grievance_days,
        "claims_by_kind": dict(kinds),
        "seeds": len(seeds),
        "seeds_with_candidates": sum(n > 0 for n in counts),
        "claims": len(ordered),
        "candidates_per_seed": {
            "median": statistics.median(counts) if counts else 0,
            "mean": round(statistics.mean(counts), 2) if counts else 0,
            "max": max(counts, default=0),
        },
        "claims_with_signal": {
            name: sum(bool(c["signals"][name]) for c in ordered)
            for name in ("same_article", "actors", "locations", "shared_names")
        }
        | {"similarity_at_floor": sum(c["signals"]["similarity"] >= 0.45 for c in ordered)},
        "cause_event_types": dict(Counter(event_type[c["cause_event_id"]] for c in ordered)),
        "lag_days": dict(
            sorted(Counter(c["lag_days"] for c in ordered if c["lag_days"] is not None).items())
        ),
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(manifest, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
