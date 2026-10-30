import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
SCRIPT = ROOT / "frontend" / "review.js"


def load_api():
    spec = importlib.util.spec_from_file_location(
        "review_viewer", ROOT / "pipeline" / "08_run_viewer.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def annotation_records():
    sentences = [
        "🪧 Farmers marched in Delhi.",
        "The union met officials.",
        "The campaign began in 2020.",
        "Analysts discussed reform.",
        "Police arrested protesters on Monday.",
    ]
    text = " ".join(sentences[:2]) + "\n" + " ".join(sentences[2:4]) + "\n" + sentences[4]
    spans = []
    for index, sentence in enumerate(sentences):
        start = text.index(sentence)
        spans.append(
            {
                "sentence_id": index + 1,
                "paragraph_id": index // 2 + 1,
                "text": sentence,
                "start_char": start,
                "end_char": start + len(sentence),
            }
        )
    records: list[dict[str, Any]] = []
    for index, headline in enumerate(
        [
            "Farmers march as police arrest protesters",
            '<img src="x" onerror="window.injected=true"> Historical background',
            "Government announces a new policy",
        ]
    ):
        start = text.index("Delhi")
        records.append(
            {
                "schema_version": "focal-event-gold.v1",
                "article_id": f"review-{index + 1}",
                "article_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "headline": headline,
                "article_text": text,
                "sentences": copy.deepcopy(spans),
                "review_status": "UNREVIEWED",
                "reviewer": None,
                "label_source": None,
                "cohort": None,
                "split": "pilot",
                "focal_event_summary": None,
                "supporting_sentence_ids": [],
                "notes": None,
                "gold_entities": [
                    {
                        "text": "Delhi",
                        "label": "LOCATION",
                        "start_char": start,
                        "end_char": start + 5,
                    }
                ],
            }
        )
    records[0]["screening"] = {
        "text_quality": {"status": "SHORT_REVIEW", "word_count": len(text.split())}
    }
    records[0]["source_metadata"] = {"source_url": "https://example.test/protest"}
    return records


def jsonl(records):
    return "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"


def prediction_records():
    predictions = []
    for record in annotation_records():
        sentences = [
            dict(
                sentence,
                entities=[],
                ner_status="COMPLETE" if sentence["sentence_id"] <= 3 else "NOT_SELECTED",
                rank=sentence["sentence_id"],
                importance_score=1 / sentence["sentence_id"],
                position_score=1 / sentence["sentence_id"],
                headline_score=0,
                event_relevance=0.4,
            )
            for sentence in record["sentences"]
        ]
        start = record["article_text"].index("Delhi")
        sentences[0]["entities"] = [
            {
                "text": "Delhi",
                "label": label,
                "confidence": confidence,
                "start_char": start,
                "end_char": start + 5,
                "sentence_id": 1,
                "sentence_start_char": start,
                "sentence_end_char": start + 5,
            }
            for label, confidence in (("LOCATION", 0.9), ("ORGANIZATION", 0.7))
        ]
        paragraphs = []
        for paragraph_id in sorted({sentence["paragraph_id"] for sentence in sentences}):
            members = [s for s in sentences if s["paragraph_id"] == paragraph_id]
            begin, end = members[0]["start_char"], members[-1]["end_char"]
            paragraphs.append(
                {
                    "paragraph_id": paragraph_id,
                    "start_char": begin,
                    "end_char": end,
                    "text": record["article_text"][begin:end],
                }
            )
        predictions.append(
            {
                **record,
                "schema_version": "focal-evidence.v1",
                "paragraphs": paragraphs,
                "sentences": sentences,
                "candidate_sentences": sentences[:3],
                "candidate_sentence_ids_in_article_order": [1, 2, 3],
                "entity_schema": {"LOCATION": "places", "ORGANIZATION": "organizations"},
                "processing_status": "COMPLETE",
                "errors": [],
                "models": {"test": "deterministic fixture"},
            }
        )
    predictions[1]["processing_status"] = "ERROR"
    predictions[1]["errors"] = [{"stage": "ner", "message": "Fixture entity extraction failure"}]
    predictions[1]["sentences"][0]["ner_status"] = "ERROR"
    predictions[1]["sentences"][0]["entities"] = []
    return predictions


NODE_PARSE = """
const fs = require('node:fs');
const review = require(process.argv[1]);
(async () => {
  try {
    const records = review.parseAnnotations(fs.readFileSync(0, 'utf8'));
    await review.verifySnapshots(records);
    console.log(JSON.stringify({ articles: records.length }));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
})();
"""


def parse_in_node(records):
    return subprocess.run(
        ["node", "-e", NODE_PARSE, str(SCRIPT)],
        input=jsonl(records),
        text=True,
        capture_output=True,
        check=False,
    )


def test_review_parser_accepts_exact_python_unicode_offsets_and_preserves_evidence():
    result = parse_in_node(annotation_records())
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["articles"] == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_schema",
        "duplicate_articles",
        "offset",
        "changed_text",
        "unknown_status",
        "bad_support",
        "reviewed_without_name",
        "excluded_without_notes",
        "entity_offset",
    ],
)
def test_review_parser_rejects_invalid_annotations(mutation):
    records = annotation_records()
    record = records[0]
    if mutation == "wrong_schema":
        record["schema_version"] = "focal-evidence.v1"
    elif mutation == "duplicate_articles":
        records.append(copy.deepcopy(record))
    elif mutation == "offset":
        record["sentences"][0]["end_char"] += 1
    elif mutation == "changed_text":
        record["article_text"] += " Changed."
    elif mutation == "unknown_status":
        record["review_status"] = "ACCEPTED"
    elif mutation == "bad_support":
        record["supporting_sentence_ids"] = [99]
    elif mutation == "reviewed_without_name":
        record.update(
            {
                "review_status": "REVIEWED",
                "label_source": "human",
                "focal_event_summary": "A march",
                "supporting_sentence_ids": [1],
            }
        )
    elif mutation == "excluded_without_notes":
        record.update(
            {"review_status": "UNSUITABLE", "label_source": "human", "reviewer": "Fixture"}
        )
    else:
        record["gold_entities"][0]["end_char"] += 1
    result = parse_in_node(records)
    assert result.returncode == 2
    assert result.stderr.strip()


def test_draft_restore_and_export_cannot_replace_original_evidence():
    script = """
    const assert = require('node:assert/strict');
    const fs = require('node:fs');
    const review = require(process.argv[1]);
    const records = review.parseAnnotations(fs.readFileSync(0, 'utf8'));
    const snapshots = records.map(review.immutableSnapshot);
    const drafts = records.map(review.draftFields);
    drafts[0].review_status = 'REVIEWED';
    drafts[0].reviewer = 'Fixture reviewer';
    drafts[0].label_source = 'human';
    drafts[0].focal_event_summary = 'Police arrested protesters.';
    drafts[0].supporting_sentence_ids = [5];
    drafts[0].article_text = 'Injected replacement';
    drafts[0].sentences = [];
    drafts[0].gold_entities = [];
    const restored = review.applyDrafts(records, drafts);
    assert.equal(restored[0].review_status, 'REVIEWED');
    assert.equal(review.immutableSnapshot(restored[0]), snapshots[0]);
    const exported = review.parseAnnotations(review.serializeAnnotations(restored, snapshots));
    assert.deepEqual(exported[0].gold_entities, records[0].gold_entities);
    assert.deepEqual(exported[0].supporting_sentence_ids, [5]);
    assert.throws(() => review.applyDrafts(records, [drafts[0], drafts[0]]), /duplicate/);
    assert.throws(() => review.applyDrafts(records, [{article_id: 'other'}]), /different batch/);
    restored[0].article_text += ' Changed.';
    assert.throws(() => review.serializeAnnotations(restored, snapshots), /evidence changed/);
    console.log('Draft and evidence checks passed');
    """
    result = subprocess.run(
        ["node", "-e", script, str(SCRIPT)],
        input=jsonl(annotation_records()),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_manual_entity_helpers_preserve_unicode_evidence_and_review_boundaries():
    script = r"""
    const assert = require('node:assert/strict');
    const fs = require('node:fs');
    const review = require(process.argv[1]);
    (async () => {
      const records = review.parseAnnotations(fs.readFileSync(0, 'utf8'));
      const record = records[0];
      record.review_status = 'REVIEWED';
      record.reviewer = 'Event reviewer';
      record.label_source = 'ai_assisted';
      record.focal_event_summary = 'Police arrested protesters.';
      record.supporting_sentence_ids = [5];
      const snapshots = records.map(record => review.immutableSnapshot(record, true));
      const source = record.article_text;
      assert.deepEqual(review.spanFromUtf16('🪧 Delhi Delhi ', 3, 9), {
        text:'Delhi', start_char:2, end_char:7
      });
      assert.deepEqual(review.spanFromUtf16('🪧 Delhi Delhi ', 15, 9), {
        text:'Delhi', start_char:8, end_char:13
      });
      assert.throws(() => review.spanFromUtf16('🪧 Delhi', 1, 4), /Unicode/);
      assert.throws(() => review.spanFromUtf16(source, -1, 5), /within/);
      assert.throws(() => review.spanFromUtf16(source, 2, 3), /nonempty/);
      const start = source.indexOf('Monday');
      const span = review.spanFromUtf16(source, start, start + 6);
      review.addGoldEntity(record, span, 'DATE');
      assert.equal(record.review_status, 'REVIEWED');
      assert.equal(record.ner_annotation.review_status, 'UNREVIEWED');
      assert.equal(record.ner_annotation.whole_article_checked, false);
      assert.throws(() => review.addGoldEntity(record, span, 'DATE'), /Duplicate/);
      assert.throws(() => review.addGoldEntity(record, span, 'EVENT'), /annotation/);
      assert.throws(() => review.completeNerReview(record, {
        reviewer:'Entity reviewer', label_source:'human', whole_article_checked:false
      }), /whole-article/);
      review.completeNerReview(record, {
        reviewer:'Entity reviewer', label_source:'human', whole_article_checked:true
      }, '2026-10-11T10:00:00Z');
      assert.equal(record.ner_annotation.review_status, 'REVIEWED');
      assert.equal(record.reviewer, 'Event reviewer');
      assert.equal(record.label_source, 'ai_assisted');
      const drafts = records.map(record => review.draftFields(record, true));
      drafts[0].article_text = 'Injected';
      drafts[0].entity_schema = {EVENT:'Injected'};
      const restored = review.applyDrafts(records, drafts, true);
      assert.equal(review.immutableSnapshot(restored[0], true), snapshots[0]);
      assert.deepEqual(restored[0].ner_annotation, record.ner_annotation);
      const exported = review.parseAnnotations(
        review.serializeAnnotations(restored, snapshots, true)
      );
      assert.equal(exported[0].gold_entities.length, 2);
      review.removeGoldEntity(record, 1);
      assert.equal(record.ner_annotation.review_status, 'UNREVIEWED');
      assert.equal(record.ner_annotation.reviewed_at, null);
      assert.equal(record.review_status, 'REVIEWED');
      assert.throws(() => review.removeGoldEntity(record, 20), /existing/);
      const oldKey = await review.batchStorageKey(records);
      const newKey = await review.batchStorageKey(records, true);
      assert.match(oldKey, /^focal-review.v1:/);
      assert.match(newKey, /^focal-review.v2:/);
      assert.notEqual(newKey, oldKey);
      record.entity_schema = {LOCATION:'places', EVENT:'events'};
      assert.deepEqual(review.entityLabels(record), ['LOCATION', 'EVENT']);
      assert.notEqual(await review.batchStorageKey(records, true), newKey);
      assert.throws(
        () => review.serializeAnnotations(records, snapshots, true), /evidence changed/
      );
      console.log('Manual entities, Unicode and cache checks passed');
    })().catch(error => {console.error(error); process.exitCode = 1;});
    """
    result = subprocess.run(
        ["node", "-e", script, str(SCRIPT)],
        input=jsonl(annotation_records()),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_review_routes_serve_only_the_configured_annotation_file(tmp_path):
    api = load_api()
    path = tmp_path / "annotations.jsonl"
    content = jsonl(annotation_records())
    path.write_text(content)

    async def exercise():
        app = api.create_app(review_annotations_path=path)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            page = await client.get("/review")
            script = await client.get("/review.js")
            annotations = await client.get("/api/focal-review/annotations?path=/etc/passwd")
            assert page.status_code == script.status_code == annotations.status_code == 200
            assert 'id="sentence-list"' in page.text
            assert "text/javascript" in script.headers["content-type"]
            assert annotations.text == content
            assert annotations.headers["cache-control"] == "no-store"
            path.unlink()
            missing = await client.get("/api/focal-review/annotations")
            assert missing.status_code == 404
            original = await client.get("/")
            assert original.status_code == 200
            assert 'data-mode="cards"' in original.text

    asyncio.run(exercise())


def test_model_evidence_route_checks_snapshot_and_never_writes_files(tmp_path):
    api = load_api()
    annotation_path, result_path = tmp_path / "annotations.jsonl", tmp_path / "results.jsonl"
    annotations, predictions = annotation_records(), prediction_records()
    annotation_path.write_text(jsonl(annotations))
    result_path.write_text(jsonl(predictions))
    original = annotation_path.read_bytes(), result_path.read_bytes()

    async def exercise():
        app = api.create_app(
            review_annotations_path=annotation_path, review_results_path=result_path
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/focal-review/evidence/review-1?path=/etc/passwd", json=annotations[0]
            )
            assert response.status_code == 200, response.text
            envelope = response.json()
            assert envelope["result"] == predictions[0]
            assert envelope["input_sha256"] == hashlib.sha256(original[1]).hexdigest()
            assert envelope["filename"] == result_path.name
            assert response.headers["cache-control"] == "no-store"
            wrong_id = await client.post("/api/focal-review/evidence/review-2", json=annotations[0])
            assert wrong_id.status_code == 400
            absent = await client.post(
                "/api/focal-review/evidence/absent", json={**annotations[0], "article_id": "absent"}
            )
            assert absent.status_code == 404
            assert (annotation_path.read_bytes(), result_path.read_bytes()) == original
            result_path.unlink()
            missing = await client.post("/api/focal-review/evidence/review-1", json=annotations[0])
            assert missing.status_code == 404
        unconfigured = api.create_app(review_annotations_path=annotation_path)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=unconfigured), base_url="http://test"
        ) as client:
            missing = await client.post("/api/focal-review/evidence/review-1", json=annotations[0])
            assert missing.status_code == 404

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mutation",
    [
        "headline",
        "text",
        "sentence_ids",
        "metadata",
        "prediction_schema",
        "entity_offset",
        "confidence",
        "duplicate_records",
        "numeric_overflow",
    ],
)
def test_model_evidence_route_rejects_changed_or_inconsistent_evidence(tmp_path, mutation):
    api = load_api()
    path = tmp_path / "results.jsonl"
    annotation, predictions = annotation_records()[0], prediction_records()
    if mutation == "headline":
        annotation["headline"] = "Different headline"
    elif mutation == "text":
        annotation["article_text"] += " Changed text."
    elif mutation == "sentence_ids":
        annotation["sentences"][0]["paragraph_id"] = 99
    elif mutation == "metadata":
        del annotation["source_metadata"]
    elif mutation == "prediction_schema":
        predictions[0]["schema_version"] = "unknown"
    elif mutation == "entity_offset":
        predictions[0]["candidate_sentences"][0]["entities"][0]["sentence_start_char"] += 1
    elif mutation == "confidence":
        predictions[0]["candidate_sentences"][0]["entities"][0]["confidence"] = 2.0
    elif mutation == "duplicate_records":
        predictions.append(copy.deepcopy(predictions[0]))
    content = jsonl(predictions)
    if mutation == "numeric_overflow":
        content = content.replace('"confidence": 0.9', '"confidence": 1e999')
    path.write_text(content)
    original = path.read_bytes()

    async def exercise():
        app = api.create_app(review_results_path=path)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/focal-review/evidence/review-1", json=annotation)
            assert response.status_code == 422, response.text
            assert response.json()["detail"]

    asyncio.run(exercise())
    assert path.read_bytes() == original


def test_inspection_history_and_conflicting_labels_preserve_gold_and_review_decision():
    script = """
    const assert = require('node:assert/strict');
    const fs = require('node:fs');
    const review = require(process.argv[1]);
    const records = review.parseAnnotations(fs.readFileSync(0, 'utf8'));
    const record = records[0];
    const snapshots = records.map(review.immutableSnapshot);
    const evidence = {
      schema_version: 'focal-evidence-review.v1', filename: 'results.jsonl',
      input_sha256: 'a'.repeat(64),
      result: {article_id: record.article_id, article_text_sha256: record.article_text_sha256}
    };
    review.recordModelInspection(record, evidence, '2026-10-11T14:00:00.000Z');
    review.recordModelInspection(record, evidence, '2026-10-11T15:00:00.000Z');
    assert.equal(record.model_evidence_inspections.length, 1);
    assert.equal(record.model_evidence_inspections[0].viewed_at, '2026-10-11T14:00:00.000Z');
    assert.equal(record.review_status, 'UNREVIEWED');
    assert.equal(review.immutableSnapshot(record), snapshots[0]);
    const drafts = records.map(review.draftFields);
    const restored = review.applyDrafts(records, drafts);
    const exported = review.parseAnnotations(review.serializeAnnotations(restored, snapshots));
    assert.deepEqual(exported[0].model_evidence_inspections, record.model_evidence_inspections);
    assert.throws(() => review.validateModelInspections([{}, {}]), /invalid/);
    const inspection = record.model_evidence_inspections[0];
    assert.throws(() => review.validateModelInspections([inspection, inspection]), /invalid/);
    const badHash = {...evidence, input_sha256:'bad'};
    assert.throws(() => review.recordModelInspection(record, badHash), /invalid/);
    assert.throws(() => review.recordModelInspection(record, evidence, 'yesterday'), /invalid/);
    const otherArticle = {...evidence, result:{article_id:'other'}};
    assert.throws(() => review.recordModelInspection(record, otherArticle), /snapshot/);
    const conflicts = review.entityLabelConflicts([
      {label:'LOCATION', start_char:10, end_char:15},
      {label:'ORGANIZATION', start_char:10, end_char:15},
      {label:'LOCATION', start_char:30, end_char:35},
      {label:'LOCATION', start_char:40, end_char:45},
      {label:'LOCATION', start_char:40, end_char:45}
    ]);
    assert.deepEqual(Array.from(conflicts), ['10:15']);
    """
    result = subprocess.run(
        ["node", "-e", script, str(SCRIPT)],
        input=jsonl(annotation_records()),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_screening_labels_validate_and_source_metadata_remains_immutable():
    script = """
    const assert = require('node:assert/strict');
    const fs = require('node:fs');
    const review = require(process.argv[1]);
    (async () => {
      const records = review.parseAnnotations(fs.readFileSync(0, 'utf8'));
      const record = records[0];
      record.eligibility = {
        review_status: 'REVIEWED', reviewer: 'Screening reviewer',
        protest_relevance: 'PROTEST', body_quality: 'COMPLETE', scope: 'INDIA_2024',
        exclusion_reason: null, reviewed_at: '2026-10-11T13:00:00Z'
      };
      review.validateEligibility(record.eligibility);
      assert.equal(record.review_status, 'UNREVIEWED');
      assert.throws(
        () => review.validateEligibility({...record.eligibility, reviewer: null}), /reviewer/
      );
      assert.throws(
        () => review.validateEligibility({...record.eligibility, scope: null}), /Choose/
      );
      assert.throws(
        () => review.validateEligibility({...record.eligibility, protest_relevance: 'POLITICS'}),
        /Invalid/
      );
      record.source_metadata = {source_url: 'https://example.test/protest'};
      record.screening = {text_quality: {status: 'SHORT_REVIEW', word_count: 50}};
      const snapshots = records.map(review.immutableSnapshot);
      const key = await review.batchStorageKey(records);
      const draft = review.draftFields(record);
      assert.equal(draft.eligibility.reviewer, 'Screening reviewer');
      const exported = review.parseAnnotations(review.serializeAnnotations(records, snapshots));
      assert.deepEqual(exported[0].eligibility, record.eligibility);
      record.source_metadata.source_url = 'https://example.test/changed';
      assert.notEqual(await review.batchStorageKey(records), key);
      assert.throws(() => review.serializeAnnotations(records, snapshots), /evidence changed/);
      console.log(JSON.stringify(review.ELIGIBILITY_LABELS));
    })().catch(error => { console.error(error); process.exitCode = 1; });
    """
    result = subprocess.run(
        ["node", "-e", script, str(SCRIPT)],
        input=jsonl(annotation_records()),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    from focal_event_evaluation import ELIGIBILITY_LABELS

    assert {
        key: set(values) for key, values in json.loads(result.stdout).items()
    } == ELIGIBILITY_LABELS


BROWSER_SCRIPT = r"""
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const { chromium } = require('playwright');
const { expect } = require('@playwright/test');
const [root, baseUrl, inputPath, outputPath, screenshotPath, predictionsPath] =
  process.argv.slice(1);
(async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: chromium.executablePath()
  });
  try {
    const context = await browser.newContext({
      acceptDownloads: true, viewport: {width: 1440, height: 1000}
    });
    const page = await context.newPage();
    const errors = [];
    let evidenceRequests = 0;
    const predictionsText = fs.readFileSync(predictionsPath, 'utf8');
    const predictions = predictionsText.trim().split('\n').map(JSON.parse);
    const predictionsHash = crypto.createHash('sha256').update(predictionsText).digest('hex');
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/focal-review/annotations', route => route.fulfill({
      status: 200, contentType: 'application/x-ndjson',
      body: fs.readFileSync(inputPath, 'utf8')
    }));
    await page.route('**/api/focal-review/evidence/*', route => {
      evidenceRequests += 1;
      const annotation = route.request().postDataJSON();
      const result = predictions.find(record => record.article_id === annotation.article_id);
      return route.fulfill({status:200, contentType:'application/json', body:JSON.stringify({
        schema_version:'focal-evidence-review.v1', filename:'predictions.jsonl',
        input_sha256:predictionsHash, result
      })});
    });
    await page.goto(baseUrl + '/frontend/review.html');
    await expect(page.locator('#article-id')).toHaveText('Article ID review-1');
    await expect(page.locator('.sentence')).toHaveCount(5);
    await expect(page.locator('#sentence-list')).not.toContainText('importance_score');
    await expect(page.locator('#screening-summary')).toContainText('Short extract');
    await expect(page.locator('#model-inspector')).toBeHidden();
    assert.equal(evidenceRequests, 0);
    await page.locator('[data-sentence-id="5"]').click();
    await expect(page.locator('[data-sentence-id="5"]')).toHaveAttribute('aria-pressed', 'true');
    await page.locator('[data-sentence-id="5"]').click();
    await expect(page.locator('#selection-label')).toHaveText('No evidence selected');
    await page.locator('[data-sentence-id="5"]').click();
    await page.locator('#mark-reviewed').click();
    await expect(page.locator('#review-error')).toHaveText('Enter your reviewer name.');
    await page.locator('#reviewer').fill('Fixture reviewer');
    await page.locator('#event-summary').fill('Police arrested protesters on Monday.');
    await page.locator('#cohort').selectOption('multiple_events');
    await page.locator('#label-source').selectOption('ai_assisted');
    await page.locator('#protest-relevance').selectOption('PROTEST_LINKED');
    await page.locator('#body-quality').selectOption('COMPLETE');
    await page.locator('#scope').selectOption('INDIA_2024');
    await page.locator('#screening-reviewer').fill('Fixture screening reviewer');
    await page.locator('#save-screening').click();
    await expect(page.locator('#screening-progress')).toHaveText('1 of 3 screened');
    await expect(page.locator('#review-status')).toHaveText('To review');
    await expect(page.locator('#screening-summary')).toContainText('Article screening saved');
    await page.screenshot({path: screenshotPath, fullPage: true});
    await page.locator('#mark-reviewed').click();
    await expect(page.locator('#article-id')).toHaveText('Article ID review-2');
    await expect(page.locator('#model-inspector')).toBeHidden();
    await page.locator('.queue-item').first().click();
    await expect(page.locator('#model-inspector')).toBeVisible();
    assert.equal(evidenceRequests, 0);
    await page.locator('#model-inspector > summary').click();
    await expect(page.locator('.model-candidate')).toHaveCount(3);
    await expect(page.locator('#model-evidence-state')).toContainText(
      'None of your saved evidence'
    );
    await expect(page.locator('.model-entity[data-conflict="true"]')).toHaveCount(2);
    await expect(page.locator('.model-signals').first()).toContainText('Event cues: 0.400');
    await expect(page.locator('#model-evidence-source')).toContainText(predictionsHash);
    await page.locator('#model-inspector > summary').click();
    await page.locator('#model-inspector > summary').click();
    await expect(page.locator('.model-candidate')).toHaveCount(3);
    assert.equal(evidenceRequests, 1);
    await page.locator('.queue-item').nth(1).click();
    await expect(page.locator('#article-headline')).toContainText('<img');
    assert.equal(await page.locator('img').count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    await page.locator('#mark-unsuitable').click();
    await expect(page.locator('#review-error')).toHaveText(
      'Choose an exclusion reason or add it in notes.'
    );
    await page.locator('#exclusion-reason').selectOption('NO_FOCAL_EVENT');
    await page.locator('#mark-unsuitable').click();
    await expect(page.locator('#article-id')).toHaveText('Article ID review-3');
    await page.locator('.queue-item').nth(1).click();
    await page.locator('#model-inspector > summary').click();
    await expect(page.locator('#model-evidence-state')).toContainText(
      'Extraction recorded an error'
    );
    await expect(page.locator('.model-candidate').first()).toContainText(
      'Entity extraction failed for this sentence.'
    );
    await expect(page.locator('#review-status')).toHaveText('Excluded');
    await page.locator('.queue-item').nth(2).click();
    await expect(page.locator('#progress-label')).toHaveText('2 of 3 done');
    await page.locator('#queue-filter').selectOption('REVIEWED');
    assert.equal(await page.locator('.queue-item:visible').count(), 1);
    await page.locator('#queue-filter').selectOption('all');
    await page.locator('#search').fill('Historical');
    assert.equal(await page.locator('.queue-item:visible').count(), 1);
    await page.locator('#search').fill('');
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export-file').click();
    await (await downloadPromise).saveAs(outputPath);
    const exported = fs.readFileSync(outputPath, 'utf8').trim().split('\n').map(JSON.parse);
    assert.equal(exported[0].review_status, 'REVIEWED');
    assert.deepEqual(exported[0].supporting_sentence_ids, [5]);
    assert.equal(exported[0].label_source, 'ai_assisted');
    assert.equal(exported[0].eligibility.review_status, 'REVIEWED');
    assert.equal(exported[0].eligibility.reviewer, 'Fixture screening reviewer');
    assert.equal(exported[0].eligibility.protest_relevance, 'PROTEST_LINKED');
    assert.equal(exported[0].model_evidence_inspections.length, 1);
    assert.equal(exported[0].model_evidence_inspections[0].input_sha256, predictionsHash);
    assert.equal(exported[1].review_status, 'UNSUITABLE');
    assert.equal(exported[1].eligibility.exclusion_reason, 'NO_FOCAL_EVENT');
    assert.equal(exported[1].model_evidence_inspections.length, 1);
    assert.equal(exported[2].review_status, 'UNREVIEWED');
    await page.reload();
    await expect(page.locator('#progress-label')).toHaveText('2 of 3 done');
    await expect(page.locator('#message')).toContainText('Restored');
    await page.locator('.queue-item').first().click();
    await expect(page.locator('#review-status')).toHaveText('Reviewed');
    await expect(page.locator('#model-inspector')).toBeVisible();
    await page.locator('#eligibility-panel summary').click();
    await page.locator('#body-quality').selectOption('LIMITED');
    await expect(page.locator('#screening-progress')).toHaveText('0 of 3 screened');
    await page.locator('#event-summary').fill('Updated event description.');
    await expect(page.locator('#review-status')).toHaveText('To review');
    await expect(page.locator('#model-inspector')).toBeHidden();
    await expect(page.locator('.model-candidate')).toHaveCount(0);
    await page.locator('#load-pilot').click();
    await expect(page.locator('#event-summary')).toHaveValue('Updated event description.');
    await page.locator('#import-file').setInputFiles(inputPath);
    await expect(page.locator('#progress-label')).toHaveText('0 of 3 done');
    await expect(page.locator('#event-summary')).toHaveValue('');
    await expect(page.locator('#model-inspector')).toBeHidden();
    await page.evaluate(() => {
      Storage.prototype.setItem = () => { throw new Error('Quota exceeded'); };
    });
    await page.locator('[data-sentence-id="1"]').click();
    await expect(page.locator('#save-status')).toContainText('Browser storage is unavailable');
    await page.setViewportSize({width: 390, height: 844});
    const fits = await page.evaluate(() => {
      return document.documentElement.scrollWidth <= window.innerWidth;
    });
    assert.equal(fits, true);
    assert.deepEqual(errors, []);
    console.log('Browser review, export, recovery, import, and mobile checks passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def test_browser_review_export_roundtrip_and_evaluation(tmp_path):
    if not (ROOT / "node_modules" / "playwright").is_dir():
        pytest.skip("Install the workspace's Playwright dependency before browser tests")
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    input_path, output_path = tmp_path / "input.jsonl", tmp_path / "exported.jsonl"
    input_path.write_text(jsonl(annotation_records()))
    predictions_path = tmp_path / "predictions.jsonl"
    predictions_path.write_text(jsonl(prediction_records()))
    screenshot_path = tmp_path / "review.png"
    try:
        result = subprocess.run(
            [
                "node",
                "-e",
                BROWSER_SCRIPT,
                str(ROOT),
                f"http://127.0.0.1:{server.server_port}",
                str(input_path),
                str(output_path),
                str(screenshot_path),
                str(predictions_path),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
            env={**os.environ},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        exported = [json.loads(line) for line in output_path.read_text().splitlines()]
        originals = annotation_records()
        for original, record in zip(originals, exported, strict=True):
            for field in (
                "article_id",
                "article_text_sha256",
                "article_text",
                "headline",
                "sentences",
                "gold_entities",
            ):
                assert record[field] == original[field]
        evaluation = __import__("focal_event_evaluation")
        metrics = evaluation.evaluate(prediction_records(), exported)
        assert metrics["reviewed_articles"] == 1
        assert metrics["unsuitable_articles"] == 1
        assert metrics["unreviewed_articles"] == 1
        assert metrics["top3_recall"] == 0
        assert metrics["evidence_consistency"]["inconsistent_articles"] == 0
        assert metrics["protest_benchmark"]["reviewed_articles"] == 1
        assert metrics["protest_benchmark"]["top3_recall"] == 0
        assert metrics["article_screening"]["reviewed_articles"] == 1
        assert metrics["article_screening"]["labels"]["exclusion_reason"] == {"NO_FOCAL_EVENT": 1}
        assert metrics["annotation_provenance"] == {
            "reviewed_label_sources": {"ai_assisted": 1},
            "reviewed_with_model_evidence_inspections": 1,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


ENTITY_BROWSER_SCRIPT = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('playwright');
const {expect} = require('@playwright/test');
const [root, baseUrl, inputPath, outputPath, screenshotPath] = process.argv.slice(1);
const review = require(root + '/frontend/review.js');
(async () => {
  const source = fs.readFileSync(inputPath, 'utf8');
  const records = review.parseAnnotations(source);
  const oldKey = await review.batchStorageKey(records);
  const drafts = records.map(review.draftFields);
  Object.assign(drafts[0], {
    review_status:'REVIEWED', reviewer:'Event reviewer', label_source:'ai_assisted',
    focal_event_summary:'Police arrested protesters.', supporting_sentence_ids:[5],
    article_text:'Injected source', gold_entities:[],
    ner_annotation:{review_status:'REVIEWED', reviewer:'Injected'}
  });
  const legacy = JSON.stringify(drafts);
  const browser = await chromium.launch({
    headless:true, executablePath:chromium.executablePath()
  });
  try {
    const context = await browser.newContext({acceptDownloads:true,
      viewport:{width:1440, height:1000}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(({key, legacy}) => {
      if (!localStorage.getItem(key)) localStorage.setItem(key, legacy);
    }, {key:oldKey, legacy});
    await page.route('**/api/focal-review/annotations', route => route.fulfill({
      status:200, contentType:'application/x-ndjson', body:source
    }));
    await page.goto(baseUrl + '/frontend/review.html');
    await expect(page.locator('#article-id')).toHaveText('Article ID review-2');
    await expect(page.locator('#entity-editor')).toBeHidden();
    await expect(page.locator('#progress-label')).toHaveText('1 of 3 done');
    await page.locator('.queue-item').first().click();
    await expect(page.locator('#entity-editor')).toBeVisible();
    await page.locator('#entity-editor > summary').click();
    await expect(page.locator('.gold-entity')).toHaveCount(1);
    await expect(page.locator('#ner-state')).toContainText('legacy entity');
    assert.equal(await page.locator('#ner-reviewer').inputValue(), '');
    assert.equal(await page.locator('#ner-label-source').inputValue(), 'ai_assisted');
    await page.locator('#show-entity-source').click();
    await expect(page.locator('#original-text')).toHaveText(records[0].article_text);
    await page.evaluate(() => {
      const node = document.getElementById('original-text').firstChild;
      const start = node.textContent.indexOf('Monday');
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, start + 6);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    });
    await expect(page.locator('#entity-selection')).toContainText('Selected: Monday');
    await page.locator('#entity-label').selectOption('DATE');
    await page.locator('#add-entity').click();
    await expect(page.locator('.gold-entity')).toHaveCount(2);
    await expect(page.locator('#review-status')).toHaveText('Reviewed');
    await expect(page.locator('#ner-state')).toContainText('in draft');
    await page.locator('#ner-reviewer').fill('Entity reviewer');
    await page.locator('#ner-label-source').selectOption('human');
    await page.locator('#save-entities').click();
    await expect(page.locator('#ner-error')).toContainText('whole-article check');
    let download = page.waitForEvent('download');
    await page.locator('#export-file').click();
    await (await download).saveAs(outputPath + '.draft');
    await page.locator('#ner-whole-article').check();
    await page.locator('#save-entities').click();
    await expect(page.locator('#ner-state')).toContainText('confirmed by Entity reviewer');
    await expect(page.locator('#ner-error')).toBeHidden();
    await page.reload();
    await expect(page.locator('#progress-label')).toHaveText('1 of 3 done');
    await page.locator('.queue-item').first().click();
    await page.locator('#entity-editor > summary').click();
    await expect(page.locator('.gold-entity')).toHaveCount(2);
    await expect(page.locator('#ner-whole-article')).toBeChecked();
    await expect(page.locator('#ner-reviewer')).toHaveValue('Entity reviewer');
    assert.equal(await page.evaluate(key => localStorage.getItem(key), oldKey), legacy);
    const newKey = await review.batchStorageKey(records, true);
    const cache = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), newKey);
    assert.equal(cache.schema_version, 'focal-review-drafts.v2');
    assert.equal(cache.drafts[0].ner_annotation.review_status, 'REVIEWED');
    await page.locator('.gold-entity button').last().click();
    await expect(page.locator('#ner-state')).toContainText('in draft');
    await expect(page.locator('#ner-whole-article')).not.toBeChecked();
    await expect(page.locator('#review-status')).toHaveText('Reviewed');
    download = page.waitForEvent('download');
    await page.locator('#export-file').click();
    await (await download).saveAs(outputPath + '.removed');
    await page.locator('#show-entity-source').click();
    await page.evaluate(() => {
      const node = document.getElementById('original-text').firstChild;
      const start = node.textContent.indexOf('Monday');
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, start + 6);
      const selection = window.getSelection();
      selection.removeAllRanges(); selection.addRange(range);
    });
    await expect(page.locator('#entity-selection')).toContainText('Selected: Monday');
    await page.locator('#entity-label').selectOption('DATE');
    await page.locator('#add-entity').click();
    await page.locator('#ner-whole-article').check();
    await page.locator('#save-entities').click();
    download = page.waitForEvent('download');
    await page.locator('#export-file').click();
    await (await download).saveAs(outputPath);
    const exported = review.parseAnnotations(fs.readFileSync(outputPath, 'utf8'));
    const first = exported[0];
    assert.equal(first.ner_annotation.review_status, 'REVIEWED');
    assert.equal(first.gold_entities[1].start_char, Array.from(
      records[0].article_text.split('Monday')[0]).length);
    assert.equal(first.gold_entities[1].label, 'DATE');
    assert.equal(first.reviewer, 'Event reviewer');
    assert.equal(first.label_source, 'ai_assisted');
    assert.equal(first.article_text, records[0].article_text);
    await page.locator('#import-file').setInputFiles(outputPath);
    await page.locator('.queue-item').first().click();
    await page.locator('#entity-editor > summary').click();
    await expect(page.locator('.gold-entity')).toHaveCount(2);
    await expect(page.locator('#ner-whole-article')).toBeChecked();
    await page.locator('#entity-editor').evaluate(el => el.scrollIntoView({block:'start'}));
    await page.screenshot({path:screenshotPath, fullPage:true});
    await page.setViewportSize({width:390, height:844});
    assert.equal(await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({path:screenshotPath + '.mobile.png', fullPage:true});
    assert.deepEqual(errors, []);
    console.log('Manual entity review, legacy cache, export and mobile checks passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


def test_browser_manual_entities_legacy_recovery_and_ner_evaluation(tmp_path):
    if not (ROOT / "node_modules" / "playwright").is_dir():
        pytest.skip("Install the workspace's Playwright dependency before browser tests")
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    input_path, output_path = tmp_path / "input.jsonl", tmp_path / "entities.jsonl"
    input_path.write_text(jsonl(annotation_records()))
    original_bytes = input_path.read_bytes()
    try:
        result = subprocess.run(
            [
                "node",
                "-e",
                ENTITY_BROWSER_SCRIPT,
                str(ROOT),
                f"http://127.0.0.1:{server.server_port}",
                str(input_path),
                str(output_path),
                str(tmp_path / "entities.png"),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
            env={**os.environ},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        evaluation = __import__("focal_event_evaluation")
        predictions = prediction_records()
        for prediction in predictions:
            prediction["entity_schema"]["DATE"] = "calendar references"
        for suffix in (".draft", ".removed"):
            draft = evaluation.read_jsonl(Path(str(output_path) + suffix))
            metrics = evaluation.evaluate(predictions, draft)
            assert metrics["reviewed_articles"] == 1
            assert metrics["ner"]["annotated_articles"] == 0
            assert metrics["ner"]["draft_articles"] == 1
            assert metrics["ner"]["precision"] is None
        exported = evaluation.read_jsonl(output_path)
        for original, record in zip(annotation_records(), exported, strict=True):
            for field in (
                "article_id", "article_text_sha256", "article_text", "headline", "sentences"
            ):
                assert record[field] == original[field]
        metrics = evaluation.evaluate(predictions, exported)
        assert metrics["ner"]["annotated_articles"] == 1
        assert metrics["ner"]["legacy_annotated_articles"] == 0
        assert metrics["ner"]["label_sources"] == {"human": 1}
        assert metrics["ner"]["precision"] == 0.5
        assert metrics["ner"]["recall_full_article"] == 0.5
        assert metrics["ner"]["recall_within_candidates"] == 1
        assert metrics["top3_recall"] == 0
        assert input_path.read_bytes() == original_bytes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
