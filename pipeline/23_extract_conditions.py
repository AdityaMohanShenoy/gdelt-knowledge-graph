"""Conditions and remarks: apply extraction, pair conditions, build canonical ones.

    .venv/bin/python pipeline/23_extract_conditions.py apply \\
      --annotations data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl \\
      --mentions data/evidence/events/protest-review-300.mentions.v2.reviewed.jsonl \\
      --extraction data/evidence/events/protest-review-300.conditions-remarks.extraction.v1.jsonl \\
      --output data/evidence/events/protest-review-300.conditions.v1.jsonl
    .venv/bin/python pipeline/23_extract_conditions.py pairs \\
      --conditions data/evidence/events/protest-review-300.conditions.v1.jsonl \\
      --output data/evidence/events/protest-review-300.condition-pairs.v1.json
    .venv/bin/python pipeline/23_extract_conditions.py build \\
      --annotations ... --conditions ... --pairs ... --decisions ... \\
      --output data/evidence/events/protest-review-300.canonical-conditions.v1.jsonl

`apply` keeps only verbatim spans and also writes the event mentions with remarks
added (`<output stem>.mentions.jsonl`), for re-running Phase 8. Merges are judged
decisions only, as in Phase 8. Never overwrites.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from canonical_events import clusters, merged_pairs
from conditions import apply_extraction, canonical_condition, condition_pairs
from focal_event_evaluation import read_jsonl
from focal_event_screening import file_hash

ROOT = Path(__file__).resolve().parents[1]
MODEL_MANIFEST = ROOT / "data" / "evidence" / "focal_events" / "models.json"
PAIR_FLOOR = 0.55


def fresh(*paths: Path) -> None:
    for path in paths:
        if path.exists() or path.with_suffix(".manifest.json").exists():
            raise FileExistsError(f"{path} or its manifest already exists")


def write(path: Path, rows: list[dict], manifest: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    manifest = {**manifest, "output": str(path), "output_sha256": file_hash(path)}
    with path.with_suffix(".manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return manifest


def apply(args: argparse.Namespace) -> dict:
    mentions_out = args.output.with_name(args.output.stem + ".mentions.jsonl")
    fresh(args.output, mentions_out)
    articles = {g["article_id"]: g for g in read_jsonl(args.annotations)}
    extraction = [json.loads(line) for line in args.extraction.read_text().splitlines()]
    reviewed = {a for a, g in articles.items() if g["review_status"] == "REVIEWED"}
    if {x["article_id"] for x in extraction} != reviewed:
        raise ValueError("Extraction must cover exactly the reviewed articles")
    conditions, remarks, dropped = [], [], 0
    for entry in sorted(extraction, key=lambda x: int(x["article_id"])):
        found, said, lost = apply_extraction(articles[entry["article_id"]], entry, "Claude (AI)")
        conditions += found
        remarks += said
        dropped += lost
    mentions = [json.loads(line) for line in args.mentions.read_text().splitlines()]
    inputs = {
        name: {"path": str(p.resolve()), "sha256": file_hash(p)}
        for name, p in (
            ("annotations", args.annotations),
            ("mentions", args.mentions),
            ("extraction", args.extraction),
        )
    }
    stamp = {"created_at": datetime.now(UTC).isoformat(), "inputs": inputs}
    added = {"schema_version": "event-mentions-with-remarks.v1", "remarks_added": len(remarks)}
    write(mentions_out, mentions + remarks, {**stamp, **added})
    return write(
        args.output,
        conditions,
        {
            **stamp,
            "schema_version": "condition-mentions.v1",
            "conditions": len(conditions),
            "remarks": len(remarks),
            "values_dropped_not_verbatim": dropped,
            "kinds": dict(Counter(c["kind"] for c in conditions)),
            "roles": dict(Counter(c["role"] for c in conditions)),
            "start_stated": sum(c["validity"]["start_stated"] for c in conditions),
            "end_stated": sum(c["validity"]["end_stated"] for c in conditions),
            "remark_types": dict(Counter(r["event_type"] for r in remarks)),
            "mentions_with_remarks": str(mentions_out),
        },
    )


def pairs(args: argparse.Namespace) -> dict:
    fresh(args.output)
    from sentence_transformers import SentenceTransformer

    records = [json.loads(line) for line in args.conditions.read_text().splitlines()]
    model = SentenceTransformer(json.loads(args.model_manifest.read_text())["embedding"]["path"])
    texts = [
        " ".join([r["condition"]["text"]] + [h["text"] for h in r["holders"] + r["locations"]])
        for r in records
    ]
    vectors = model.encode(texts, batch_size=32, normalize_embeddings=True)
    found = condition_pairs(records, vectors, args.floor)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(found, handle, ensure_ascii=False, indent=1)
    manifest = {
        "schema_version": "condition-pairs.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "conditions_sha256": file_hash(args.conditions),
        "floor": args.floor,
        "candidate_pairs": len(found),
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
    }
    with args.output.with_suffix(".manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    return manifest


def build(args: argparse.Namespace) -> dict:
    fresh(args.output)
    articles = {g["article_id"]: g for g in read_jsonl(args.annotations)}
    records = {
        r["condition_mention_id"]: r
        for r in map(json.loads, args.conditions.read_text().splitlines())
    }
    scored = json.loads(args.pairs.read_text())
    decisions = {
        d["key"]: d["decision"] for d in map(json.loads, args.decisions.read_text().splitlines())
    }
    if set(decisions) - {p["key"] for p in scored}:
        raise ValueError("Decisions for pairs that were never candidates")
    tiers = merged_pairs(scored, decisions, float("inf"), args.review_floor)
    different = {k for k, d in decisions.items() if d == "different"}

    def outlet(record: dict) -> str:
        url = articles[record["source_article_id"]]["source_metadata"].get("url_key") or ""
        return (urlsplit(url).hostname or "").removeprefix("www.")

    rows = []
    for group in clusters(sorted(records), tiers["reviewed"]):
        members = set(group)
        conflicts = sorted(tuple(k.split("|")) for k in different if set(k.split("|")) <= members)
        rows.append(canonical_condition([records[i] for i in group], conflicts, outlet))
    return write(
        args.output,
        rows,
        {
            "schema_version": "canonical-conditions.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "inputs": {
                name: file_hash(p)
                for name, p in (
                    ("conditions", args.conditions),
                    ("pairs", args.pairs),
                    ("decisions", args.decisions),
                )
            },
            "review_floor": args.review_floor,
            "condition_mentions": len(records),
            "canonical_conditions": len(rows),
            "merged": sum(len(r["mentions"]) > 1 for r in rows),
            "multi_outlet": sum(len(r["independent_outlets"]) > 1 for r in rows),
            "conflicts": sum(r["review_status"] == "CONFLICT" for r in rows),
            "pairs": {
                "candidates": len(scored),
                "merged_reviewed": len(tiers["reviewed"]),
                "rejected_reviewed": sum(1 for p in tiers["rejected"] if p["key"] in decisions),
                "in_band_unreviewed": sum(
                    1 for p in tiers["rejected"] if p.get("unreviewed_in_band")
                ),
                "below_review_floor": len(tiers["below_band"]),
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Conditions and remarks")
    commands = parser.add_subparsers(dest="command", required=True)
    a = commands.add_parser("apply")
    for name in ("annotations", "mentions", "extraction", "output"):
        a.add_argument(f"--{name}", type=Path, required=True)
    p = commands.add_parser("pairs")
    p.add_argument("--conditions", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--floor", type=float, default=PAIR_FLOOR)
    p.add_argument("--model-manifest", type=Path, default=MODEL_MANIFEST)
    b = commands.add_parser("build")
    for name in ("annotations", "conditions", "pairs", "decisions", "output"):
        b.add_argument(f"--{name}", type=Path, required=True)
    b.add_argument("--review-floor", type=float, default=PAIR_FLOOR)
    args = parser.parse_args()
    result = {"apply": apply, "pairs": pairs, "build": build}[args.command](args)
    print(json.dumps(result, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
