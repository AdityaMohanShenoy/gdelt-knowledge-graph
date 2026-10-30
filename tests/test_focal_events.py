import argparse
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import pytest
import spacy
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

evaluation = importlib.import_module("focal_event_evaluation")
extraction = importlib.import_module("focal_events")
annotation_template = evaluation.annotation_template
evaluate = evaluation.evaluate
evidence_audit = evaluation.evidence_audit
read_jsonl = evaluation.read_jsonl
ENTITY_SCHEMA = extraction.ENTITY_SCHEMA
FocalEventPipeline = extraction.FocalEventPipeline
RankingConfig = extraction.RankingConfig
load_pipeline = extraction.load_pipeline
normalize_entities = extraction.normalize_entities
rank_sentences = extraction.rank_sentences
segment_articles = extraction.segment_articles


def load_cli():
    spec = importlib.util.spec_from_file_location(
        "extract_focal_events", ROOT / "pipeline" / "10_extract_focal_events.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def nlp():
    return spacy.load("en_core_web_sm", disable=["ner"])


class Tokenizer:
    def encode(self, text):
        return text.split() + ["start", "end"]


class Embedder:
    tokenizer = Tokenizer()
    max_seq_length = 512

    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        return np.array([[1.0, 0.0] if "arrest" in text.lower() else [0.0, 1.0] for text in texts])


class NER:
    def __init__(self):
        self.calls = []

    def batch_extract_entities(self, texts, labels, **kwargs):
        self.calls.append((texts, labels, kwargs))
        return [
            {
                "entities": {
                    "LOCATION": [
                        {
                            "text": "Delhi",
                            "start": match.start(),
                            "end": match.end(),
                            "confidence": 0.9,
                        }
                        for match in re.finditer("Delhi", text)
                    ],
                }
            }
            for text in texts
        ]


def article(document_id=1, text=None, title="Police arrest protesters in Delhi"):
    return {
        "document_id": document_id,
        "title": title,
        "cleaned_text": text
        if text is not None
        else (
            "  Police arrested protesters in Delhi.\n\n"
            "The unions held a march. Officials met leaders.\r\n"
            "The campaign started in 2020. Residents discussed their concerns.  "
        ),
        "source_url": "https://example.test/news",
        "status": "extracted",
    }


def make_pipeline(nlp, **kwargs):
    return FocalEventPipeline(
        nlp, Embedder(), NER(), RankingConfig(**kwargs), {"test": "deterministic doubles"}
    )


def reviewed(record, support=None, entities=None):
    gold = annotation_template(record)
    gold.update(
        {
            "review_status": "REVIEWED",
            "reviewer": "fixture-reviewer",
            "label_source": "human",
            "focal_event_summary": "Police arrests",
            "cohort": "single_event",
            "supporting_sentence_ids": support or [record["candidate_sentences"][0]["sentence_id"]],
            "gold_entities": entities,
        }
    )
    if entities is not None:
        gold["ner_annotation"].update(
            review_status="REVIEWED",
            reviewer="entity-fixture-reviewer",
            label_source="human",
            whole_article_checked=True,
            reviewed_at="2026-10-11T10:00:00Z",
        )
    return gold


def test_preserves_full_text_all_sentences_paragraphs_and_unicode_offsets(nlp):
    source = article(
        text="\n  Delhi residents protested.\n\nFarmers marched in Pune. Café workers joined.  \n"
    )
    record = make_pipeline(nlp).process([source])[0]
    assert record["article_text"] == source["cleaned_text"]
    assert len(record["paragraphs"]) == 2
    assert len(record["sentences"]) == 3
    assert [s["sentence_id"] for s in record["sentences"]] == [1, 2, 3]
    assert record["publication_timestamp"] is None
    for span in record["sentences"] + record["paragraphs"]:
        assert record["article_text"][span["start_char"] : span["end_char"]] == span["text"]
    assert evidence_audit(record)["invalid_spans"] == []


def test_top_three_rank_and_source_order_are_separate_and_rest_retained(nlp):
    pipeline = make_pipeline(nlp)
    record = pipeline.process([article()])[0]
    assert len(record["sentences"]) == 5
    assert len(record["candidate_sentences"]) == 3
    assert [s["rank"] for s in record["candidate_sentences"]] == [1, 2, 3]
    assert record["candidate_sentence_ids_in_article_order"] == sorted(
        s["sentence_id"] for s in record["candidate_sentences"]
    )
    assert sum(s["ner_status"] == "NOT_SELECTED" for s in record["sentences"]) == 2
    assert len(pipeline.embedder.calls) == 1
    assert record["focal_event_status"] == "PENDING_REVIEW"
    assert record["processing_status"] == "COMPLETE"
    assert record["models"]["test"] == "deterministic doubles"


@pytest.mark.parametrize("text", ["", " \n\t ", None])
def test_empty_text_yields_no_evidence_without_model_calls(nlp, text):
    source = article()
    source["cleaned_text"] = text
    pipeline = make_pipeline(nlp)
    record = pipeline.process([source])[0]
    assert record["processing_status"] == "EMPTY_TEXT"
    assert record["sentences"] == record["candidate_sentences"] == []
    assert pipeline.embedder.calls == pipeline.ner.calls == []


@pytest.mark.parametrize("headline", [None, "", "  "])
def test_short_articles_and_missing_headlines_use_remaining_signals(nlp, headline):
    record = make_pipeline(nlp).process(
        [article(text="Farmers marched in Delhi.", title=headline)]
    )[0]
    sentence = record["candidate_sentences"][0]
    assert sentence["headline_similarity"] is None
    assert len(record["candidate_sentences"]) == 1
    assert sentence["importance_score"] == pytest.approx(
        (sentence["position_score"] + sentence["event_relevance"]) / 2
    )


@pytest.mark.parametrize(
    "config",
    [
        {"headline_weight": -1},
        {"event_weight": float("nan")},
        {"batch_size": 0},
        {"headline_weight": 0, "position_weight": 0, "event_weight": 0},
        {"position_weight": 0, "event_weight": 0},
        {"ner_threshold": 1.1},
        {"unknown": 1},
    ],
)
def test_invalid_configuration_is_rejected(config):
    with pytest.raises(ValidationError):
        RankingConfig(**config)


def test_later_event_can_outrank_lead_and_ties_are_deterministic():
    record: dict[str, Any] = {
        "headline": "A focal event",
        "sentences": [
            {"sentence_id": index, "event_relevance": float(index == 5)} for index in range(1, 6)
        ],
    }
    rank_sentences(record, [0, 0, 0, 0, 1], RankingConfig())
    assert record["candidate_sentences"][0]["sentence_id"] == 5
    rank_sentences(
        record, [0] * 5, RankingConfig(headline_weight=0, position_weight=0, event_weight=1)
    )
    assert [s["sentence_id"] for s in record["candidate_sentences"]] == [5, 1, 2]


def test_dependency_event_cues_prefer_actions_to_opinion(nlp):
    records = segment_articles(
        [article(text="Police arrested protesters. Analysts believe change is needed.")], nlp, 2
    )
    action, opinion = records[0]["sentences"]
    assert action["event_relevance"] > opinion["event_relevance"]
    assert "arrest" in action["event_cues"]["action_lemmas"]
    assert opinion["event_cues"]["reporting_or_opinion_root"]


def test_repeated_entity_text_has_distinct_exact_offsets(nlp):
    record = make_pipeline(nlp).process(
        [article(text="Delhi police arrested protesters in Delhi.")]
    )[0]
    entities = record["candidate_sentences"][0]["entities"]
    assert len(entities) == 2
    assert entities[0]["start_char"] != entities[1]["start_char"]
    assert evidence_audit(record)["invalid_spans"] == []


@pytest.mark.parametrize(
    "span",
    [
        {"text": "Delhi", "start": 1, "end": 6},
        {"text": "Delhi", "start": -1, "end": 5},
        {"text": "Delhi", "start": 0, "end": 100},
        {"text": "Delhi", "start": 0, "end": 5, "confidence": float("nan")},
    ],
)
def test_invalid_ner_spans_are_rejected(span):
    sentence: dict[str, Any] = {"text": "Delhi police marched.", "start_char": 10, "sentence_id": 1}
    with pytest.raises(ValueError):
        normalize_entities(
            {"entities": {"LOCATION": [span]}}, sentence, " " * 10 + sentence["text"], ENTITY_SCHEMA
        )


def test_failed_ner_never_looks_like_successful_empty_entities(nlp):
    pipeline = make_pipeline(nlp)
    pipeline.ner.batch_extract_entities = lambda texts, *args, **kwargs: [{} for _ in texts]
    record = pipeline.process([article()])[0]
    assert record["processing_status"] == "ERROR"
    assert record["candidate_sentences"]
    assert all(s["ner_status"] == "ERROR" for s in record["candidate_sentences"])
    assert record["article_text"] == article()["cleaned_text"]


def test_embedding_failure_preserves_all_source_evidence(nlp):
    pipeline = make_pipeline(nlp)
    pipeline.embedder.encode = lambda *args, **kwargs: np.array([[float("nan"), 1]])
    record = pipeline.process([article()])[0]
    assert record["processing_status"] == "ERROR"
    assert len(record["sentences"]) == 5
    assert record["errors"][0]["stage"] == "ranking"


def test_long_embeddings_are_explicitly_flagged(nlp):
    pipeline = make_pipeline(nlp)
    pipeline.embedder.max_seq_length = 3
    record = pipeline.process([article(text="Farmers marched in Delhi.")])[0]
    assert record["sentences"][0]["embedding_truncated"]
    assert record["headline_embedding_truncated"]
    assert pipeline.ner.calls[0][2]["max_len"] is None


def test_annotations_hide_predictions_and_undefined_metrics_stay_null(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    gold = annotation_template(record)
    assert "rank" not in gold["sentences"][0]
    assert len(gold["sentences"]) == 5
    metrics = evaluate([record], [gold])
    assert metrics["top3_recall"] is None
    assert metrics["ner"]["precision"] is None
    assert metrics["unreviewed_articles"] == 1


def test_model_inspection_provenance_is_reported_without_accepting_any_new_labels(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    gold = reviewed(record)
    gold["model_evidence_inspections"] = [
        {
            "filename": "predictions.jsonl",
            "input_sha256": "a" * 64,
            "viewed_at": "2026-10-11T14:00:00.000Z",
        }
    ]
    metrics = evaluate([record], [gold])
    assert metrics["annotation_provenance"] == {
        "reviewed_label_sources": {"human": 1},
        "reviewed_with_model_evidence_inspections": 1,
    }
    gold["review_status"] = "UNREVIEWED"
    metrics = evaluate([record], [gold])
    assert metrics["reviewed_articles"] == 0
    assert metrics["top3_recall"] is None
    assert metrics["annotation_provenance"]["reviewed_with_model_evidence_inspections"] == 0
    gold["model_evidence_inspections"].append(copy.deepcopy(gold["model_evidence_inspections"][0]))
    with pytest.raises(ValueError, match="Duplicate model"):
        evaluate([record], [gold])
    gold["model_evidence_inspections"][0]["viewed_at"] = "yesterday"
    with pytest.raises(ValueError, match="history"):
        evaluate([record], [gold])


def test_metrics_include_missed_evidence_and_exact_ner_matches(nlp):
    records = make_pipeline(nlp).process([article(1), article(2)])
    entities = [entity for s in records[0]["candidate_sentences"] for entity in s["entities"]]
    annotations = [reviewed(records[0], entities=entities), reviewed(records[1], support=[5])]
    metrics = evaluate(records, annotations)
    assert metrics["top1_accuracy"] == 0.5
    assert metrics["top3_recall"] == 0.5
    assert metrics["ner"]["precision"] == metrics["ner"]["recall_full_article"] == 1
    assert metrics["evidence_validity"] == 1
    assert metrics["top3_misses"][0]["article_id"] == "2"
    # Each gold set is one sentence, so the chance floor is the per-article
    # 1/N and 3/N averaged; Top-k is only meaningful above it.
    sizes = [len(r["sentences"]) for r in records]
    assert metrics["gold_support"]["mean_sentences"] == 1
    assert metrics["baselines"]["random"]["articles"] == 2
    assert metrics["baselines"]["random"]["top1_accuracy"] == sum(1 / n for n in sizes) / 2
    assert metrics["baselines"]["random"]["top3_recall"] == sum(
        evaluation.chance_hits(1, n)[1] for n in sizes
    ) / 2


def test_chance_floor_rises_with_support_size():
    chance = evaluation.chance_hits
    assert chance(2, 10) == (0.2, 1 - 56 / 120)  # C(8,3)/C(10,3) misses all three
    assert chance(10, 10) == (1.0, 1.0)
    assert chance(1, 2) == (0.5, 1.0)  # fewer than three sentences: Top-3 sees all
    assert chance(0, 0) == (0.0, 0.0)
    floors = [chance(k, 20) for k in range(1, 21)]
    assert floors == sorted(floors)


def test_ner_reports_retrieval_losses_separately(nlp):
    record = make_pipeline(nlp).process(
        [
            article(
                text=(
                    "Police arrested protesters in Delhi. Unions marched. Leaders met. "
                    "Officials resigned. Farmers rallied in Pune."
                )
            )
        ]
    )[0]
    entities = [entity for s in record["candidate_sentences"] for entity in s["entities"]]
    start = record["article_text"].index("Pune")
    entities.append(
        {"text": "Pune", "label": "LOCATION", "start_char": start, "end_char": start + 4}
    )
    metrics = evaluate([record], [reviewed(record, entities=entities)])
    assert metrics["ner"]["recall_full_article"] == 0.5
    assert metrics["ner"]["recall_within_candidates"] == 1


def test_partial_entity_annotations_do_not_score_ner_or_change_focal_metrics(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    entities = [entity for s in record["candidate_sentences"] for entity in s["entities"]]
    gold = reviewed(record, entities=entities)
    gold["ner_annotation"].update(
        review_status="UNREVIEWED", whole_article_checked=False, reviewed_at=None
    )
    metrics = evaluate([record], [gold])
    assert metrics["reviewed_articles"] == 1
    assert metrics["top3_recall"] == 1
    assert metrics["ner"]["annotated_articles"] == 0
    assert metrics["ner"]["draft_articles"] == 1
    assert metrics["ner"]["precision"] is None
    assert metrics["ner"]["recall_full_article"] is None


def test_complete_and_legacy_entity_annotations_report_separate_provenance(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    entities = [entity for s in record["candidate_sentences"] for entity in s["entities"]]
    gold = reviewed(record, entities=entities)
    current = evaluate([record], [gold])["ner"]
    assert current["annotated_articles"] == 1
    assert current["legacy_annotated_articles"] == 0
    assert current["label_sources"] == {"human": 1}
    assert current["precision"] == 1
    del gold["ner_annotation"]
    del gold["entity_schema"]
    legacy = evaluate([record], [gold])["ner"]
    assert legacy["legacy_annotated_articles"] == 1
    assert legacy["precision"] == current["precision"]
    empty = evaluate([record], [reviewed(record, entities=[])])["ner"]
    assert empty["annotated_articles"] == 1
    assert empty["gold"] == 0
    assert empty["precision"] == 0
    assert empty["recall_full_article"] is None


@pytest.mark.parametrize(
    "mutation",
    ["reviewer", "provenance", "unchecked", "timestamp", "null_entities", "status", "schema"],
)
def test_invalid_entity_review_metadata_rejected_even_for_event_drafts(nlp, mutation):
    record = make_pipeline(nlp).process([article()])[0]
    gold = reviewed(record, entities=[])
    gold["review_status"] = "UNREVIEWED"
    if mutation == "reviewer":
        gold["ner_annotation"]["reviewer"] = " "
    elif mutation == "provenance":
        gold["ner_annotation"]["label_source"] = None
    elif mutation == "unchecked":
        gold["ner_annotation"]["whole_article_checked"] = False
    elif mutation == "timestamp":
        gold["ner_annotation"]["reviewed_at"] = "not a timestamp"
    elif mutation == "null_entities":
        gold["gold_entities"] = None
    elif mutation == "status":
        gold["ner_annotation"]["review_status"] = "ACCEPTED"
    else:
        gold["entity_schema"] = {"EVENT": "events"}
    with pytest.raises(ValueError):
        evaluate([record], [gold])


def test_protest_benchmark_requires_separate_relevance_quality_and_scope_review(nlp):
    records = make_pipeline(nlp).process([article(index) for index in range(1, 6)])
    gold = [reviewed(record) for record in records]
    for annotation in gold:
        annotation["eligibility"].update(
            review_status="REVIEWED",
            reviewer="Screening reviewer",
            protest_relevance="PROTEST",
            body_quality="COMPLETE",
            scope="INDIA_2024",
        )
    gold[1]["eligibility"]["body_quality"] = "LIMITED"
    gold[2]["eligibility"]["scope"] = "UNCERTAIN"
    gold[3]["eligibility"]["protest_relevance"] = "UNRELATED"
    gold[4]["review_status"] = "UNREVIEWED"
    metrics = evaluate(records, gold)
    assert metrics["reviewed_articles"] == 4
    assert metrics["protest_benchmark"]["reviewed_articles"] == 1
    assert metrics["protest_benchmark"]["top3_recall"] == 1
    assert metrics["article_screening"]["reviewed_articles"] == 5
    assert metrics["article_screening"]["labels"]["body_quality"] == {"COMPLETE": 4, "LIMITED": 1}


def test_screening_alone_does_not_validate_focal_event_and_invalid_labels_fail(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    gold = annotation_template(record)
    gold["eligibility"].update(
        review_status="REVIEWED",
        reviewer="Screening reviewer",
        protest_relevance="PROTEST",
        body_quality="COMPLETE",
        scope="INDIA_2024",
    )
    assert evaluate([record], [gold])["protest_benchmark"]["reviewed_articles"] == 0
    gold["eligibility"]["protest_relevance"] = "POLITICS"
    with pytest.raises(ValueError, match="screening label"):
        evaluate([record], [gold])
    legacy = reviewed(record)
    del legacy["eligibility"]
    assert evaluate([record], [legacy])["reviewed_articles"] == 1
    assert evaluate([record], [legacy])["protest_benchmark"]["reviewed_articles"] == 0
    draft = annotation_template(record)
    draft["eligibility"].update(protest_relevance="PROTEST", body_quality="COMPLETE")
    draft_metrics = evaluate([record], [draft])
    assert draft_metrics["article_screening"]["labels"]["protest_relevance"] == {}


def test_reviewed_processing_failure_stays_in_ranking_denominator(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    gold = reviewed(record)
    record["candidate_sentences"] = []
    record["processing_status"] = "ERROR"
    metrics = evaluate([record], [gold])
    assert metrics["reviewed_articles"] == 1
    assert metrics["top3_recall"] == 0


@pytest.mark.parametrize("mutation", ["hash", "segmentation", "reviewer", "support", "entity"])
def test_invalid_gold_or_changed_snapshot_is_rejected(nlp, mutation):
    record = make_pipeline(nlp).process([article()])[0]
    gold = reviewed(record)
    if mutation == "hash":
        gold["article_text_sha256"] = "changed"
    elif mutation == "segmentation":
        gold["sentences"][0]["start_char"] += 1
    elif mutation == "reviewer":
        gold["reviewer"] = None
    elif mutation == "support":
        gold["supporting_sentence_ids"] = [999]
    else:
        gold["gold_entities"] = [
            {"text": "wrong", "label": "PERSON", "start_char": 0, "end_char": 5}
        ]
    with pytest.raises(ValueError):
        evaluate([record], [gold])


def test_split_filter_and_unsuitable_exclusions_are_explicit(nlp):
    records = make_pipeline(nlp).process([article(1), article(2)])
    gold = [reviewed(record) for record in records]
    gold[0]["split"] = "test"
    gold[1].update(
        {
            "split": "test",
            "review_status": "UNSUITABLE",
            "notes": "No identifiable focal development",
        }
    )
    metrics = evaluate(records, gold, "test")
    assert metrics["reviewed_articles"] == metrics["unsuitable_articles"] == 1


def test_evidence_audit_finds_sentence_relative_offset_corruption(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    record["candidate_sentences"][0]["entities"][0]["sentence_start_char"] += 1
    assert evidence_audit(record)["invalid_spans"][0]["kind"] == "entity"


@pytest.mark.parametrize("mutation", ["missing", "boolean"])
def test_entity_sentence_reference_requires_an_integer_id(nlp, mutation):
    record = make_pipeline(nlp).process([article()])[0]
    entity = record["candidate_sentences"][0]["entities"][0]
    if mutation == "missing":
        del entity["sentence_id"]
    else:
        entity["sentence_id"] = True
    audit = evidence_audit(record)
    assert not audit["consistent"]
    assert audit["invalid_spans"][0]["kind"] == "entity"


def test_annotation_cannot_remove_or_change_source_metadata(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    record["source_metadata"] = {"gdelt_observations": [{"GlobalEventID": 123}]}
    record["screening"] = {"quality_status": "READABLE"}
    for field in ("screening", "source_metadata"):
        gold = copy.deepcopy(annotation_template(record))
        del gold[field]
        with pytest.raises(ValueError, match="source metadata"):
            evaluate([record], [gold])
        gold[field] = {"changed": True}
        with pytest.raises(ValueError, match="source metadata"):
            evaluate([record], [gold])


def test_legacy_unscreened_annotation_can_omit_source_metadata(nlp):
    record = make_pipeline(nlp).process([article()])[0]
    gold = annotation_template(record)
    assert "source_metadata" in record and "source_metadata" not in gold
    assert evaluate([record], [gold])["unreviewed_articles"] == 1
    gold["source_metadata"] = {"changed": True}
    with pytest.raises(ValueError, match="source metadata"):
        evaluate([record], [gold])


@pytest.mark.parametrize("status", ["UNREVIEWED", "REVIEWED", "UNSUITABLE"])
@pytest.mark.parametrize(
    "mutation", ["text", "headline", "duplicate_sentence", "sentence_order", "paragraph"]
)
def test_all_annotation_statuses_require_the_exact_snapshot(nlp, status, mutation):
    record = make_pipeline(nlp).process([article()])[0]
    gold = reviewed(record)
    gold.update(review_status=status, notes="Excluded fixture")
    if mutation == "text":
        gold["article_text"] += "Extra text with the old hash."
    elif mutation == "headline":
        gold["headline"] = "Different article headline"
    elif mutation == "duplicate_sentence":
        gold["sentences"].append(copy.deepcopy(gold["sentences"][0]))
    elif mutation == "sentence_order":
        gold["sentences"].reverse()
    else:
        gold["sentences"][0]["paragraph_id"] = 99
    with pytest.raises(ValueError, match="snapshots|segmentation"):
        evaluate([record], [gold])


@pytest.mark.parametrize(
    "mutation", ["support_duplicate", "support_boolean", "entity_duplicate", "entity_label"]
)
def test_draft_annotations_cannot_hide_invalid_support_or_entities(nlp, mutation):
    record = make_pipeline(nlp).process([article()])[0]
    gold = annotation_template(record)
    if mutation == "support_duplicate":
        gold["supporting_sentence_ids"] = [1, 1]
    elif mutation == "support_boolean":
        gold["supporting_sentence_ids"] = [True]
    else:
        entity = copy.deepcopy(record["candidate_sentences"][0]["entities"][0])
        if mutation == "entity_duplicate":
            gold["gold_entities"] = [entity, copy.deepcopy(entity)]
        else:
            entity["label"] = "UNSUPPORTED"
            gold["gold_entities"] = [entity]
    with pytest.raises(ValueError):
        evaluate([record], [gold])


def test_mismatched_candidate_reference_cannot_be_a_focal_hit(nlp):
    record = json.loads(json.dumps(make_pipeline(nlp).process([article()])[0]))
    gold = reviewed(record, support=[5])
    candidate = record["candidate_sentences"][0]
    candidate["sentence_id"] = 5
    for entity in candidate["entities"]:
        entity["sentence_id"] = 5
    record["candidate_sentences"] = [candidate]
    record["candidate_sentence_ids_in_article_order"] = [5]
    assert (
        record["article_text"][candidate["start_char"] : candidate["end_char"]] == candidate["text"]
    )
    audit = evidence_audit(record)
    assert not audit["consistent"]
    assert audit["valid_candidate_sentence_ids"] == []
    metrics = evaluate([record], [gold])
    assert metrics["top1_accuracy"] == metrics["top3_recall"] == 0
    assert metrics["evidence_consistency"]["inconsistent_articles"] == 1


def test_top3_recall_does_not_count_a_fourth_candidate(nlp):
    record = json.loads(json.dumps(make_pipeline(nlp).process([article()])[0]))
    gold = reviewed(record, support=[4])
    record["candidate_sentences"].append(copy.deepcopy(record["sentences"][3]))
    record["candidate_sentence_ids_in_article_order"] = [1, 2, 3, 4]
    metrics = evaluate([record], [gold])
    assert metrics["top3_recall"] == 0
    assert (
        "more-than-three-candidate-sentences"
        in metrics["evidence_consistency"]["issues"][0]["structural_errors"]
    )


@pytest.mark.parametrize(
    "mutation",
    ["hash", "missing_sentence", "duplicate_id", "source_order", "entity_label", "confidence"],
)
def test_structural_evidence_audit_detects_corruption(nlp, mutation):
    record = json.loads(json.dumps(make_pipeline(nlp).process([article()])[0]))
    if mutation == "hash":
        record["article_text_sha256"] = "changed"
    elif mutation == "missing_sentence":
        record["sentences"].pop()
    elif mutation == "duplicate_id":
        record["sentences"][1]["sentence_id"] = 1
    elif mutation == "source_order":
        record["candidate_sentence_ids_in_article_order"].reverse()
    elif mutation == "entity_label":
        record["candidate_sentences"][0]["entities"][0]["label"] = "UNSUPPORTED"
    else:
        record["candidate_sentences"][0]["entities"][0]["confidence"] = 2.0
    assert not evidence_audit(record)["consistent"]


def test_cli_audit_persists_corruption_report_and_fails_without_mutating_input(tmp_path, nlp):
    cli = load_cli()
    record = make_pipeline(nlp).process([article()])[0]
    path, report = tmp_path / "results.jsonl", tmp_path / "audit.json"
    cli.write_jsonl(path, [record])
    command = [sys.executable, str(ROOT / "pipeline" / "10_extract_focal_events.py")]
    result = subprocess.run(
        command + ["audit", "--input", str(path), "--output", str(report)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(report.read_text())["evidence_consistency"]["consistent_articles"] == 1
    record["article_text_sha256"] = "changed"
    broken, failure_report = tmp_path / "broken.jsonl", tmp_path / "broken.audit.json"
    cli.write_jsonl(broken, [record])
    original = broken.read_bytes()
    result = subprocess.run(
        command + ["audit", "--input", str(broken), "--output", str(failure_report)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    audit = json.loads(failure_report.read_text())
    assert audit["evidence_validity"] == 1
    assert audit["evidence_consistency"]["inconsistent_articles"] == 1
    assert audit["evidence_consistency"]["issues"][0]["structural_errors"] == [
        "article-text-hash-mismatch"
    ]
    assert broken.read_bytes() == original
    assert (
        subprocess.run(
            command + ["audit", "--input", str(broken), "--output", str(failure_report)],
            capture_output=True,
        ).returncode
        != 0
    )
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert (
        subprocess.run(command + ["audit", "--input", str(empty)], capture_output=True).returncode
        != 0
    )


def test_cli_evaluation_saves_invalid_candidate_report_and_fails(tmp_path, nlp):
    cli = load_cli()
    record = json.loads(json.dumps(make_pipeline(nlp).process([article()])[0]))
    gold = reviewed(record, support=[1])
    record["candidate_sentences"][0]["sentence_id"] = 5
    input_path = tmp_path / "results.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    report_path = tmp_path / "metrics.json"
    cli.write_jsonl(input_path, [record])
    cli.write_jsonl(gold_path, [gold])
    original = input_path.read_bytes(), gold_path.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "pipeline" / "10_extract_focal_events.py"),
            "evaluate",
            "--input",
            str(input_path),
            "--annotations",
            str(gold_path),
            "--output",
            str(report_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(report_path.read_text())
    assert report["top1_accuracy"] == report["top3_recall"] == 0
    assert report["evidence_consistency"]["issues"][0]["article_id"] == "1"
    assert (input_path.read_bytes(), gold_path.read_bytes()) == original


def test_jsonl_rejects_nonfinite_numbers_and_nonobject_records(tmp_path):
    path = tmp_path / "invalid.jsonl"
    for text in (
        '{"article_id":"1","confidence":NaN}',
        '{"article_id":"1","score":1e999}',
        "null",
        '{"article_id":1}',
    ):
        path.write_text(text + "\n")
        with pytest.raises(ValueError, match="line 1"):
            read_jsonl(path)


def test_cli_annotation_and_evaluation_roundtrip_without_inference(tmp_path, nlp):
    cli = load_cli()
    record = make_pipeline(nlp).process([article()])[0]
    input_path, gold_path = tmp_path / "results.jsonl", tmp_path / "gold.jsonl"
    cli.write_jsonl(input_path, [record])
    command = [sys.executable, str(ROOT / "pipeline" / "10_extract_focal_events.py")]
    subprocess.run(
        command + ["annotate", "--input", str(input_path), "--output", str(gold_path)],
        check=True,
        capture_output=True,
    )
    assert read_jsonl(gold_path)[0]["article_id"] == "1"
    result = subprocess.run(
        command + ["evaluate", "--input", str(input_path), "--annotations", str(gold_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["top3_recall"] is None
    with pytest.raises(FileExistsError):
        cli.write_jsonl(input_path, [record])
    with pytest.raises(ValueError):
        evaluate([record, copy.deepcopy(record)], [])


def test_cli_extract_persists_manifest_configuration_and_full_evidence(tmp_path, monkeypatch, nlp):
    cli = load_cli()
    model_manifest = tmp_path / "models.json"
    model_manifest.write_text("{}")
    config_path = tmp_path / "config.json"
    config_path.write_text('{"headline_weight": 0.3, "batch_size": 2}')

    async def select(*args):
        return [article(1), article(2)]

    monkeypatch.setattr(cli, "select_articles", select)
    monkeypatch.setattr(
        cli,
        "load_pipeline",
        lambda models, config: FocalEventPipeline(
            nlp,
            Embedder(),
            NER(),
            config,
            models,
        ),
    )
    args = argparse.Namespace(
        output=tmp_path / "extraction.jsonl",
        config=config_path,
        model_manifest=model_manifest,
        database_url="unused",
        limit=2,
        seed="fixture",
        article_id=[],
    )
    result = cli.extract(args)
    assert result["counts"] == {"COMPLETE": 2}
    persisted = read_jsonl(args.output)
    assert len(persisted[0]["sentences"]) == 5
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["ranking_config"]["headline_weight"] == 0.3
    assert manifest["article_ids"] == ["1", "2"]
    with pytest.raises(FileExistsError):
        cli.extract(args)


def test_postgres_to_persisted_results_integration(tmp_path, nlp):
    cli = load_cli()
    database_url = os.environ.get("ARTICLE_DATABASE_URL", cli.DEFAULT_DATABASE_URL)

    async def run():
        connection = await asyncpg.connect(database_url, timeout=2)
        url = f"https://example.test/focal-{uuid.uuid4()}"
        try:
            document_id = await connection.fetchval(
                """
                INSERT INTO article_documents (url_key, source_url, status, title, cleaned_text)
                VALUES ($1, $1, 'extracted', $2, $3) RETURNING document_id
            """,
                url,
                article()["title"],
                article()["cleaned_text"],
            )
            selected = await cli.select_articles(database_url, 1, "test", [document_id])
            assert selected[0]["document_id"] == document_id
            records = make_pipeline(nlp).process(selected)
            cli.write_jsonl(tmp_path / "results.jsonl", records)
            assert read_jsonl(tmp_path / "results.jsonl")[0]["article_id"] == str(document_id)
            with pytest.raises(ValueError, match="not found"):
                await cli.select_articles(database_url, 1, "test", [9223372036854775807])
        finally:
            await connection.execute("DELETE FROM article_documents WHERE url_key=$1", url)
            await connection.close()

    try:
        asyncio.run(run())
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")


def test_screened_snapshot_inference_retains_quality_exclusions_and_observations(
    tmp_path, monkeypatch, nlp
):
    screening = importlib.import_module("focal_event_screening")
    cli = load_cli()
    source = article()
    source["url_key"] = source["source_url"]
    observations = [
        {
            "GlobalEventID": "100",
            "day": 20240725,
            "EventCode": "141",
            "EventRootCode": "14",
            "ActionGeo_CountryCode": "IN",
            "SOURCEURL": source["url_key"],
        }
    ]
    screened = screening.screen_article(source, observations, 100)
    rejected_source = copy.deepcopy(source)
    rejected_source.update(document_id=2, status="insufficient_text")
    rejected = screening.screen_article(rejected_source, observations, 100)
    screening_path = tmp_path / "screening.jsonl"
    cli.write_jsonl(screening_path, [screened, rejected])
    models = tmp_path / "models.json"
    models.write_text("{}")
    monkeypatch.setattr(cli, "load_pipeline", lambda models, config: make_pipeline(nlp))

    async def unexpected_database(*args):
        raise AssertionError("Screened inference must use its frozen snapshots")

    monkeypatch.setattr(cli, "select_articles", unexpected_database)
    args = argparse.Namespace(
        output=tmp_path / "results.jsonl",
        config=None,
        model_manifest=models,
        screened_input=screening_path,
        article_id=[],
        database_url="unused",
        limit=40,
        seed="unused",
    )
    result = cli.extract(args)
    persisted = read_jsonl(args.output)
    assert len(persisted) == 1
    assert persisted[0]["article_text"] == screened["article"]["cleaned_text"]
    assert persisted[0]["screening"]["relevance_status"] == "PENDING_REVIEW"
    assert persisted[0]["source_metadata"]["gdelt_observations"] == observations
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["selection"] == "screened_snapshot"
    assert manifest["screening_input"]["skipped_articles"][0]["article_id"] == "2"
    assert annotation_template(persisted[0])["screening"] == persisted[0]["screening"]
    with pytest.raises(ValueError, match="cannot be combined"):
        args.output = tmp_path / "another.jsonl"
        args.article_id = [1]
        cli.extract(args)


def test_local_pretrained_models_end_to_end(monkeypatch):
    manifest_path = Path(
        os.environ.get(
            "FOCAL_EVENT_MODEL_MANIFEST",
            ROOT / "data" / "evidence" / "focal_events" / "models.json",
        )
    )
    if not manifest_path.exists():
        pytest.skip("Download the pretrained checkpoints with prepare-models first")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    pipeline = load_pipeline(json.loads(manifest_path.read_text()), RankingConfig(batch_size=2))
    record = pipeline.process([article(text="Police arrested protesters in Delhi on Monday.")])[0]
    assert record["processing_status"] == "COMPLETE", record["errors"]
    assert record["candidate_sentences"][0]["ner_status"] == "COMPLETE"
    assert any(entity["text"] == "Delhi" for entity in record["candidate_sentences"][0]["entities"])
    assert evidence_audit(record)["invalid_spans"] == []


def screened(gold, exclusion=None, reviewer="fixture-screener"):
    gold["eligibility"].update(
        review_status="REVIEWED",
        reviewer=reviewer,
        reviewed_at="2026-10-31T00:00:00Z",
        protest_relevance="PROTEST",
        body_quality="INSUFFICIENT" if exclusion == "INSUFFICIENT_TEXT" else "COMPLETE",
        scope="INDIA_2024",
        exclusion_reason=exclusion,
    )
    return gold


def excluded(record):
    gold = annotation_template(record)
    gold.update(review_status="UNSUITABLE", reviewer="fixture-reviewer", label_source="human")
    return screened(gold, exclusion="INSUFFICIENT_TEXT")


def test_evaluate_accepts_screening_only_exclusions_and_nothing_else(nlp):
    records = make_pipeline(nlp).process([article(1), article(2)])
    annotations = [screened(reviewed(records[0])), excluded(records[1])]
    metrics = evaluate(records[:1], annotations)  # article 2 never reached the ranker
    assert metrics["screening_only_articles"] == 1
    assert (metrics["reviewed_articles"], metrics["unsuitable_articles"]) == (1, 1)
    assert metrics["article_screening"]["labels"]["exclusion_reason"] == {"INSUFFICIENT_TEXT": 1}
    kept = screened(reviewed(records[1]))
    with pytest.raises(ValueError, match="Missing prediction"):
        evaluate(records[:1], [annotations[0], kept])
    tampered = copy.deepcopy(annotations[1])
    tampered["article_text"] += " changed"
    with pytest.raises(ValueError, match="Missing prediction"):
        evaluate(records[:1], [annotations[0], tampered])


def test_cli_freeze_is_reproducible_strips_drafts_and_guards_the_gold_name(tmp_path, nlp):
    cli = load_cli()
    records = make_pipeline(nlp).process([article(1), article(2), article(3)])
    annotations = [
        screened(reviewed(records[0])),
        excluded(records[1]),
        screened(reviewed(records[2])),
    ]
    for gold, name in zip(annotations, ("train", "dev", "test"), strict=True):
        gold["split"] = name
    annotations[0]["ai_proposal"] = {"cohort": "ongoing_protest"}
    predictions, splits = tmp_path / "predictions.jsonl", tmp_path / "splits.manifest.json"
    cli.write_jsonl(predictions, records[::2])  # article 2 is extraction-rejected
    assignment = {gold["article_id"]: gold["split"] for gold in annotations}
    splits.write_text(json.dumps({"assignment": assignment}))

    def freeze(items, output):
        source = tmp_path / f"{uuid.uuid4().hex}.input.jsonl"
        cli.write_jsonl(source, items)
        command = [sys.executable, str(ROOT / "pipeline" / "10_extract_focal_events.py"), "freeze"]
        command += ["--input", str(source), "--predictions", str(predictions)]
        command += ["--splits-manifest", str(splits), "--output", str(tmp_path / output)]
        return subprocess.run(command, text=True, capture_output=True, check=False)

    first, again = freeze(annotations, "a.gold.v1.jsonl"), freeze(annotations, "b.gold.v1.jsonl")
    assert first.returncode == again.returncode == 0, first.stderr
    frozen = tmp_path / "a.gold.v1.jsonl"
    assert frozen.read_bytes() == (tmp_path / "b.gold.v1.jsonl").read_bytes()
    manifest = json.loads(frozen.with_suffix(".manifest.json").read_text())
    assert manifest["output_sha256"] == hashlib.sha256(frozen.read_bytes()).hexdigest()
    assert manifest["dataset_kind"] == "gold"
    assert manifest["validation"]["screening_only_articles"] == 1
    assert "top1_accuracy" not in json.dumps(manifest)  # validation only, no scores
    assert all("ai_proposal" not in json.loads(line) for line in frozen.read_text().splitlines())
    evaluate(records[::2], read_jsonl(frozen))

    ai = copy.deepcopy(annotations)
    ai[0].update(reviewer="Claude (AI)", label_source="ai_assisted")
    refused = freeze(ai, "c.gold.v1.jsonl")
    assert refused.returncode != 0 and "AI labels" in refused.stderr
    assert not (tmp_path / "c.gold.v1.jsonl").exists()
    weak = freeze(ai, "c.weak.v1.jsonl")
    assert weak.returncode == 0, weak.stderr
    assert json.loads((tmp_path / "c.weak.v1.manifest.json").read_text())["dataset_kind"] == (
        "ai-assisted"
    )

    unreviewed = copy.deepcopy(annotations)
    unreviewed[2]["review_status"] = "UNREVIEWED"
    moved = copy.deepcopy(annotations)
    moved[2]["split"] = "dev"
    for items, message in ((unreviewed, "not reviewed"), (moved, "split dev != test")):
        result = freeze(items, "d.weak.v1.jsonl")
        assert result.returncode != 0 and message in result.stderr
