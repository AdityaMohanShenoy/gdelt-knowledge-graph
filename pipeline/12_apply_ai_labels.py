"""Apply AI screening and focal-event decisions to annotation templates.

    .venv/bin/python pipeline/12_apply_ai_labels.py \\
      --templates <annotate output> --screening <dir>/batch_*.decisions.jsonl \\
      --focal <dir>/batch_*.decisions.jsonl --base-splits <old splits manifest> \\
      --output <labelled annotations>

For an extension batch: articles drawn after the splits were fixed. Every record
gets split `extension`, reviewer `Claude (AI)` and label source `ai_assisted`,
so `freeze` names the result weak, never gold. Screening exclusions and focal
`UNSUITABLE` decisions become `UNSUITABLE` records. Also writes a splits
manifest: the base assignment, unchanged, plus these articles.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

REVIEWER, SOURCE, SPLIT = "Claude (AI)", "ai_assisted", "extension"


def rows(paths: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in paths:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if str(row["article_id"]) in out:
                raise ValueError(f"Article {row['article_id']} decided twice")
            out[str(row["article_id"])] = row
    return out


def label(record: dict, screen: dict, focal: dict | None, now: str) -> dict:
    out = {**record, "reviewer": REVIEWER, "label_source": SOURCE, "split": SPLIT}
    out["eligibility"] = {
        "review_status": "REVIEWED", "reviewer": REVIEWER, "reviewed_at": now,
        **{k: screen[k] for k in ("protest_relevance", "body_quality", "scope",
                                  "exclusion_reason")},
    }
    if screen["exclusion_reason"]:
        return {**out, "review_status": "UNSUITABLE", "notes": screen["reason"]}
    if focal is None:
        raise ValueError(f"{record['article_id']}: kept at screening but has no focal decision")
    if focal["decision"] == "UNSUITABLE":
        out["eligibility"]["exclusion_reason"] = focal["exclusion_reason"] or "NO_FOCAL_EVENT"
        return {**out, "review_status": "UNSUITABLE", "notes": focal["notes"]}
    ids = {s["sentence_id"] for s in record["sentences"]}
    support = sorted(focal["supporting_sentence_ids"])
    if not support or set(support) - ids or focal["core_sentence_id"] not in support:
        raise ValueError(f"{record['article_id']}: support or core sentence not in the article")
    return {**out, "review_status": "REVIEWED", "cohort": focal["cohort"],
            "focal_event_summary": focal["focal_event_summary"],
            "supporting_sentence_ids": support, "core_sentence_id": focal["core_sentence_id"],
            "notes": focal.get("notes")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--screening", type=Path, nargs="+", required=True)
    parser.add_argument("--focal", type=Path, nargs="+", required=True)
    parser.add_argument("--base-splits", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    splits_out = args.output.with_suffix(".splits.manifest.json")
    if args.output.exists() or splits_out.exists():
        raise FileExistsError("Output already exists")
    templates = [json.loads(line) for line in args.templates.read_text().splitlines()]
    screening, focal = rows(args.screening), rows(args.focal)
    now = datetime.now(UTC).isoformat()
    missing = [t["article_id"] for t in templates if str(t["article_id"]) not in screening]
    if missing:
        raise ValueError(f"No screening decision for {missing[:5]}")
    labelled = [label(t, screening[str(t["article_id"])], focal.get(str(t["article_id"])), now)
                for t in templates]
    with args.output.open("x", encoding="utf-8") as handle:
        for r in labelled:
            handle.write(json.dumps(r, ensure_ascii=False) + "\n")
    base = json.loads(args.base_splits.read_text())
    overlap = set(base["assignment"]) & {str(r["article_id"]) for r in labelled}
    if overlap:
        raise ValueError(f"Extension articles already have a split: {sorted(overlap)[:5]}")
    assignment = {**base["assignment"], **{str(r["article_id"]): SPLIT for r in labelled}}
    splits_out.write_text(json.dumps({"base": str(args.base_splits), "assignment": assignment},
                                     indent=1) + "\n")
    kept = sum(r["review_status"] == "REVIEWED" for r in labelled)
    print(json.dumps({"articles": len(labelled), "reviewed": kept,
                      "unsuitable": len(labelled) - kept, "splits": str(splits_out)}))


if __name__ == "__main__":
    main()
