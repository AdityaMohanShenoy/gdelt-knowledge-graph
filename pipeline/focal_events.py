import hashlib
import importlib.metadata
import math
import re
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

PIPELINE_VERSION = "focal-evidence.v1"
ENTITY_SCHEMA = {
    "PERSON": "Named individual people",
    "ORGANIZATION": "Named organizations, unions, political parties and government bodies",
    "LOCATION": "Named countries, states, cities, villages and other geographical places",
    "DATE": "Calendar dates and relative date expressions explicitly present in the text",
}
ACTION_LEMMAS = frozenset(
    "announce arrest attack ban block clash close approve decide demonstrate deploy detain "
    "demand dismiss elect evacuate injure kill launch march meet occupy order pass protest "
    "rally reject release resign resume revoke strike suspend withdraw implement sign".split()
)
REPORTING_LEMMAS = frozenset("say tell believe think argue claim suggest hope expect".split())


class RankingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    headline_weight: float = Field(default=0.6, ge=0)
    position_weight: float = Field(default=0.2, ge=0)
    event_weight: float = Field(default=0.2, ge=0)
    position_decay: float = Field(default=0.2, gt=0)
    ner_threshold: float = Field(default=0.5, ge=0, le=1)
    batch_size: int = Field(default=8, gt=0)
    include_event_entities: bool = False
    # Off by default so earlier runs stay reproducible from their saved config.
    drop_headline_echoes: bool = False
    headline_echo_overlap: float = Field(default=0.8, gt=0, le=1)

    @model_validator(mode="after")
    def validate_weights(self) -> "RankingConfig":
        if self.headline_weight + self.position_weight + self.event_weight == 0:
            raise ValueError("At least one ranking weight must be positive")
        if self.position_weight + self.event_weight == 0:
            raise ValueError("A positive position or event weight is needed for missing headlines")
        return self


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def event_features(sentence: Any) -> tuple[float, dict[str, Any]]:
    predicates = [
        token
        for token in sentence
        if token.pos_ == "VERB" and token.dep_ in {"ROOT", "conj", "ccomp", "xcomp", "advcl"}
    ]
    actions = sorted({token.lemma_.lower() for token in sentence} & ACTION_LEMMAS)
    subject = any(token.dep_ in {"nsubj", "nsubjpass", "csubj"} for token in sentence)
    finite = any("Fin" in token.morph.get("VerbForm") for token in sentence)
    reporting = sentence.root.lemma_.lower() in REPORTING_LEMMAS
    modal = any(token.tag_ == "MD" for token in sentence)
    negated = any(token.dep_ == "neg" for token in sentence)
    score = (
        0.35 * bool(predicates)
        + 0.2 * subject
        + 0.15 * finite
        + 0.3 * bool(actions)
        - 0.2 * reporting
        - 0.15 * modal
    )
    return max(0.0, min(1.0, score)), {
        "predicate_lemmas": [token.lemma_ for token in predicates],
        "action_lemmas": actions,
        "has_subject": subject,
        "finite_predicate": finite,
        "reporting_or_opinion_root": reporting,
        "modal": modal,
        "negated": negated,
    }


def segment_articles(articles: list[dict[str, Any]], nlp: Any, batch_size: int) -> list[dict]:
    records = []
    paragraphs = []
    for article in articles:
        text = article.get("cleaned_text") or ""
        record: dict[str, Any] = {
            "schema_version": PIPELINE_VERSION,
            "article_id": str(article["document_id"]),
            "headline": article.get("title"),
            "article_text": text,
            "article_text_sha256": text_hash(text),
            "publication_timestamp": article.get("publication_timestamp"),
            "source_metadata": {
                key: article.get(key)
                for key in (
                    "url_key",
                    "source_url",
                    "final_url",
                    "status",
                    "fetched_at",
                    "extractor_version",
                    "extraction_reason",
                    "content_hash",
                    "raw_html_path",
                )
            },
            "paragraphs": [],
            "sentences": [],
            "candidate_sentences": [],
            "candidate_sentence_ids_in_article_order": [],
            "processing_status": "EMPTY_TEXT" if not text.strip() else "PROCESSING",
            "focal_event_status": "PENDING_REVIEW",
            "errors": [],
        }
        if "screening" in article:
            record["screening"] = article["screening"]
            record["source_metadata"]["gdelt_observations"] = article["gdelt_observations"]
        records.append(record)
        for match in re.finditer(r"[^\r\n]+", text):
            raw = match.group()
            if not raw.strip():
                continue
            start = match.start() + len(raw) - len(raw.lstrip())
            end = match.end() - len(raw) + len(raw.rstrip())
            paragraph = {
                "paragraph_id": len(record["paragraphs"]) + 1,
                "text": text[start:end],
                "start_char": start,
                "end_char": end,
            }
            record["paragraphs"].append(paragraph)
            paragraphs.append((record, paragraph))
    docs = nlp.pipe((p["text"] for _, p in paragraphs), batch_size=batch_size)
    for (record, paragraph), doc in zip(paragraphs, docs, strict=True):
        for span in doc.sents:
            raw = span.text
            if not raw.strip():
                continue
            start = paragraph["start_char"] + span.start_char + len(raw) - len(raw.lstrip())
            end = paragraph["start_char"] + span.end_char - len(raw) + len(raw.rstrip())
            relevance, features = event_features(span)
            record["sentences"].append(
                {
                    "sentence_id": len(record["sentences"]) + 1,
                    "paragraph_id": paragraph["paragraph_id"],
                    "text": record["article_text"][start:end],
                    "start_char": start,
                    "end_char": end,
                    "event_relevance": relevance,
                    "event_cues": features,
                    "entities": [],
                    "ner_status": "NOT_SELECTED",
                }
            )
    return records


def content_words(text: str | None) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(word) > 2}


def is_headline_echo(text: str, headline: str | None, overlap: float) -> bool:
    """True when at least `overlap` of a sentence's content words are headline words.

    Lexical rather than embedding similarity on purpose: on dev, a cosine cut-off
    also caught genuine lead sentences that paraphrase the headline."""
    words = content_words(text)
    return len(words) >= 3 and len(words & content_words(headline)) / len(words) >= overlap


def rank_sentences(record: dict, similarities: list[float], config: RankingConfig) -> None:
    has_headline = bool((record["headline"] or "").strip())
    denominator = config.position_weight + config.event_weight
    if has_headline:
        denominator += config.headline_weight
    for index, (sentence, similarity) in enumerate(
        zip(record["sentences"], similarities, strict=True)
    ):
        if not math.isfinite(similarity):
            raise ValueError("Nonfinite headline similarity")
        sentence["headline_similarity"] = similarity if has_headline else None
        sentence["headline_score"] = (
            (max(-1.0, min(1.0, similarity)) + 1) / 2 if has_headline else 0
        )
        sentence["position_score"] = 1 / (1 + config.position_decay * index)
        sentence["importance_score"] = (
            config.headline_weight * sentence["headline_score"]
            + config.position_weight * sentence["position_score"]
            + config.event_weight * sentence["event_relevance"]
        ) / denominator
        sentence["headline_echo"] = config.drop_headline_echoes and is_headline_echo(
            sentence["text"], record["headline"], config.headline_echo_overlap
        )
    # A body sentence that restates the headline adds no evidence beyond it, so
    # echoes rank after every other sentence rather than leading the evidence.
    ranked = sorted(
        record["sentences"],
        key=lambda s: (s["headline_echo"], -s["importance_score"], s["sentence_id"]),
    )
    for rank, sentence in enumerate(ranked, 1):
        sentence["rank"] = rank
    record["candidate_sentences"] = ranked[:3]
    record["candidate_sentence_ids_in_article_order"] = sorted(s["sentence_id"] for s in ranked[:3])


def normalize_entities(result: dict, sentence: dict, article_text: str, labels: dict) -> list[dict]:
    if "entities" not in result or not isinstance(result["entities"], dict):
        raise ValueError("GLiNER2 did not return an entity map")
    entities = []
    seen = set()
    for label, spans in result["entities"].items():
        if label not in labels or not isinstance(spans, list):
            raise ValueError("Unexpected GLiNER2 label or span format")
        for span in spans:
            start, end = span["start"], span["end"]
            if type(start) is not int or type(end) is not int:
                raise ValueError("Entity offsets must be integers")
            if not 0 <= start < end <= len(sentence["text"]):
                raise ValueError("Entity offsets lie outside their sentence")
            if sentence["text"][start:end] != span["text"]:
                raise ValueError("Entity text does not match its sentence offsets")
            article_start = sentence["start_char"] + start
            article_end = sentence["start_char"] + end
            if article_text[article_start:article_end] != span["text"]:
                raise ValueError("Entity text does not match its article offsets")
            confidence = span.get("confidence")
            if confidence is not None and (
                not math.isfinite(confidence) or not 0 <= confidence <= 1
            ):
                raise ValueError("Invalid entity confidence")
            key = (label, article_start, article_end)
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                {
                    "text": span["text"],
                    "label": label,
                    "confidence": confidence,
                    "sentence_id": sentence["sentence_id"],
                    "start_char": article_start,
                    "end_char": article_end,
                    "sentence_start_char": start,
                    "sentence_end_char": end,
                }
            )
    return sorted(
        entities, key=lambda entity: (entity["start_char"], entity["end_char"], entity["label"])
    )


class FocalEventPipeline:
    def __init__(self, nlp: Any, embedder: Any, ner: Any, config: RankingConfig, models: dict):
        if "parser" not in nlp.pipe_names:
            raise ValueError("The spaCy model must provide dependency parsing")
        self.nlp = nlp
        self.embedder = embedder
        self.ner = ner
        self.config = config
        self.models = models
        self.labels = dict(ENTITY_SCHEMA)
        if config.include_event_entities:
            self.labels["EVENT"] = "Explicitly named events, demonstrations or marches"

    def process(self, articles: list[dict[str, Any]]) -> list[dict]:
        records = segment_articles(articles, self.nlp, self.config.batch_size)
        for record in records:
            record["models"] = self.models
            record["ranking_config"] = self.config.model_dump()
            record["entity_schema"] = self.labels
            record["processed_at"] = datetime.now(UTC).isoformat()
        texts: list[str] = []
        locations = []
        for record in records:
            if not record["sentences"]:
                continue
            headline_index = None
            if (record["headline"] or "").strip():
                headline_index = len(texts)
                texts.append(record["headline"])
            start = len(texts)
            texts.extend(sentence["text"] for sentence in record["sentences"])
            locations.append((record, headline_index, start))
        if not texts:
            return records
        try:
            embeddings = self.embedder.encode(
                texts,
                batch_size=self.config.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            if len(embeddings) != len(texts) or not np.isfinite(embeddings).all():
                raise ValueError("Invalid sentence embeddings")
            for record, headline_index, start in locations:
                sentences = record["sentences"]
                similarities = [0.0] * len(sentences)
                if headline_index is not None:
                    similarities = (
                        embeddings[start : start + len(sentences)] @ embeddings[headline_index]
                    ).tolist()
                rank_sentences(record, similarities, self.config)
                for sentence in sentences:
                    token_count = len(self.embedder.tokenizer.encode(sentence["text"]))
                    sentence["embedding_token_count"] = token_count
                    sentence["embedding_truncated"] = token_count > self.embedder.max_seq_length
                record["headline_embedding_truncated"] = (
                    headline_index is not None
                    and len(self.embedder.tokenizer.encode(record["headline"]))
                    > self.embedder.max_seq_length
                )
        except Exception as error:
            for record, _, _ in locations:
                record["processing_status"] = "ERROR"
                record["errors"].append({"stage": "ranking", "message": str(error)})
            return records
        selected = [
            (record, sentence)
            for record, _, _ in locations
            for sentence in record["candidate_sentences"]
        ]
        for offset in range(0, len(selected), self.config.batch_size):
            batch = selected[offset : offset + self.config.batch_size]
            try:
                results = self.ner.batch_extract_entities(
                    [sentence["text"] for _, sentence in batch],
                    self.labels,
                    batch_size=self.config.batch_size,
                    threshold=self.config.ner_threshold,
                    include_spans=True,
                    include_confidence=True,
                    max_len=None,
                )
                if len(results) != len(batch):
                    raise ValueError("GLiNER2 result count does not match candidate count")
            except Exception as error:
                for record, sentence in batch:
                    sentence["ner_status"] = "ERROR"
                    record["errors"].append(
                        {
                            "stage": "ner",
                            "sentence_id": sentence["sentence_id"],
                            "message": str(error),
                        }
                    )
                continue
            for (record, sentence), result in zip(batch, results, strict=True):
                try:
                    sentence["entities"] = normalize_entities(
                        result, sentence, record["article_text"], self.labels
                    )
                    sentence["ner_status"] = "COMPLETE"
                except Exception as error:
                    sentence["ner_status"] = "ERROR"
                    record["errors"].append(
                        {
                            "stage": "ner_spans",
                            "sentence_id": sentence["sentence_id"],
                            "message": str(error),
                        }
                    )
        for record, _, _ in locations:
            record["processing_status"] = "ERROR" if record["errors"] else "COMPLETE"
        return records


def load_pipeline(model_manifest: dict, config: RankingConfig) -> FocalEventPipeline:
    import spacy
    import torch
    from gliner2 import GLiNER2
    from sentence_transformers import SentenceTransformer

    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    embedder = SentenceTransformer(
        model_manifest["embedding"]["path"], device="cpu", local_files_only=True
    )
    ner = GLiNER2.from_pretrained(model_manifest["ner"]["path"], map_location="cpu")
    ner.eval()
    versions = {
        package: importlib.metadata.version(package)
        for package in (
            "spacy",
            "en-core-web-sm",
            "sentence-transformers",
            "gliner2",
            "torch",
            "transformers",
            "numpy",
        )
    }
    models = {
        **model_manifest,
        "packages": versions,
        "spacy_pipeline": nlp.meta,
        "embedding_max_seq_length": embedder.max_seq_length,
        "device": "cpu",
        "random_seed": 0,
        "deterministic_algorithms": True,
    }
    return FocalEventPipeline(nlp, embedder, ner, config, models)
