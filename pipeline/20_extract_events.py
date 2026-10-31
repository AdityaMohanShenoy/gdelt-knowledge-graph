"""Phase 7: extract atomic event mentions, then apply the review step.

    .venv/bin/python pipeline/20_extract_events.py extract \\
      --input data/evidence/focal_events/protest-review-300.weak.v2.annotations.jsonl \\
      --output data/evidence/events/protest-review-300.mentions.v2.jsonl
    .venv/bin/python pipeline/20_extract_events.py apply-review \\
      --input data/evidence/focal_events/protest-review-300.weak.v2.annotations.jsonl \\
      --mentions data/evidence/events/protest-review-300.mentions.v2.jsonl \\
      --review data/evidence/events/protest-review-300.mentions.v2.review.jsonl \\
      --output data/evidence/events/protest-review-300.mentions.v2.reviewed.jsonl

Offsets index into each record's frozen snapshot text, whose hash every mention
carries. Each command writes its output and a manifest beside it; never overwrites.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import spacy
from event_mentions import EXTRACTOR_VERSION, SCHEMA_VERSION, apply_review, extract_article
from focal_event_evaluation import read_jsonl
from focal_event_screening import file_hash


def extract(input_path: Path, output: Path) -> dict:
    manifest_path = output.with_suffix(".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("Mentions output or manifest already exists")
    articles = [g for g in read_jsonl(input_path) if g["review_status"] == "REVIEWED"]
    if not articles:
        raise ValueError("No reviewed articles to extract from")
    nlp = spacy.load("en_core_web_sm")
    mentions = [m for gold in articles for m in extract_article(nlp, gold)]
    write(output, mentions)
    rules = [m for m in mentions if m["origin"] == "rules"]
    per_article = Counter(m["source_article_id"] for m in rules)
    manifest = {
        "schema_version": "event-mention-manifest.v1",
        "mention_schema_version": SCHEMA_VERSION,
        "extractor": EXTRACTOR_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "spacy": spacy.__version__,
        "spacy_model": nlp.meta["name"] + "-" + nlp.meta["version"],
        "input": str(input_path.resolve()),
        "input_sha256": file_hash(input_path),
        "output": str(output),
        "output_sha256": file_hash(output),
        "articles": len(articles),
        "mentions": len(mentions),
        "rule_mentions": len(rules),
        "focal_seeds_without_rule_mention": len(mentions) - len(rules),
        "articles_with_2_or_more_rule_mentions": sum(n >= 2 for n in per_article.values()),
        "articles_without_rule_mentions": len(articles) - len(per_article),
        "event_types": dict(Counter(m["event_type"] for m in rules)),
        "status": dict(Counter(m["status"] for m in rules)),
        # Share of rule mentions where each field was filled; empty means uncertain.
        "fill_rates": {
            field: round(sum(bool(m[field]) for m in rules) / len(rules), 4) if rules else None
            for field in ("actors", "targets", "locations", "event_time", "event_type")
        },
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return manifest


def write(output: Path, rows: list[dict]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def review(input_path: Path, mentions_path: Path, review_path: Path, output: Path) -> dict:
    manifest_path = output.with_suffix(".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("Reviewed output or manifest already exists")
    articles = {
        g["article_id"]: g for g in read_jsonl(input_path) if g["review_status"] == "REVIEWED"
    }
    proposals: dict[str, list[dict]] = {}
    for line in mentions_path.read_text().splitlines():
        mention = json.loads(line)
        proposals.setdefault(mention["source_article_id"], []).append(mention)
    reviews = {
        r["article_id"]: r for r in map(json.loads, review_path.read_text().splitlines())
    }
    if set(reviews) != set(articles):
        raise ValueError("The review must cover exactly the reviewed articles")
    rows, dropped = [], 0
    for article_id in sorted(articles, key=int):
        found, lost = apply_review(
            articles[article_id], proposals[article_id], reviews[article_id], "Claude (AI)"
        )
        rows += found
        dropped += lost
    write(output, rows)
    kept = [r for r in rows if r["review_status"] == "REVIEWED"]
    rejected = [r for r in rows if r["review_status"] == "REJECTED"]
    manifest = {
        "schema_version": "event-mention-review-manifest.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "reviewer": "Claude (AI)",
        "label_source": "ai_assisted",
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": file_hash(path)}
            for name, path in (
                ("annotations", input_path),
                ("mentions", mentions_path),
                ("review", review_path),
            )
        },
        "output": str(output),
        "output_sha256": file_hash(output),
        "articles": len(articles),
        "reviewed_mentions": len(kept),
        "from_rules_accepted": sum(r["origin"] == "rules" for r in kept),
        "from_rules_corrected": sum(r["origin"] == "rules" and r["corrected"] for r in kept),
        "added_by_review": sum(r["origin"] == "review_added" for r in kept),
        "rejected": len(rejected),
        "reviewer_values_dropped_not_verbatim": dropped,
        "articles_with_confirmed_focal_event": sum(
            r["focal"] and r["review_status"] == "REVIEWED" for r in rows
        ),
        "focal_seeds_left": sum(r["origin"] == "focal_seed" for r in rows),
        "event_types": dict(Counter(r["event_type"] for r in kept)),
        "status": dict(Counter(r["status"] for r in kept)),
        "fill_rates": {
            field: round(sum(bool(r[field]) for r in kept) / len(kept), 4) if kept else None
            for field in ("actors", "targets", "locations", "event_time", "event_type")
        },
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and review atomic event mentions")
    commands = parser.add_subparsers(dest="command", required=True)
    extracting = commands.add_parser("extract")
    extracting.add_argument("--input", type=Path, required=True)
    extracting.add_argument("--output", type=Path, required=True)
    reviewing = commands.add_parser("apply-review")
    reviewing.add_argument("--input", type=Path, required=True)
    reviewing.add_argument("--mentions", type=Path, required=True)
    reviewing.add_argument("--review", type=Path, required=True)
    reviewing.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "extract":
        result = extract(args.input, args.output)
    else:
        result = review(args.input, args.mentions, args.review, args.output)
    print(json.dumps(result, indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
