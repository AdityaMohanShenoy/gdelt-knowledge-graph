import copy
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from focal_events import text_hash

ELIGIBILITY_LABELS = {
    "protest_relevance": {"PROTEST", "PROTEST_LINKED", "UNRELATED", "UNCERTAIN"},
    "body_quality": {"COMPLETE", "LIMITED", "INSUFFICIENT"},
    "scope": {"INDIA_2024", "OUT_OF_SCOPE", "UNCERTAIN"},
    "exclusion_reason": {
        "UNRELATED",
        "INSUFFICIENT_TEXT",
        "OUT_OF_SCOPE",
        "NO_FOCAL_EVENT",
        "OTHER",
    },
}


def validate_eligibility(eligibility: dict) -> None:
    if not isinstance(eligibility, dict):
        raise ValueError("Article screening must be an object")
    if eligibility.get("review_status") not in {"UNREVIEWED", "REVIEWED"}:
        raise ValueError("Unknown article screening review status")
    for field, choices in ELIGIBILITY_LABELS.items():
        if eligibility.get(field) is not None and eligibility[field] not in choices:
            raise ValueError(f"Invalid article screening label: {field}")
    if eligibility["review_status"] == "REVIEWED" and (
        not isinstance(eligibility.get("reviewer"), str)
        or not eligibility["reviewer"].strip()
        or any(
            eligibility.get(field) is None
            for field in ("protest_relevance", "body_quality", "scope")
        )
    ):
        raise ValueError("Reviewed article screening requires a reviewer and all three labels")


def is_protest_benchmark_article(gold: dict) -> bool:
    eligibility = gold.get("eligibility") or {}
    return (
        eligibility.get("review_status") == "REVIEWED"
        and eligibility.get("protest_relevance") in {"PROTEST", "PROTEST_LINKED"}
        and eligibility.get("body_quality") == "COMPLETE"
        and eligibility.get("scope") == "INDIA_2024"
    )


def parse_jsonl(text: str, source_name: str) -> list[dict[str, Any]]:
    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"Nonfinite JSON number: {value}")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Nonfinite JSON number: {value}")
        return number

    records = []
    for index, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=reject_nonfinite, parse_float=finite_float)
        except ValueError as error:
            raise ValueError(f"Invalid JSONL in {source_name} at line {index}: {error}") from error
        if not isinstance(record, dict) or not isinstance(record.get("article_id"), str):
            raise ValueError(f"JSONL line {index} requires an object with a string article ID")
        if not record["article_id"]:
            raise ValueError(f"JSONL line {index} has an empty article ID")
        records.append(record)
    ids = [record["article_id"] for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate article IDs in JSONL input")
    return records


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return parse_jsonl(path.read_text(encoding="utf-8"), path.name)


def annotation_template(record: dict) -> dict:
    annotation = {
        "schema_version": "focal-event-gold.v1",
        "article_id": record["article_id"],
        "article_text_sha256": record["article_text_sha256"],
        "headline": record["headline"],
        "article_text": record["article_text"],
        "sentences": [
            {
                key: sentence[key]
                for key in (
                    "sentence_id",
                    "paragraph_id",
                    "text",
                    "start_char",
                    "end_char",
                )
            }
            for sentence in record["sentences"]
        ],
        **blank_labels(),
    }
    if "screening" in record:
        annotation["screening"] = record["screening"]
        annotation["source_metadata"] = record["source_metadata"]
    if "entity_schema" in record:
        annotation["entity_schema"] = dict(record["entity_schema"])
    return annotation


def blank_labels() -> dict:
    return {
        "review_status": "UNREVIEWED",
        "reviewer": None,
        "label_source": None,
        "cohort": None,
        "split": "pilot",
        "focal_event_summary": None,
        "supporting_sentence_ids": [],
        "gold_entities": None,
        "ner_annotation": {
            "review_status": "UNREVIEWED",
            "reviewer": None,
            "label_source": None,
            "whole_article_checked": False,
            "reviewed_at": None,
        },
        "notes": None,
        "eligibility": {
            "review_status": "UNREVIEWED",
            "reviewer": None,
            "reviewed_at": None,
            "protest_relevance": None,
            "body_quality": None,
            "scope": None,
            "exclusion_reason": None,
        },
    }


# The frozen article snapshot. Everything else on an annotation record is a
# label or a draft of one.
SNAPSHOT_KEYS = (
    "schema_version",
    "article_id",
    "article_text_sha256",
    "headline",
    "article_text",
    "sentences",
    "screening",
    "source_metadata",
    "entity_schema",
)


def blind_annotation(record: dict) -> dict:
    """Reset a record to its snapshot so a test-split reviewer never starts from
    an AI draft. Whitelisting the snapshot, rather than deleting known draft
    fields, means a draft field this code has never seen cannot leak through."""
    return {
        **{key: copy.deepcopy(record[key]) for key in SNAPSHOT_KEYS if key in record},
        **blank_labels(),
    }


def split_groups(records: list[dict], near_duplicate: float = 0.8) -> list[list[int]]:
    """Indices of records that must share a split: same URL, same content or
    text hash, or word 5-shingle Jaccard at or above `near_duplicate`."""
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    first: dict[tuple[str, Any], int] = {}
    shingles = []
    for index, record in enumerate(records):
        meta = record.get("source_metadata") or {}
        text = record.get("article_text") or ""
        keys = [
            ("url", meta.get("url_key")),
            ("url", meta.get("final_url")),
            ("content", meta.get("content_hash")),
        ]
        # Every empty article has the same text hash; that is not duplication.
        if text.strip():
            keys.append(("text", record.get("article_text_sha256")))
        for key in keys:
            if key[1]:
                parent[find(index)] = find(first.setdefault(key, index))
        words = text.split()
        shingles.append({tuple(words[i : i + 5]) for i in range(len(words) - 4)})
    # ponytail: all-pairs Jaccard is ~45k comparisons at 300 articles; switch to
    # MinHash if a batch reaches thousands.
    for a in range(len(records)):
        for b in range(a + 1, len(records)):
            if (
                shingles[a]
                and shingles[b]
                and len(shingles[a] & shingles[b]) / len(shingles[a] | shingles[b])
                >= near_duplicate
            ):
                parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for index in range(len(records)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def assign_splits(
    records: list[dict],
    pilot_ids: set[str],
    seed: str,
    test_fraction: float,
    dev_fraction: float,
) -> tuple[dict[str, str], list[list[str]]]:
    """Assign whole duplicate groups to pilot, test, dev or train.

    A group containing an inspected pilot article is pilot: a duplicate of an
    inspected article has been inspected too. The rest are ordered by a seeded
    hash and fill test, then dev, then train, so the result is stable."""
    ids = [str(record["article_id"]) for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate article IDs in split input")
    groups = sorted(sorted(ids[i] for i in group) for group in split_groups(records))
    assignment: dict[str, str] = {}
    rest = []
    for group in groups:
        if pilot_ids.intersection(group):
            assignment.update(dict.fromkeys(group, "pilot"))
        else:
            rest.append(group)
    rest.sort(key=lambda group: hashlib.sha256(f"{seed}:{group[0]}".encode()).hexdigest())
    total = sum(map(len, rest))
    targets = [("test", round(total * test_fraction)), ("dev", round(total * dev_fraction))]
    counts: Counter = Counter()
    for group in rest:
        split = next((name for name, target in targets if counts[name] < target), "train")
        counts[split] += len(group)
        assignment.update(dict.fromkeys(group, split))
    return assignment, [group for group in groups if len(group) > 1]


def valid_span(text: str, span: dict) -> bool:
    if not isinstance(span, dict):
        return False
    start, end = span.get("start_char"), span.get("end_char")
    return (
        type(start) is int
        and type(end) is int
        and 0 <= start < end <= len(text)
        and text[start:end] == span.get("text")
    )


def evidence_audit(record: dict) -> dict:
    text = record["article_text"]
    if not isinstance(text, str):
        raise ValueError("Saved article text must be a string")
    for field in ("paragraphs", "sentences", "candidate_sentences"):
        if not isinstance(record.get(field), list) or any(
            not isinstance(span, dict) for span in record[field]
        ):
            raise ValueError(f"Article {record['article_id']}: {field} must contain span objects")
    valid = 0
    total = 0
    invalid = []
    structural_errors = []
    if record.get("article_text_sha256") != text_hash(text):
        structural_errors.append("article-text-hash-mismatch")
    paragraphs = {
        span["paragraph_id"]: span
        for span in record["paragraphs"]
        if type(span.get("paragraph_id")) is int
    }
    sentences = {
        span["sentence_id"]: span
        for span in record["sentences"]
        if type(span.get("sentence_id")) is int
    }
    sentence_counts = Counter(
        span["sentence_id"] for span in record["sentences"] if type(span.get("sentence_id")) is int
    )
    paragraph_counts = Counter(
        span["paragraph_id"]
        for span in record["paragraphs"]
        if type(span.get("paragraph_id")) is int
    )
    candidate_counts = Counter(
        span["sentence_id"]
        for span in record["candidate_sentences"]
        if type(span.get("sentence_id")) is int
    )
    valid_candidates = []
    valid_paragraph_ids = set()
    valid_sentence_ids = set()
    for kind, identity in (("paragraphs", "paragraph_id"), ("sentences", "sentence_id")):
        previous_end = 0
        ids = paragraph_counts if kind == "paragraphs" else sentence_counts
        for span in record[kind]:
            total += 1
            span_id = span.get(identity)
            reference_valid = (
                type(span_id) is int
                and span_id > 0
                and ids[span_id] == 1
                and valid_span(text, span)
                and span["start_char"] >= previous_end
            )
            if kind == "sentences" and reference_valid:
                paragraph_id = span.get("paragraph_id")
                paragraph = paragraphs.get(paragraph_id) if type(paragraph_id) is int else None
                reference_valid = bool(
                    paragraph
                    and paragraph_id in valid_paragraph_ids
                    and valid_span(text, paragraph)
                    and paragraph["start_char"] <= span["start_char"]
                    and span["end_char"] <= paragraph["end_char"]
                )
            if reference_valid:
                valid += 1
                if kind == "paragraphs":
                    valid_paragraph_ids.add(span_id)
                else:
                    valid_sentence_ids.add(span_id)
            else:
                invalid.append({"kind": kind, "span": span})
            if valid_span(text, span):
                if text[previous_end : span["start_char"]].strip():
                    structural_errors.append(f"article-text-not-covered-by-{kind}")
                previous_end = span["end_char"]
        if text[previous_end:].strip():
            structural_errors.append(f"article-text-not-covered-by-{kind}")
    if len(record["candidate_sentences"]) > 3:
        structural_errors.append("more-than-three-candidate-sentences")
    ordered_ids = record.get("candidate_sentence_ids_in_article_order")
    if ordered_ids is not None and (
        not isinstance(ordered_ids, list)
        or any(type(sentence_id) is not int for sentence_id in ordered_ids)
        or ordered_ids != sorted(candidate_counts)
    ):
        structural_errors.append("candidate-source-order-ids-mismatch")
    for index, span in enumerate(record["candidate_sentences"], 1):
        total += 1
        sentence_id = span.get("sentence_id")
        original = sentences.get(sentence_id) if type(sentence_id) is int else None
        reference_valid = (
            type(sentence_id) is int
            and sentence_counts[sentence_id] == 1
            and sentence_id in valid_sentence_ids
            and candidate_counts[sentence_id] == 1
            and index <= 3
            and original == span
            and valid_span(text, span)
            and type(span.get("rank")) is int
            and span["rank"] == index
        )
        if reference_valid:
            valid += 1
            valid_candidates.append(sentence_id)
        else:
            invalid.append({"kind": "candidate_sentences", "span": span})
    for sentence in record["candidate_sentences"]:
        if not isinstance(sentence.get("entities"), list) or any(
            not isinstance(entity, dict) for entity in sentence["entities"]
        ):
            raise ValueError("Candidate entities must contain span objects")
        entity_counts = Counter(
            entity_key(entity)
            for entity in sentence["entities"]
            if valid_span(text, entity) and isinstance(entity.get("label"), str)
        )
        for entity in sentence["entities"]:
            total += 1
            local_start, local_end = (
                entity.get("sentence_start_char"),
                entity.get("sentence_end_char"),
            )
            local_valid = (
                valid_span(text, entity)
                and type(local_start) is int
                and type(local_end) is int
                and 0 <= local_start < local_end <= len(sentence["text"])
                and entity["start_char"] == sentence["start_char"] + local_start
                and entity["end_char"] == sentence["start_char"] + local_end
                and type(entity.get("sentence_id")) is int
                and entity["sentence_id"] == sentence.get("sentence_id")
                and sentence["text"][local_start:local_end] == entity["text"]
            )
            confidence = entity.get("confidence")
            confidence_valid = confidence is None or (
                type(confidence) in {int, float}
                and math.isfinite(confidence)
                and 0 <= confidence <= 1
            )
            if (
                valid_span(text, entity)
                and local_valid
                and confidence_valid
                and isinstance(entity.get("label"), str)
                and entity.get("label") in record["entity_schema"]
                and entity_counts[entity_key(entity)] == 1
                and sentence["sentence_id"] in valid_candidates
            ):
                valid += 1
            else:
                invalid.append({"kind": "entity", "span": entity})
    return {
        "valid_spans": valid,
        "total_spans": total,
        "invalid_spans": invalid,
        "structural_errors": sorted(set(structural_errors)),
        "consistent": not invalid and not structural_errors,
        "valid_candidate_sentence_ids": valid_candidates,
    }


def entity_key(entity: dict) -> tuple:
    return entity["label"], entity["start_char"], entity["end_char"]


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def validate_annotation_snapshot(gold: dict, record: dict) -> None:
    if gold.get("schema_version") != "focal-event-gold.v1":
        raise ValueError("Unsupported annotation schema")
    if (
        gold.get("article_text") != record["article_text"]
        or gold.get("article_text_sha256") != text_hash(record["article_text"])
        or record.get("article_text_sha256") != text_hash(record["article_text"])
        or gold.get("headline") != record.get("headline")
    ):
        raise ValueError("Annotation and prediction article snapshots differ")
    if any(
        gold.get(field) != record.get(field)
        for field in ("screening", "source_metadata")
        if field in gold or "screening" in record
    ):
        raise ValueError("Annotation and prediction source metadata differ")
    fields = ("sentence_id", "paragraph_id", "text", "start_char", "end_char")
    if not isinstance(gold.get("sentences"), list) or any(
        not isinstance(sentence, dict)
        or any(type(sentence.get(key)) is not int for key in ("sentence_id", "paragraph_id"))
        or not valid_span(record["article_text"], sentence)
        for sentence in gold["sentences"]
    ):
        raise ValueError("Annotation sentence spans or IDs are invalid")
    expected = [{key: sentence[key] for key in fields} for sentence in record["sentences"]]
    actual = [{key: sentence.get(key) for key in fields} for sentence in gold["sentences"]]
    if actual != expected:
        raise ValueError("Annotation and prediction sentence segmentation differ")
    support = gold.get("supporting_sentence_ids")
    ids = {sentence["sentence_id"] for sentence in record["sentences"]}
    if (
        not isinstance(support, list)
        or any(type(sentence_id) is not int or sentence_id not in ids for sentence_id in support)
        or len(set(support)) != len(support)
    ):
        raise ValueError("Annotation supporting sentence IDs are invalid or duplicated")
    entities = gold.get("gold_entities")
    if "entity_schema" in gold and gold["entity_schema"] != record["entity_schema"]:
        raise ValueError("Annotation and prediction entity schemas differ")
    if entities is not None:
        if not isinstance(entities, list):
            raise ValueError("Gold entities must be a list or null")
        for entity in entities:
            if (
                not valid_span(record["article_text"], entity)
                or not isinstance(entity.get("label"), str)
                or entity["label"] not in record["entity_schema"]
            ):
                raise ValueError("Gold entity has an invalid span or unsupported label")
        if len({entity_key(entity) for entity in entities}) != len(entities):
            raise ValueError("Duplicate gold entity spans")
    if "ner_annotation" in gold:
        ner = gold["ner_annotation"]
        if (
            not isinstance(ner, dict)
            or not isinstance(ner.get("review_status"), str)
            or ner["review_status"] not in {"UNREVIEWED", "REVIEWED"}
            or type(ner.get("whole_article_checked")) is not bool
            or ner.get("reviewer") is not None
            and not isinstance(ner["reviewer"], str)
            or ner.get("label_source") is not None
            and (
                not isinstance(ner["label_source"], str)
                or ner["label_source"] not in {"human", "ai_assisted"}
            )
        ):
            raise ValueError("Entity annotation review metadata is invalid")
        if ner.get("reviewed_at") is not None:
            if not isinstance(ner["reviewed_at"], str) or not re.match(
                r"\d{4}-\d{2}-\d{2}T", ner["reviewed_at"]
            ):
                raise ValueError("Entity annotation review timestamp is invalid")
            datetime.fromisoformat(ner["reviewed_at"].replace("Z", "+00:00"))
        if ner["review_status"] == "REVIEWED" and (
            not (ner.get("reviewer") or "").strip()
            or ner.get("label_source") not in {"human", "ai_assisted"}
            or not ner["whole_article_checked"]
            or ner.get("reviewed_at") is None
            or not isinstance(entities, list)
        ):
            raise ValueError("Reviewed entities require provenance and a whole-article check")
    if "model_evidence_inspections" in gold:
        inspections = gold["model_evidence_inspections"]
        if not isinstance(inspections, list):
            raise ValueError("Model evidence inspection history must be a list")
        hashes = set()
        for inspection in inspections:
            if (
                not isinstance(inspection, dict)
                or not isinstance(inspection.get("filename"), str)
                or not inspection["filename"].strip()
                or not isinstance(inspection.get("input_sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", inspection["input_sha256"])
                or not isinstance(inspection.get("viewed_at"), str)
                or not re.match(r"\d{4}-\d{2}-\d{2}T", inspection["viewed_at"])
            ):
                raise ValueError("Model evidence inspection history is invalid")
            datetime.fromisoformat(inspection["viewed_at"].replace("Z", "+00:00"))
            if inspection["input_sha256"] in hashes:
                raise ValueError("Duplicate model evidence inspection hashes")
            hashes.add(inspection["input_sha256"])


def evaluate(records: list[dict], annotations: list[dict], split: str | None = None) -> dict:
    predictions = {record["article_id"]: record for record in records}
    if len(predictions) != len(records):
        raise ValueError("Duplicate prediction article IDs")
    if len({gold["article_id"] for gold in annotations}) != len(annotations):
        raise ValueError("Duplicate annotation article IDs")
    counts: Counter[str] = Counter()
    cohorts: dict[str, Counter] = {}
    screening_counts: dict[str, Counter] = {field: Counter() for field in ELIGIBILITY_LABELS}
    misses = []
    audits = {}
    consistency_issues = []
    audit_valid = audit_total = 0
    for record in records:
        audit = evidence_audit(record)
        audits[record["article_id"]] = audit
        if not audit["consistent"]:
            consistency_issues.append(
                {
                    "article_id": record["article_id"],
                    "structural_errors": audit["structural_errors"],
                    "invalid_spans": audit["invalid_spans"],
                }
            )
        audit_valid += audit["valid_spans"]
        audit_total += audit["total_spans"]
        counts[f"processing:{record['processing_status']}"] += 1
    for gold in annotations:
        if gold.get("split") not in {"pilot", "train", "dev", "test"}:
            raise ValueError("Unknown annotation evaluation split")
        if split is not None and gold.get("split") != split:
            continue
        if gold["article_id"] not in predictions:
            raise ValueError(f"Missing prediction for annotated article {gold['article_id']}")
        record = predictions[gold["article_id"]]
        validate_annotation_snapshot(gold, record)
        eligibility = gold.get("eligibility")
        if eligibility is not None:
            validate_eligibility(eligibility)
            counts["screening_reviewed"] += eligibility["review_status"] == "REVIEWED"
            for field in screening_counts:
                confirmed = (
                    gold["review_status"] == "UNSUITABLE"
                    if field == "exclusion_reason"
                    else eligibility["review_status"] == "REVIEWED"
                )
                if confirmed and eligibility.get(field):
                    screening_counts[field][eligibility[field]] += 1
        status = gold["review_status"]
        if status not in {"UNREVIEWED", "REVIEWED", "UNSUITABLE"}:
            raise ValueError("Unknown annotation review status")
        if status == "UNREVIEWED":
            counts["unreviewed"] += 1
            continue
        if (
            not isinstance(gold.get("reviewer"), str)
            or not gold["reviewer"].strip()
            or gold.get("label_source") not in {"human", "ai_assisted"}
        ):
            raise ValueError("Reviewed labels require a reviewer and label provenance")
        if status == "UNSUITABLE":
            if (eligibility or {}).get("exclusion_reason") == "OTHER" and not gold.get("notes"):
                raise ValueError("Other exclusions require an explanation in notes")
            if not gold.get("notes") and not (eligibility or {}).get("exclusion_reason"):
                raise ValueError("Unsuitable articles require an exclusion reason in notes")
            counts["unsuitable"] += 1
            continue
        sentence_map = {sentence["sentence_id"]: sentence for sentence in record["sentences"]}
        support = set(gold["supporting_sentence_ids"])
        if (
            not support
            or not isinstance(gold.get("focal_event_summary"), str)
            or not gold["focal_event_summary"].strip()
        ):
            raise ValueError(
                "Reviewed articles require a focal event and valid supporting sentence IDs"
            )
        counts["reviewed"] += 1
        counts[f"label_source:{gold['label_source']}"] += 1
        counts["reviewed_with_model_inspections"] += bool(gold.get("model_evidence_inspections"))
        cohort = cohorts.setdefault(gold.get("cohort") or "unspecified", Counter())
        cohort["articles"] += 1
        candidates = record["candidate_sentences"][:3]
        valid_candidate_ids = set(audits[record["article_id"]]["valid_candidate_sentence_ids"])
        top1 = bool(candidates and candidates[0]["sentence_id"] in support & valid_candidate_ids)
        top3 = bool(
            support & valid_candidate_ids & {sentence["sentence_id"] for sentence in candidates}
        )
        counts["top1_hits"] += top1
        counts["top3_hits"] += top3
        if is_protest_benchmark_article(gold):
            counts["protest_benchmark_reviewed"] += 1
            counts["protest_benchmark_top1_hits"] += top1
            counts["protest_benchmark_top3_hits"] += top3
        cohort["top3_hits"] += top3
        if not top3:
            misses.append(
                {
                    "article_id": record["article_id"],
                    "supporting_sentence_ids": sorted(support),
                    "candidate_sentence_ids": [s["sentence_id"] for s in candidates],
                }
            )
        for name, field in (("position", "position_score"), ("headline", "headline_score")):
            scored = [s for s in sentence_map.values() if field in s]
            if name == "headline" and not (record["headline"] or "").strip():
                continue
            counts[f"{name}_articles"] += 1
            ordered = sorted(scored, key=lambda s: (-s[field], s["sentence_id"]))
            counts[f"{name}_top1_hits"] += bool(ordered and ordered[0]["sentence_id"] in support)
            counts[f"{name}_top3_hits"] += bool(support & {s["sentence_id"] for s in ordered[:3]})
        if gold.get("gold_entities") is None:
            continue
        ner = gold.get("ner_annotation")
        if ner is not None and ner["review_status"] != "REVIEWED":
            counts["ner_draft_articles"] += 1
            continue
        counts[f"ner_label_source:{ner['label_source'] if ner else gold['label_source']}"] += 1
        counts["ner_legacy_articles"] += ner is None
        gold_entities = gold["gold_entities"]
        expected = {entity_key(entity) for entity in gold_entities}
        predicted = {
            entity_key(entity) for sentence in candidates for entity in sentence["entities"]
        }
        candidate_expected = {
            entity_key(entity)
            for entity in gold_entities
            if any(
                s["start_char"] <= entity["start_char"] < entity["end_char"] <= s["end_char"]
                for s in candidates
            )
        }
        counts["ner_annotated_articles"] += 1
        counts["ner_true_positive"] += len(predicted & expected)
        counts["ner_predicted"] += len(predicted)
        counts["ner_gold"] += len(expected)
        counts["ner_candidate_gold"] += len(candidate_expected)
    return {
        "reviewed_articles": counts["reviewed"],
        "unreviewed_articles": counts["unreviewed"],
        "unsuitable_articles": counts["unsuitable"],
        "annotation_provenance": {
            "reviewed_label_sources": {
                key.removeprefix("label_source:"): value
                for key, value in counts.items()
                if key.startswith("label_source:")
            },
            "reviewed_with_model_evidence_inspections": counts["reviewed_with_model_inspections"],
        },
        "top1_accuracy": ratio(counts["top1_hits"], counts["reviewed"]),
        "top3_recall": ratio(counts["top3_hits"], counts["reviewed"]),
        "protest_benchmark": {
            "reviewed_articles": counts["protest_benchmark_reviewed"],
            "top1_accuracy": ratio(
                counts["protest_benchmark_top1_hits"], counts["protest_benchmark_reviewed"]
            ),
            "top3_recall": ratio(
                counts["protest_benchmark_top3_hits"], counts["protest_benchmark_reviewed"]
            ),
        },
        "article_screening": {
            "reviewed_articles": counts["screening_reviewed"],
            "labels": {field: dict(values) for field, values in screening_counts.items()},
        },
        "baselines": {
            name: {
                "articles": counts[f"{name}_articles"],
                "top1_accuracy": ratio(counts[f"{name}_top1_hits"], counts[f"{name}_articles"]),
                "top3_recall": ratio(counts[f"{name}_top3_hits"], counts[f"{name}_articles"]),
            }
            for name in ("position", "headline")
        },
        "ner": {
            "annotated_articles": counts["ner_annotated_articles"],
            "draft_articles": counts["ner_draft_articles"],
            "legacy_annotated_articles": counts["ner_legacy_articles"],
            "label_sources": {
                key.removeprefix("ner_label_source:"): value
                for key, value in counts.items()
                if key.startswith("ner_label_source:")
            },
            "precision": ratio(counts["ner_true_positive"], counts["ner_predicted"]),
            "recall_full_article": ratio(counts["ner_true_positive"], counts["ner_gold"]),
            "recall_within_candidates": ratio(
                counts["ner_true_positive"], counts["ner_candidate_gold"]
            ),
            "true_positive": counts["ner_true_positive"],
            "predicted": counts["ner_predicted"],
            "gold": counts["ner_gold"],
        },
        "evidence_validity": ratio(audit_valid, audit_total),
        "evidence_valid_spans": audit_valid,
        "evidence_total_spans": audit_total,
        "evidence_consistency": {
            "audited_articles": len(records),
            "consistent_articles": len(records) - len(consistency_issues),
            "inconsistent_articles": len(consistency_issues),
            "issues": consistency_issues,
        },
        "processing_counts": {
            key.removeprefix("processing:"): value
            for key, value in counts.items()
            if key.startswith("processing:")
        },
        "cohorts": {
            name: {
                "articles": value["articles"],
                "top3_recall": ratio(value["top3_hits"], value["articles"]),
            }
            for name, value in cohorts.items()
        },
        "top3_misses": misses,
    }
