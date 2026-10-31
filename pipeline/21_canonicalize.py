"""Phase 8: canonical events from reviewed event mentions.

    .venv/bin/python pipeline/21_canonicalize.py pairs \\
      --annotations data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl \\
      --mentions data/evidence/events/protest-review-300.mentions.v2.reviewed.jsonl \\
      --output data/evidence/events/protest-review-300.pairs.v1.json
    .venv/bin/python pipeline/21_canonicalize.py build \\
      --annotations ... --mentions ... \\
      --pairs data/evidence/events/protest-review-300.pairs.v1.json \\
      --decisions data/evidence/events/protest-review-300.pairs.v1.decisions.jsonl \\
      --output data/evidence/events/protest-review-300.canonical.v1.jsonl

`pairs` scores candidate pairs to order review; it decides nothing. `build` merges
only judged-same pairs, plus pairs at or above `--auto` when one is given. The
auto tier is off by default: no score threshold was merge-safe on the first
review (docs/measurements/canonical_events.md). Nothing below `--review-floor` is
ever merged without a judgement. Every command writes a manifest and never
overwrites.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from canonical_events import (
    anchor_date,
    candidate_pairs,
    canonical_event,
    clusters,
    merged_pairs,
    pair_features,
    resolve_time,
    score,
)
from focal_event_evaluation import read_jsonl
from focal_event_screening import file_hash

ROOT = Path(__file__).resolve().parents[1]
MODEL_MANIFEST = ROOT / "data" / "evidence" / "focal_events" / "models.json"


def load(annotations: Path, mentions_path: Path) -> list[dict]:
    """Reviewed mentions with resolved dates, evidence sentences and outlets."""
    articles = {g["article_id"]: g for g in read_jsonl(annotations)}
    mentions = []
    for line in mentions_path.read_text().splitlines():
        mention = json.loads(line)
        if mention["review_status"] != "REVIEWED":
            continue
        gold = articles[mention["source_article_id"]]
        mention["when"] = resolve_time(
            (mention["event_time"] or {}).get("text"),
            anchor_date(gold),
            mention["status"] == "announced",
        )
        start, end = mention["evidence_start"], mention["evidence_end"]
        mention["sentence"] = gold["article_text"][start:end]
        host = urlsplit(gold["source_metadata"].get("url_key") or "").hostname or ""
        mention["outlet"] = host.removeprefix("www.")
        mentions.append(mention)
    return mentions


def write_manifest(output: Path, manifest: dict) -> Path:
    path = output.with_suffix(".manifest.json")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        handle.write("\n")
    return path


def pairs(args: argparse.Namespace) -> dict:
    if args.output.exists() or args.output.with_suffix(".manifest.json").exists():
        raise FileExistsError("Pairs output or manifest already exists")
    from sentence_transformers import SentenceTransformer

    mentions = load(args.annotations, args.mentions)
    model_path = json.loads(args.model_manifest.read_text())["embedding"]["path"]
    model = SentenceTransformer(model_path, device="cpu")
    vectors = model.encode(
        [m["sentence"] for m in mentions], batch_size=32, normalize_embeddings=True
    )
    scored = []
    for i, j in candidate_pairs(mentions):
        a, b = mentions[i], mentions[j]
        features = pair_features(a, b, float(vectors[i] @ vectors[j]))
        scored.append(
            {
                "key": f"{a['event_mention_id']}|{b['event_mention_id']}",
                "a": a["event_mention_id"],
                "b": b["event_mention_id"],
                "score": score(features),
                "features": features,
            }
        )
    scored.sort(key=lambda p: (-p["score"], p["key"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(scored, handle, ensure_ascii=False, indent=1)
    manifest = {
        "schema_version": "canonical-pairs.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "annotations": file_hash(args.annotations),
            "mentions": file_hash(args.mentions),
        },
        "embedding_model": model_path,
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
        "mentions": len(mentions),
        "candidate_pairs": len(scored),
        "time_rules": dict(Counter(m["when"]["rule"] for m in mentions)),
    }
    write_manifest(args.output, manifest)
    return manifest


def build(args: argparse.Namespace) -> dict:
    if args.output.exists() or args.output.with_suffix(".manifest.json").exists():
        raise FileExistsError("Canonical output or manifest already exists")
    mentions = load(args.annotations, args.mentions)
    by_id = {m["event_mention_id"]: m for m in mentions}
    scored = json.loads(args.pairs.read_text())
    decisions = {}
    for line in args.decisions.read_text().splitlines():
        row = json.loads(line)
        if row["decision"] not in {"same", "different"}:
            raise ValueError(f"Unknown decision for {row['key']}")
        decisions[row["key"]] = row["decision"]
    unknown = set(decisions) - {p["key"] for p in scored}
    if unknown:
        raise ValueError(f"Decisions for pairs that were never candidates: {sorted(unknown)[:3]}")
    auto = args.auto if args.auto is not None else float("inf")
    tiers = merged_pairs(scored, decisions, auto, args.review_floor)
    different = {k for k, d in decisions.items() if d == "different"}
    events = []
    for group in clusters(sorted(by_id), tiers["auto"] + tiers["reviewed"]):
        members = set(group)
        conflicts = [
            tuple(k.split("|")) for k in different if set(k.split("|")) <= members
        ]
        events.append(canonical_event([by_id[i] for i in group], sorted(conflicts)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
    multi = [e for e in events if len(e["supporting_sources"]) > 1]
    manifest = {
        "schema_version": "canonical-events.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": file_hash(path)}
            for name, path in (
                ("annotations", args.annotations),
                ("mentions", args.mentions),
                ("pairs", args.pairs),
                ("decisions", args.decisions),
            )
        },
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
        "auto_threshold": args.auto,
        "review_floor": args.review_floor,
        "mentions": len(mentions),
        "canonical_events": len(events),
        "merged_events": sum(len(e["mentions"]) > 1 for e in events),
        "multi_article_events": len(multi),
        "multi_outlet_events": sum(len(e["independent_outlets"]) > 1 for e in events),
        "conflicted_events": sum(e["review_status"] == "CONFLICT" for e in events),
        "pairs": {
            "candidates": len(scored),
            "merged_auto": len(tiers["auto"]),
            "merged_reviewed": len(tiers["reviewed"]),
            "rejected_reviewed": sum(1 for p in tiers["rejected"] if p["key"] in decisions),
            "in_band_unreviewed": sum(1 for p in tiers["rejected"] if p.get("unreviewed_in_band")),
            "below_review_floor": len(tiers["below_band"]),
        },
        "largest_events": sorted(
            ((len(e["mentions"]), e["canonical_event_id"], e["description"][:80]) for e in events),
            reverse=True,
        )[:5],
    }
    write_manifest(args.output, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonical events from reviewed mentions")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("pairs", "build"):
        sub = commands.add_parser(name)
        sub.add_argument("--annotations", type=Path, required=True)
        sub.add_argument("--mentions", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if name == "pairs":
            sub.add_argument("--model-manifest", type=Path, default=MODEL_MANIFEST)
        else:
            sub.add_argument("--pairs", type=Path, required=True)
            sub.add_argument("--decisions", type=Path, required=True)
            sub.add_argument("--auto", type=float, default=None)
            sub.add_argument("--review-floor", type=float, default=0.25)
    args = parser.parse_args()
    result = pairs(args) if args.command == "pairs" else build(args)
    print(json.dumps(result, indent=2, default=str), file=sys.stdout)


if __name__ == "__main__":
    main()
