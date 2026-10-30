import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import asyncpg
from focal_event_evaluation import (
    SNAPSHOT_KEYS,
    annotation_template,
    assign_splits,
    blank_labels,
    blind_annotation,
    evaluate,
    read_jsonl,
)
from focal_event_screening import (
    DEFAULT_EVENTS_PATH,
    candidate_observations,
    file_hash,
    load_screened_articles,
    screen_article,
    validate_screening,
)
from focal_events import RankingConfig, load_pipeline

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "evidence" / "focal_events"
MODEL_MANIFEST = DEFAULT_DIR / "models.json"
DEFAULT_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5432/gdelt"
)


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        for record in records:
            output.write(
                json.dumps(record, ensure_ascii=False, default=str, allow_nan=False) + "\n"
            )


def prepare_models(args: argparse.Namespace) -> dict:
    from huggingface_hub import snapshot_download

    if args.model_manifest.exists():
        raise FileExistsError(f"Model manifest already exists: {args.model_manifest}")
    manifest = {}
    for name in ("embedding", "ner"):
        model_id = getattr(args, f"{name}_model")
        revision = getattr(args, f"{name}_revision")
        path = Path(
            snapshot_download(
                model_id,
                revision=revision,
                cache_dir=DEFAULT_DIR / "models",
                allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors"],
            )
        ).resolve()
        manifest[name] = {"model_id": model_id, "revision": path.name, "path": str(path)}
    args.model_manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.model_manifest.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write("\n")
    return manifest


async def select_articles(
    database_url: str,
    limit: int,
    seed: str,
    article_ids: list[int],
    candidate_urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            fields = """
                SELECT document_id, url_key, source_url, final_url, status, title,
                       cleaned_text, fetched_at, extractor_version, extraction_reason,
                       content_hash, raw_html_path
                FROM article_documents
            """
            if article_ids:
                rows = await connection.fetch(
                    fields + " WHERE document_id = ANY($1::bigint[]) ORDER BY document_id",
                    article_ids,
                )
                missing = set(article_ids) - {row["document_id"] for row in rows}
                if missing:
                    raise ValueError(f"Article IDs not found: {sorted(missing)}")
            elif candidate_urls is not None:
                rows = await connection.fetch(
                    fields
                    + """
                    WHERE status = 'extracted' AND url_key = ANY($3::text[])
                    ORDER BY md5($1 || url_key), document_id
                    LIMIT $2
                """,
                    seed,
                    limit,
                    candidate_urls,
                )
            else:
                rows = await connection.fetch(
                    fields
                    + """
                    WHERE status = 'extracted'
                    ORDER BY md5($1 || url_key), document_id
                    LIMIT $2
                """,
                    seed,
                    limit,
                )
            return [dict(row) for row in rows]
    finally:
        await connection.close()


def screen(args: argparse.Namespace) -> dict:
    manifest_path = args.output.with_suffix(".manifest.json")
    if args.output.exists() or manifest_path.exists():
        raise FileExistsError("Screening output or manifest already exists")
    observations = candidate_observations(args.events_input, args.root_code)
    articles = asyncio.run(
        select_articles(args.database_url, args.limit, args.seed, [], sorted(observations))
    )
    if not articles:
        raise ValueError("No extracted articles match the candidate GDELT URLs")
    records = []
    for index, article in enumerate(articles, 1):
        record = screen_article(
            article, observations[article["url_key"]], args.short_word_threshold
        )
        validate_screening(record)
        records.append(record)
        print(f"Screened {index}/{len(articles)} articles", file=sys.stderr)
    write_jsonl(args.output, records)
    manifest = {
        "schema_version": "focal-event-screening-manifest.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
        "sample_seed": args.seed,
        "events_input": str(args.events_input.resolve()),
        "events_sha256": file_hash(args.events_input),
        "screening_code_sha256": file_hash(ROOT / "pipeline" / "focal_event_screening.py"),
        "extractor_code_sha256": file_hash(ROOT / "pipeline" / "article_extractor.py"),
        "root_codes": sorted(set(args.root_code)),
        "action_country": "IN",
        "gdelt_day_range": [20240101, 20241231],
        "candidate_url_count": len(observations),
        "article_ids": [r["article_id"] for r in records],
        "short_word_threshold": args.short_word_threshold,
        "quality_counts": dict(Counter(r["text_quality"]["status"] for r in records)),
        "reprocessing_counts": dict(Counter(r["reprocessing"]["status"] for r in records)),
        "body_cue_articles": sum(bool(r["protest_cues"]["body"]) for r in records),
        "relevance_status": "PENDING_REVIEW",
    }
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, default=str, indent=2, allow_nan=False)
        output.write("\n")
    return manifest


def extract(args: argparse.Namespace) -> dict:
    if args.output.exists():
        raise FileExistsError(f"Output already exists: {args.output}")
    manifest_path = args.output.with_suffix(".manifest.json")
    if manifest_path.exists():
        raise FileExistsError(f"Run manifest already exists: {manifest_path}")
    config = (
        RankingConfig.model_validate_json(args.config.read_text())
        if args.config
        else RankingConfig()
    )
    screened_input = getattr(args, "screened_input", None)
    screening_manifest = None
    if screened_input:
        if args.article_id:
            raise ValueError("Screening input and explicit article IDs cannot be combined")
        articles, screening_manifest = load_screened_articles(screened_input)
    else:
        articles = asyncio.run(
            select_articles(args.database_url, args.limit, args.seed, args.article_id)
        )
    if not articles:
        raise ValueError("No articles selected from the existing store")
    model_manifest = json.loads(args.model_manifest.read_text())
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    with redirect_stdout(sys.stderr):
        pipeline = load_pipeline(model_manifest, config)
    records = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        for offset in range(0, len(articles), config.batch_size):
            with redirect_stdout(sys.stderr):
                batch = pipeline.process(articles[offset : offset + config.batch_size])
            for record in batch:
                output.write(
                    json.dumps(record, ensure_ascii=False, default=str, allow_nan=False) + "\n"
                )
            output.flush()
            records.extend(batch)
            print(f"Stored {len(records)}/{len(articles)} article results", file=sys.stderr)
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "output": str(args.output),
        "sample_seed": (
            screening_manifest.get("selection_manifest", {}).get("sample_seed")
            if screening_manifest
            else args.seed
        ),
        "selection": (
            "screened_snapshot"
            if screened_input
            else "explicit_ids"
            if args.article_id
            else "seeded_url_hash_sample"
        ),
        "screening_input": screening_manifest,
        "article_ids": [record["article_id"] for record in records],
        "article_text_hashes": {
            record["article_id"]: record["article_text_sha256"] for record in records
        },
        "ranking_config": config.model_dump(),
        "models": pipeline.models,
        "counts": dict(Counter(record["processing_status"] for record in records)),
        "embedding_truncated_sentences": sum(
            s["embedding_truncated"]
            for record in records
            for s in record["sentences"]
            if "embedding_truncated" in s
        ),
        "audit": evaluate(records, []),
    }
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, ensure_ascii=False, default=str, indent=2, allow_nan=False)
        output.write("\n")
    return {
        "output": str(args.output),
        "manifest": str(manifest_path),
        "counts": summary["counts"],
        "audit": summary["audit"],
    }


def split(args: argparse.Namespace) -> dict:
    manifest_path = args.output.with_suffix(".manifest.json")
    if args.output.exists() or manifest_path.exists():
        raise FileExistsError("Split output or manifest already exists")
    if args.test_fraction + args.dev_fraction >= 1:
        raise ValueError("Test and dev fractions must leave room for train")
    records = read_jsonl(args.input)
    # Splits are assigned before review. Blinding a test record resets its
    # labels, which on a reviewed export would silently discard human work.
    reviewed = [
        record["article_id"]
        for record in records
        if record.get("review_status", "UNREVIEWED") != "UNREVIEWED"
        or (record.get("eligibility") or {}).get("review_status", "UNREVIEWED") != "UNREVIEWED"
        or (record.get("ner_annotation") or {}).get("review_status", "UNREVIEWED")
        != "UNREVIEWED"
    ]
    if reviewed:
        raise ValueError(f"Split runs before review; already reviewed: {reviewed[:5]}")
    pilot_ids = {str(record["article_id"]) for path in args.pilot for record in read_jsonl(path)}
    assignment, groups = assign_splits(
        records, pilot_ids, args.seed, args.test_fraction, args.dev_fraction
    )
    output = []
    hosts: dict[str, set[str]] = {}
    months: dict[str, Counter] = {}
    for record in records:
        name = assignment[str(record["article_id"])]
        meta = record.get("source_metadata") or {}
        host = urlsplit(meta.get("url_key") or "").hostname
        if host:
            hosts.setdefault(name, set()).add(host)
        observations = meta.get("gdelt_observations") or record.get("gdelt_observations") or []
        days = [str(row["day"]) for row in observations if row.get("day")]
        months.setdefault(name, Counter())[min(days)[:6] if days else "unknown"] += 1
        record = blind_annotation(record) if name == "test" else dict(record)
        record["split"] = name
        output.append(record)
    write_jsonl(args.output, output)
    tuning_hosts = hosts.get("train", set()) | hosts.get("dev", set())
    manifest = {
        "schema_version": "focal-event-splits.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "input": str(args.input.resolve()),
        "input_sha256": file_hash(args.input),
        "pilot_inputs": {str(path.resolve()): file_hash(path) for path in args.pilot},
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
        "seed": args.seed,
        "test_fraction": args.test_fraction,
        "dev_fraction": args.dev_fraction,
        "counts": dict(Counter(assignment.values())),
        "pilot_ids_matched": len(pilot_ids & assignment.keys()),
        "blinded_test_articles": sum(record["split"] == "test" for record in output),
        "duplicate_groups": groups,
        "test_hosts": len(hosts.get("test", set())),
        "test_hosts_shared_with_train_or_dev": len(hosts.get("test", set()) & tuning_hosts),
        "first_gdelt_month_by_split": {name: dict(sorted(c.items())) for name, c in months.items()},
        "assignment": assignment,
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return {
        key: manifest[key]
        for key in ("output", "counts", "pilot_ids_matched", "blinded_test_articles")
    } | {"manifest": str(manifest_path), "duplicate_groups": len(groups)}


# A frozen record is the article snapshot plus its final labels. Drafts and other
# working fields (e.g. `ai_proposal`) stay in the input file, whose hash the
# manifest records.
FROZEN_KEYS = (*SNAPSHOT_KEYS, *blank_labels(), "model_evidence_inspections")
SPLITS = ("pilot", "train", "dev", "test")


def is_ai_label(reviewer: str | None, label_source: str | None = None) -> bool:
    return label_source == "ai_assisted" or (reviewer or "").strip().endswith("(AI)")


def ai_labelled(gold: dict) -> bool:
    ner = gold.get("ner_annotation") or {}
    return (
        is_ai_label(gold.get("reviewer"), gold.get("label_source"))
        or is_ai_label((gold.get("eligibility") or {}).get("reviewer"))
        or (
            gold.get("gold_entities") is not None
            and is_ai_label(ner.get("reviewer"), ner.get("label_source"))
        )
    )


def freeze(args: argparse.Namespace) -> dict:
    manifest_path = args.output.with_suffix(".manifest.json")
    if args.output.exists() or manifest_path.exists():
        raise FileExistsError("Frozen output or manifest already exists")
    annotations = read_jsonl(args.input)
    predictions = read_jsonl(args.predictions)
    assignment = json.loads(args.splits_manifest.read_text())["assignment"]
    problems = []
    if set(assignment) != {str(gold["article_id"]) for gold in annotations}:
        problems.append("annotations and the split assignment cover different articles")
    for gold in annotations:
        article = str(gold["article_id"])
        if assignment.get(article) != gold.get("split"):
            problems.append(f"{article}: split {gold.get('split')} != {assignment.get(article)}")
        if gold.get("review_status") not in {"REVIEWED", "UNSUITABLE"}:
            problems.append(f"{article}: focal event is not reviewed")
        if (gold.get("eligibility") or {}).get("review_status") != "REVIEWED":
            problems.append(f"{article}: screening is not reviewed")
    if problems:
        raise ValueError("Cannot freeze:\n" + "\n".join(problems[:20]))
    ai = [gold for gold in annotations if ai_labelled(gold)]
    if "gold" in args.output.name and ai:
        raise ValueError(
            f"{len(ai)} records carry AI labels; a 'gold' dataset must be human-labelled. "
            "Name it 'weak' or 'ai-assisted' instead."
        )
    metrics = evaluate(predictions, annotations)
    if metrics["evidence_consistency"]["inconsistent_articles"]:
        raise ValueError("Predictions fail the evidence audit; run `audit` first")
    write_jsonl(args.output, [{k: g[k] for k in FROZEN_KEYS if k in g} for g in annotations])
    frozen = read_jsonl(args.output)
    evaluate(predictions, frozen)  # the frozen file must validate on its own

    def by_split(value) -> dict:
        return {
            name: dict(Counter(value(gold) for gold in frozen if gold["split"] == name))
            for name in SPLITS
        }

    entities = [e for gold in frozen if gold.get("gold_entities") for e in gold["gold_entities"]]
    manifest = {
        "schema_version": "focal-event-freeze.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_kind": "ai-assisted" if ai else "gold",
        "records_with_ai_labels": len(ai),
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": file_hash(path)}
            for name, path in (
                ("annotations", args.input),
                ("predictions", args.predictions),
                ("splits_manifest", args.splits_manifest),
            )
        },
        "output": str(args.output),
        "output_sha256": file_hash(args.output),
        "articles": len(frozen),
        "review_status_by_split": by_split(lambda gold: gold["review_status"]),
        "exclusions": dict(
            Counter(
                gold["eligibility"]["exclusion_reason"]
                for gold in frozen
                if gold["review_status"] == "UNSUITABLE"
            )
        ),
        "provenance": {
            "event_label_source_by_split": by_split(lambda gold: gold.get("label_source")),
            "event_reviewers": dict(Counter(gold.get("reviewer") for gold in frozen)),
            "screening_reviewers": dict(
                Counter(gold["eligibility"]["reviewer"] for gold in frozen)
            ),
        },
        "entities": {
            "annotated_articles": sum(gold.get("gold_entities") is not None for gold in frozen),
            "entities": len(entities),
            "by_label": dict(Counter(e["label"] for e in entities)),
        },
        # Validation only. Top-k and NER scores are Phase 6's, and test is scored once.
        "validation": {
            key: metrics[key]
            for key in (
                "reviewed_articles",
                "unsuitable_articles",
                "unreviewed_articles",
                "screening_only_articles",
            )
        }
        | {
            "predictions_consistent": metrics["evidence_consistency"]["consistent_articles"],
            "frozen_file_revalidated": True,
        },
    }
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return {
        key: manifest[key]
        for key in ("output", "output_sha256", "dataset_kind", "articles", "validation")
    } | {"manifest": str(manifest_path)}


def fraction(value: str) -> float:
    number = float(value)
    if not 0 <= number < 1:
        raise argparse.ArgumentTypeError("Fraction must be in [0, 1)")
    return number


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local focal-event evidence retrieval and evaluation"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-models")
    prepare.add_argument("--embedding-model", default="sentence-transformers/all-mpnet-base-v2")
    prepare.add_argument("--embedding-revision", default="main")
    prepare.add_argument("--ner-model", default="fastino/gliner2-base-v1")
    prepare.add_argument("--ner-revision", default="main")
    prepare.add_argument("--model-manifest", type=Path, default=MODEL_MANIFEST)
    screening = commands.add_parser("screen")
    screening.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    screening.add_argument("--events-input", type=Path, default=DEFAULT_EVENTS_PATH)
    screening.add_argument("--root-code", action="append", choices=["14", "18", "19", "20"])
    screening.add_argument("--limit", type=positive_integer, default=50)
    screening.add_argument("--seed", default="protest-screening-v1")
    screening.add_argument("--short-word-threshold", type=positive_integer, default=100)
    screening.add_argument("--output", type=Path, required=True)
    extraction = commands.add_parser("extract")
    extraction.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    extraction.add_argument("--limit", type=positive_integer, default=40)
    extraction.add_argument("--seed", default="focal-pilot-v1")
    extraction.add_argument("--article-id", type=positive_integer, action="append", default=[])
    extraction.add_argument("--screened-input", type=Path)
    extraction.add_argument("--config", type=Path)
    extraction.add_argument("--model-manifest", type=Path, default=MODEL_MANIFEST)
    extraction.add_argument("--output", type=Path, required=True)
    annotation = commands.add_parser("annotate")
    annotation.add_argument("--input", type=Path, required=True)
    annotation.add_argument("--output", type=Path, required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--input", type=Path, required=True)
    evaluation.add_argument("--annotations", type=Path, required=True)
    evaluation.add_argument("--split", choices=["pilot", "train", "dev", "test"])
    evaluation.add_argument("--output", type=Path)
    audit = commands.add_parser("audit")
    audit.add_argument("--input", type=Path, required=True)
    audit.add_argument("--output", type=Path)
    splitting = commands.add_parser("split")
    splitting.add_argument("--input", type=Path, required=True)
    splitting.add_argument("--pilot", type=Path, action="append", required=True)
    splitting.add_argument("--seed", default="focal-splits-v1")
    splitting.add_argument("--test-fraction", type=fraction, default=0.2)
    splitting.add_argument("--dev-fraction", type=fraction, default=0.2)
    splitting.add_argument("--output", type=Path, required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--input", type=Path, required=True)
    freezing.add_argument("--predictions", type=Path, required=True)
    freezing.add_argument("--splits-manifest", type=Path, required=True)
    freezing.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "screen" and not args.root_code:
        args.root_code = ["14"]
    if args.command == "extract" and args.screened_input and args.article_id:
        parser.error("--screened-input and --article-id cannot be combined")
    return args


def main() -> None:
    args = parse_args()
    if args.command == "prepare-models":
        result = prepare_models(args)
    elif args.command == "screen":
        result = screen(args)
    elif args.command == "extract":
        result = extract(args)
    elif args.command == "annotate":
        records = [annotation_template(record) for record in read_jsonl(args.input)]
        write_jsonl(args.output, records)
        result = {"output": str(args.output), "articles": len(records)}
    elif args.command == "split":
        result = split(args)
    elif args.command == "freeze":
        result = freeze(args)
    elif args.command == "evaluate":
        result = evaluate(read_jsonl(args.input), read_jsonl(args.annotations), args.split)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(result, output, indent=2, allow_nan=False)
                output.write("\n")
    else:
        records = read_jsonl(args.input)
        if not records:
            raise ValueError("No stored article results to audit")
        metrics = evaluate(records, [])
        result = {
            "schema_version": "focal-evidence-audit.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "input": str(args.input.resolve()),
            "input_sha256": file_hash(args.input),
            **{
                key: metrics[key]
                for key in (
                    "processing_counts",
                    "evidence_validity",
                    "evidence_valid_spans",
                    "evidence_total_spans",
                    "evidence_consistency",
                )
            },
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(result, output, indent=2, allow_nan=False)
                output.write("\n")
    print(json.dumps(result, indent=2, allow_nan=False))
    if args.command == "extract" and (
        result["counts"].get("ERROR", 0)
        or result["audit"]["evidence_consistency"]["inconsistent_articles"]
    ):
        raise SystemExit(2)
    if (
        args.command in {"audit", "evaluate"}
        and result["evidence_consistency"]["inconsistent_articles"]
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
