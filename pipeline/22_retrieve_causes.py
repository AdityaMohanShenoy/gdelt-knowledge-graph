"""Phase 9: retrieve candidate causes for protest seeds from canonical events.

    .venv/bin/python pipeline/22_retrieve_causes.py \\
      --annotations data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl \\
      --mentions data/evidence/events/protest-review-300.mentions.v2.reviewed.jsonl \\
      --canonical data/evidence/events/protest-review-300.canonical.v2.jsonl \\
      --output data/evidence/events/protest-review-300.claims.v1.jsonl

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

from causal_candidates import claim, in_window, is_seed, proposed, queue, signals
from focal_event_evaluation import read_jsonl
from focal_event_screening import file_hash

ROOT = Path(__file__).resolve().parents[1]
MODEL_MANIFEST = ROOT / "data" / "evidence" / "focal_events" / "models.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Candidate causes for protest seeds")
    for name in ("annotations", "mentions", "canonical", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, default=MODEL_MANIFEST)
    args = parser.parse_args()
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

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(json.loads(args.model_manifest.read_text())["embedding"]["path"])
    flat = [(i, s) for i, e in enumerate(events) for s in e["sentences"]]
    vectors = model.encode([s for _, s in flat], batch_size=32, normalize_embeddings=True)
    by_event: dict[int, list] = {}
    for (i, _), vector in zip(flat, vectors, strict=True):
        by_event.setdefault(i, []).append(vector)

    seeds = [i for i, e in enumerate(events) if is_seed(e, mentions, articles)]
    claims = []
    for s in seeds:
        seed = events[s]
        for c, cause in enumerate(events):
            if c == s or not in_window(seed, cause):
                continue
            similarity = max(float(a @ b) for a in by_event[s] for b in by_event[c])
            found = signals(seed, cause, similarity)
            if proposed(found):
                evidence = {"effect": seed["evidence"], "cause": cause["evidence"]}
                claims.append(claim(seed, cause, found, evidence))
    ordered = queue(claims)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")

    event_type = {e["canonical_event_id"]: e["event_type"] for e in events}
    per_seed = Counter(c["effect_event_id"] for c in ordered)
    counts = [per_seed.get(events[s]["canonical_event_id"], 0) for s in seeds]
    manifest = {
        "schema_version": "causal-candidates.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {
            name: {"path": str(p.resolve()), "sha256": file_hash(p)}
            for name, p in (
                ("annotations", args.annotations),
                ("mentions", args.mentions),
                ("canonical", args.canonical),
            )
        },
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
        "window_days": 7,
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
        "lag_days": dict(sorted(Counter(c["lag_days"] for c in ordered).items())),
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(manifest, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
