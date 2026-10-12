import argparse
import asyncio
import copy
import gzip
import importlib
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

import asyncpg
import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

screening = importlib.import_module("focal_event_screening")
candidate_observations = screening.candidate_observations
cue_spans = screening.cue_spans
load_screened_articles = screening.load_screened_articles
screen_article = screening.screen_article
validate_screening = screening.validate_screening
annotation_template = importlib.import_module("focal_event_evaluation").annotation_template
segment_articles = importlib.import_module("focal_events").segment_articles


def load_cli():
    spec = importlib.util.spec_from_file_location(
        "screen_focal_events", ROOT / "pipeline" / "16_extract_focal_events.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation(url="https://example.test/protest"):
    return {
        "GlobalEventID": "100",
        "day": 20240725,
        "EventCode": "141",
        "EventRootCode": "14",
        "ActionGeo_CountryCode": "IN",
        "SOURCEURL": url,
    }


def article(raw_path=None, text="Farmers protested in Delhi on Monday."):
    return {
        "document_id": 10,
        "url_key": "https://example.test/protest",
        "source_url": "https://example.test/protest",
        "final_url": None,
        "title": "Farmers protest",
        "cleaned_text": text,
        "status": "extracted",
        "raw_html_path": str(raw_path) if raw_path else None,
        "extractor_version": "old-extractor",
    }


def write_parquet(path, rows):
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE TABLE events (
                GlobalEventID VARCHAR, day BIGINT, EventCode VARCHAR,
                EventRootCode VARCHAR, ActionGeo_CountryCode VARCHAR, SOURCEURL VARCHAR
            )
            """
        )
        connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", rows)
        connection.execute("COPY events TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def test_candidate_scope_dates_country_roots_and_normalized_urls(tmp_path):
    path = tmp_path / "events.parquet"
    write_parquet(
        path,
        [
            ("100", 20240101, "141", "14", "IN", "https://example.test/protest#lead"),
            ("101", 20241231, "145", "14", "IN", "https://example.test/protest"),
            ("102", 20240101, "190", "19", "IN", "https://example.test/clash"),
            ("103", 20240101, "141", "14", "NP", "https://example.test/nepal"),
            ("104", 20250101, "141", "14", "IN", "https://example.test/new-year"),
            ("105", 20231231, "141", "14", "IN", "https://example.test/old-year"),
            ("106", 20240101, "141", "14", "IN", "not-a-url"),
        ],
    )
    selected = candidate_observations(path, ["14"])
    assert list(selected) == ["https://example.test/protest"]
    assert [r["GlobalEventID"] for r in selected["https://example.test/protest"]] == ["100", "101"]
    broader = candidate_observations(path, ["14", "19"])
    assert "https://example.test/clash" in broader
    assert candidate_observations(path, ["14"]) == selected


@pytest.mark.parametrize("roots", [[], ["1"], ["14 OR TRUE"]])
def test_invalid_roots_fail_before_sql(tmp_path, roots):
    with pytest.raises(ValueError, match="two-digit"):
        candidate_observations(tmp_path / "missing.parquet", roots)


def test_cues_preserve_unicode_offsets_without_claiming_event_relevance():
    text = "🪧 Officials denied protests. Historians described a strike in 1993."
    spans = cue_spans(text)
    assert [s["text"] for s in spans] == ["protests", "strike"]
    assert all(text[s["start_char"] : s["end_char"]] == s["text"] for s in spans)
    record = screen_article(article(text=text), [observation()], 100)
    assert record["relevance_status"] == "PENDING_REVIEW"
    assert record["text_quality"]["status"] == "UNVERIFIED"
    assert record["stored_article"]["cleaned_text"] == text
    validate_screening(record)


def test_current_extractor_rejects_title_only_and_preserves_both_snapshots(tmp_path):
    raw = tmp_path / "title.html.gz"
    with gzip.open(raw, "wb") as target:
        target.write(b"<html><head><title>Farmers protest</title></head><body></body></html>")
    source = article(raw, "Farmers protest")
    original = copy.deepcopy(source)
    record = screen_article(source, [observation()], 100)
    assert source == original
    assert record["stored_article"]["cleaned_text"] == "Farmers protest"
    assert record["reprocessing"]["status"] == "COMPLETE"
    assert record["reprocessing"]["raw_html_sha256"]
    assert record["text_quality"]["status"] == "UNSUITABLE"
    path = tmp_path / "screened.jsonl"
    load_cli().write_jsonl(path, [record])
    selected, manifest = load_screened_articles(path)
    assert selected == []
    assert manifest["skipped_articles"][0]["article_id"] == "10"


def test_short_report_is_flagged_and_retained_for_inference(tmp_path):
    from article_extractor import ExtractionResult

    text = "Farmers protested outside the district administration offices. " * 10
    raw = tmp_path / "short.html.gz"
    with gzip.open(raw, "wb") as target:
        target.write(b"stored HTML")
    import focal_event_screening as screening

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            screening,
            "extract_article",
            lambda *args, **kwargs: ExtractionResult("extracted", "Farmers protest", text),
        )
        record = screen_article(article(raw), [observation()], 100)
    assert record["text_quality"]["status"] == "SHORT_REVIEW"
    assert record["text_quality"]["word_count"] == 70
    path = tmp_path / "screened.jsonl"
    load_cli().write_jsonl(path, [record])
    selected, manifest = load_screened_articles(path)
    assert len(selected) == 1
    assert manifest["skipped_articles"] == []
    assert selected[0]["cleaned_text"] == text
    assert selected[0]["gdelt_observations"][0]["GlobalEventID"] == "100"


def test_missing_raw_and_no_cues_remain_uncertain(tmp_path):
    record = screen_article(
        article(tmp_path / "missing.html.gz", "Motorcycle sales increased in April. " * 25),
        [observation()],
        100,
    )
    assert record["text_quality"]["status"] == "UNVERIFIED"
    assert record["reprocessing"]["status"] == "ERROR"
    assert "no-protest-cue-in-body" in record["text_quality"]["flags"]
    assert record["relevance_status"] == "PENDING_REVIEW"
    validate_screening(record)


@pytest.mark.parametrize("mutation", ["text", "stored_text", "id", "cue", "url", "country", "year"])
def test_changed_screening_evidence_is_rejected(mutation):
    record = screen_article(article(), [observation()], 100)
    if mutation == "text":
        record["article"]["cleaned_text"] += "changed"
    elif mutation == "stored_text":
        record["stored_article"]["cleaned_text"] += "changed"
    elif mutation == "id":
        record["article_id"] = "11"
    elif mutation == "cue":
        record["protest_cues"]["body"][0]["start_char"] += 1
    elif mutation == "url":
        record["gdelt_observations"][0]["SOURCEURL"] = "https://example.test/wrong"
    elif mutation == "country":
        record["gdelt_observations"][0]["ActionGeo_CountryCode"] = "NP"
    else:
        record["gdelt_observations"][0]["day"] = 20250101
    with pytest.raises(ValueError):
        validate_screening(record)


def test_screening_metadata_reaches_results_and_annotations(tmp_path):
    import spacy

    record = screen_article(article(), [observation()], 100)
    path = tmp_path / "screening.jsonl"
    load_cli().write_jsonl(path, [record])
    articles, _ = load_screened_articles(path)
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    result = segment_articles(articles, nlp, 2)[0]
    assert result["screening"]["relevance_status"] == "PENDING_REVIEW"
    gold = annotation_template(result)
    assert gold["source_metadata"]["gdelt_observations"] == [observation()]
    assert gold["screening"]["text_quality"]["status"] == "UNVERIFIED"
    assert gold["article_text"] == articles[0]["cleaned_text"]


def test_selection_manifest_rejects_an_altered_screening_batch(tmp_path):
    record = screen_article(article(), [observation()], 100)
    path = tmp_path / "screened.jsonl"
    load_cli().write_jsonl(path, [record])
    path.with_suffix(".manifest.json").write_text(
        json.dumps({"output_sha256": "changed", "article_ids": ["10"]})
    )
    with pytest.raises(ValueError, match="selection manifest"):
        load_screened_articles(path)


def test_screening_postgres_cli_and_snapshot_integration(tmp_path):
    cli = load_cli()
    database_url = os.environ.get("ARTICLE_DATABASE_URL", cli.DEFAULT_DATABASE_URL)
    url = f"https://example.test/protest-screen-{uuid.uuid4()}"
    unrelated = f"https://example.test/not-screened-{uuid.uuid4()}"
    events_path = tmp_path / "events.parquet"
    write_parquet(events_path, [("100", 20240725, "141", "14", "IN", url)])

    async def run():
        connection = await asyncpg.connect(database_url, timeout=2)
        try:
            for candidate in (url, unrelated):
                await connection.execute(
                    """
                    INSERT INTO article_documents (url_key, source_url, status, title, cleaned_text)
                    VALUES ($1, $1, 'extracted', 'Farmers protest', $2)
                    """,
                    candidate,
                    "Farmers protested in Delhi.",
                )
            selected = await cli.select_articles(database_url, 10, "test", [], [url])
            assert [r["url_key"] for r in selected] == [url]
            assert await cli.select_articles(database_url, 10, "test", [], []) == []
            return selected[0]["document_id"]
        finally:
            await connection.close()

    async def cleanup():
        connection = await asyncpg.connect(database_url, timeout=2)
        try:
            await connection.execute(
                "DELETE FROM article_documents WHERE url_key=ANY($1::text[])", [url, unrelated]
            )
        finally:
            await connection.close()

    try:
        document_id = asyncio.run(run())
    except (OSError, asyncpg.PostgresConnectionError) as error:
        pytest.skip(f"local Postgres is unavailable: {error}")
    try:
        args = argparse.Namespace(
            output=tmp_path / "screening.jsonl",
            events_input=events_path,
            root_code=["14"],
            database_url=database_url,
            limit=10,
            seed="test",
            short_word_threshold=100,
        )
        manifest = cli.screen(args)
        assert manifest["article_ids"] == [str(document_id)]
        assert manifest["candidate_url_count"] == 1
        selected, input_manifest = load_screened_articles(args.output)
        assert selected[0]["url_key"] == url
        assert input_manifest["quality_counts"] == {"UNVERIFIED": 1}
        assert json.loads(args.output.with_suffix(".manifest.json").read_text()) == manifest
        with pytest.raises(FileExistsError):
            cli.screen(args)
    finally:
        asyncio.run(cleanup())
