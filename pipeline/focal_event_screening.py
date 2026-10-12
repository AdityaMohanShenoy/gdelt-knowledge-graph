import copy
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
from article_extractor import EXTRACTOR_VERSION, extract_article
from focal_events import text_hash
from url_utils import normalize_url

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS_PATH = ROOT / "data" / "working" / "india-2024" / "target_events.parquet"
SCHEMA_VERSION = "focal-event-screening.v1"
PROTEST_CUES = re.compile(
    r"\b(?:protests?|protested|protesting|protesters?|demonstrations?|demonstrators?|"
    r"strikes?|striking|hunger strikes?|boycotts?|boycotting|dharnas?|bandhs?|"
    r"sit[ -]ins?|agitations?|picketing)\b",
    re.IGNORECASE,
)


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def candidate_observations(events_path: Path, root_codes: list[str]) -> dict[str, list[dict]]:
    if not root_codes or any(not re.fullmatch(r"\d{2}", code) for code in root_codes):
        raise ValueError("Candidate event roots must be two-digit CAMEO codes")
    connection = duckdb.connect()
    try:
        result = connection.execute(
            """
            SELECT DISTINCT GlobalEventID, day, EventCode, EventRootCode,
                            ActionGeo_CountryCode, SOURCEURL
            FROM read_parquet(?)
            WHERE EventRootCode = ANY(?) AND ActionGeo_CountryCode = 'IN'
              AND day BETWEEN 20240101 AND 20241231
              AND SOURCEURL IS NOT NULL AND SOURCEURL <> ''
            ORDER BY GlobalEventID, day, SOURCEURL, EventRootCode, EventCode
            """,
            [str(events_path), sorted(set(root_codes))],
        )
        names = [item[0] for item in result.description]
        rows = [dict(zip(names, row, strict=True)) for row in result.fetchall()]
    finally:
        connection.close()
    observations: dict[str, list[dict]] = {}
    for row in rows:
        key = normalize_url(row["SOURCEURL"])
        if key:
            observations.setdefault(key, []).append(row)
    return observations


def cue_spans(text: str) -> list[dict]:
    return [
        {"text": match.group(), "start_char": match.start(), "end_char": match.end()}
        for match in PROTEST_CUES.finditer(text)
    ]


def screen_article(article: dict, observations: list[dict], short_word_threshold: int) -> dict:
    if short_word_threshold < 1:
        raise ValueError("Short-text review threshold must be positive")
    stored = copy.deepcopy(article)
    stored["cleaned_text"] = stored.get("cleaned_text") or ""
    snapshot = copy.deepcopy(stored)
    raw_path = stored.get("raw_html_path")
    reprocessing: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "extractor_version": EXTRACTOR_VERSION,
        "raw_html_sha256": None,
        "error": None,
    }
    if raw_path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        try:
            with gzip.open(path, "rb") as source:
                body = source.read()
            reprocessing["raw_html_sha256"] = hashlib.sha256(body).hexdigest()
            result = extract_article(body, url=stored.get("final_url") or stored.get("source_url"))
            snapshot.update(
                {
                    "title": result.title,
                    "cleaned_text": result.text,
                    "status": result.status,
                    "extractor_version": EXTRACTOR_VERSION,
                    "extraction_reason": result.reason,
                }
            )
            reprocessing["status"] = "COMPLETE"
        except (OSError, EOFError, ValueError) as error:
            reprocessing["status"] = "ERROR"
            reprocessing["error"] = f"{type(error).__name__}: {error}"
    text = snapshot["cleaned_text"]
    words = len(text.split())
    flags = []
    if snapshot["status"] != "extracted" or not text.strip():
        quality = "UNSUITABLE"
        flags.append(snapshot.get("extraction_reason") or snapshot["status"])
    elif reprocessing["status"] != "COMPLETE":
        quality = "UNVERIFIED"
        flags.append("current-extractor-not-verified")
    else:
        quality = "READABLE"
    if words < short_word_threshold:
        flags.append("short-text-review")
        if quality == "READABLE":
            quality = "SHORT_REVIEW"
    body_cues = cue_spans(text)
    headline_cues = cue_spans(snapshot.get("title") or "")
    if not body_cues:
        flags.append("no-protest-cue-in-body")
    if snapshot.get("extraction_reason") in {"press-release", "promotional-content"}:
        flags.append(snapshot["extraction_reason"])
    return {
        "schema_version": SCHEMA_VERSION,
        "article_id": str(stored["document_id"]),
        "article": snapshot,
        "article_text_sha256": text_hash(text),
        "stored_article": stored,
        "stored_article_text_sha256": text_hash(stored["cleaned_text"]),
        "gdelt_observations": copy.deepcopy(observations),
        "reprocessing": reprocessing,
        "text_quality": {
            "status": quality,
            "flags": flags,
            "word_count": words,
            "character_count": len(text),
            "short_word_threshold": short_word_threshold,
        },
        "protest_cues": {"body": body_cues, "headline": headline_cues},
        "relevance_status": "PENDING_REVIEW",
    }


def validate_screening(record: dict) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported screening schema")
    article = record["article"]
    stored = record["stored_article"]
    if (
        record["article_id"] != str(article["document_id"])
        or record["article_id"] != str(stored["document_id"])
        or record["article_text_sha256"] != text_hash(article["cleaned_text"])
        or record["stored_article_text_sha256"] != text_hash(stored["cleaned_text"])
    ):
        raise ValueError("Screened article ID or text snapshot changed")
    quality = record["text_quality"]
    if quality["status"] not in {"READABLE", "SHORT_REVIEW", "UNVERIFIED", "UNSUITABLE"}:
        raise ValueError("Unsupported text quality status")
    if (
        quality["word_count"] != len(article["cleaned_text"].split())
        or quality["character_count"] != len(article["cleaned_text"])
        or quality["short_word_threshold"] < 1
    ):
        raise ValueError("Screened text quality counts changed")
    if article["status"] != "extracted" or not article["cleaned_text"].strip():
        expected_quality = "UNSUITABLE"
    elif record["reprocessing"]["status"] != "COMPLETE":
        expected_quality = "UNVERIFIED"
    elif quality["word_count"] < quality["short_word_threshold"]:
        expected_quality = "SHORT_REVIEW"
    else:
        expected_quality = "READABLE"
    if quality["status"] != expected_quality:
        raise ValueError("Screened text quality status contradicts extraction evidence")
    if record["relevance_status"] != "PENDING_REVIEW":
        raise ValueError("Automated screening cannot verify protest relevance")
    key = normalize_url(article["url_key"])
    if not record["gdelt_observations"] or any(
        normalize_url(row["SOURCEURL"]) != key
        or row["ActionGeo_CountryCode"] != "IN"
        or not 20240101 <= int(row["day"]) <= 20241231
        or row["EventRootCode"] not in {"14", "18", "19", "20"}
        for row in record["gdelt_observations"]
    ):
        raise ValueError("Screening observations do not support the candidate URL or scope")
    for field, text in (
        ("body", article["cleaned_text"]),
        ("headline", article.get("title") or ""),
    ):
        if record["protest_cues"][field] != cue_spans(text):
            raise ValueError("Screening cues do not match the original text")


def load_screened_articles(path: Path) -> tuple[list[dict], dict]:
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not records or len({r["article_id"] for r in records}) != len(records):
        raise ValueError("Screening input is empty or contains duplicate article IDs")
    articles, skipped = [], []
    for record in records:
        validate_screening(record)
        if record["text_quality"]["status"] == "UNSUITABLE":
            skipped.append(
                {"article_id": record["article_id"], "flags": record["text_quality"]["flags"]}
            )
            continue
        article = copy.deepcopy(record["article"])
        article["screening"] = {
            key: record[key]
            for key in ("text_quality", "protest_cues", "relevance_status", "reprocessing")
        }
        article["screening"]["stored_article_text_sha256"] = record["stored_article_text_sha256"]
        article["gdelt_observations"] = record["gdelt_observations"]
        articles.append(article)
    metadata = {
        "path": str(path.resolve()),
        "sha256": file_hash(path),
        "screened_articles": len(records),
        "quality_counts": dict(Counter(r["text_quality"]["status"] for r in records)),
        "skipped_articles": skipped,
    }
    manifest_path = path.with_suffix(".manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("output_sha256") != metadata["sha256"] or manifest.get("article_ids") != [
            record["article_id"] for record in records
        ]:
            raise ValueError("Screening batch differs from its selection manifest")
        metadata["selection_manifest"] = {
            "path": str(manifest_path.resolve()),
            "sha256": file_hash(manifest_path),
            "sample_seed": manifest["sample_seed"],
            "events_sha256": manifest["events_sha256"],
            "root_codes": manifest["root_codes"],
        }
    return articles, metadata
