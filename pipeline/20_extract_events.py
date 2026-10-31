"""Phase 7: extract atomic event mentions from a frozen focal-event dataset.

    .venv/bin/python pipeline/20_extract_events.py \\
      --input data/evidence/focal_events/protest-review-300.weak.v2.annotations.jsonl \\
      --output data/evidence/events/protest-review-300.mentions.v1.jsonl

Offsets index into each record's frozen snapshot text, whose hash every mention
carries. Writes the mentions and a manifest beside them; never overwrites.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import spacy
from event_mentions import EXTRACTOR_VERSION, SCHEMA_VERSION, extract_article
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
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        for mention in mentions:
            handle.write(json.dumps(mention, ensure_ascii=False, allow_nan=False) + "\n")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract atomic event mentions")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.input, args.output), indent=2), file=sys.stdout)


if __name__ == "__main__":
    main()
