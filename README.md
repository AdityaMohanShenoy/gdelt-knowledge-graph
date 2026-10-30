# Decoding the Domino Effect

Decoding the Domino Effect is a research project on evidence-backed causal reasoning over temporal knowledge graphs built from GDELT data.

The previous Python exploration pipeline and dashboard are preserved in [archive/legacy-exploration/](archive/legacy-exploration/). The active project is now being rebuilt around a smaller, reproducible dataset of civil unrest and protests in India, followed by a pilot annotation set.

See [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) for the research context and [docs/techstack.md](docs/techstack.md) for the technology choices.

## Agent and contribution workflow

Repository-wide agent instructions are in [AGENTS.md](AGENTS.md). The local GitHub workflow skill is in [.agents/gh/SKILL.md](.agents/gh/SKILL.md) and defines the required commit, branch, testing, and draft pull-request process.

## Requirements

- Python 3.11–3.14
- [uv](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh/) 1.3.14 or newer
- Docker with Docker Compose (for the local article store)
- GDELT 2024 event Parquet data under `out_parquet/events/year=2024/`
- Neo4j is optional and only required for the Neo4j export step

The raw GDELT data files are not committed because of their size.

## Install

From the repository root:

```bash
uv sync
bun install
```

`uv sync` creates `.venv` and installs the Python runtime and development dependencies from `pyproject.toml` and `uv.lock`. `bun install` installs the TypeScript workspace dependencies from `package.json` and `bun.lock`.

For later installs or CI, use the lockfiles exactly:

```bash
uv sync
bun install --frozen-lockfile
```

If uv is not available, the Python dependencies can be installed with pip:

```bash
python -m venv .venv
source .venv/bin/activate                 # macOS/Linux
# .venv\Scripts\activate                 # Windows
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Verify the installation

```bash
uv run --group pipeline python -c "import asyncpg, duckdb, fastapi, neo4j, polars, trafilatura; print('Python dependencies: OK')"
bun x biome --version
bun x vitest --version
```

If Bun reports blocked lifecycle scripts during installation, trust the required local tooling and reinstall:

```bash
bun pm trust @biomejs/biome esbuild
bun install --frozen-lockfile
```

## The dashboard

`app.py` and `frontend/index.html` serve the live dashboard at
https://gdelt-knowledge-graph.vercel.app, deployed from `main`. It reads one
committed parquet (`out/step2_causal_filtered.parquet`) and nothing else at
runtime — see `CLAUDE.md` before changing its dependencies or query layer.

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Total events, date range, country count |
| `GET /api/graph` | Knowledge graph nodes and edges with QuadClass and CAMEO labels |
| `GET /api/edge-detail` | CAMEO description, sample events, causal analysis |
| `GET /api/timeline` | Monthly QuadClass breakdown and Goldstein trend |
| `GET /api/country-stats` | Per-country stats with monthly sparklines |
| `GET /api/events` | Paginated event list with search and filter |
| `GET /api/heatmap` | 10x10 country-pair interaction matrix |
| `GET /api/causal/score` | Causal Evidence scoring with full derivation trace |

Tabs: knowledge graph (circular and force-directed layouts), timeline,
country analysis, event explorer, heatmap, and Causal Evidence.

Run it locally with `pip install -r requirements.txt && python test_app.py`.

## Legacy implementation

Earlier exploratory versions of the pipeline and frontend are preserved under
`archive/legacy-exploration/` for reference. They are not the active workflow
and their commands should not be used to produce the new working dataset.

The local raw GDELT snapshot remains under `out_parquet/`. It is intentionally ignored by Git and is the input for the fresh India-focused workflow.

## Annotating causal claims

`pipeline/14_run_annotator.py` seeds candidate pairs into the evidence store and
serves the review screen that P2.4's annotation run uses.

```bash
python pipeline/14_run_annotator.py seed --targets 40
python pipeline/14_run_annotator.py serve --port 8200
open "http://127.0.0.1:8200/?annotator=your-name"
```

Set `ANNOTATOR_TOKEN` before exposing this anywhere but localhost — `annotations`
refuses DELETE, so anything a stranger writes is permanent in the set the
calibration rests on. Unset, the tool is open, which is what you want locally.

    ANNOTATOR_TOKEN=$(python -c 'import secrets;print(secrets.token_urlsafe(24))') \
      python pipeline/14_run_annotator.py serve

Then hand each person `?annotator=<name>&token=<token>`.

Open it and pick your name — pabo, nambi, akka or shenoy. Each queue is that
person's own. A quarter of claims are dealt to a second reader as well, so
inter-annotator agreement can be measured; re-run `assign` after seeding more.

Keys: `a` accept, `e` change strength, `r` reject, `1`-`8` pick a rejection
reason, `m` reveal what the scorer thought. The machine's own score is hidden by
default on purpose — P3.4 measures calibration by comparing it against the human
number, which is worth nothing if the human saw it first.

Every candidate is stored, including ones the scorer would drop: the rejections
are the hard negatives. The queue serves each target's strongest unjudged
candidate so coverage spreads across events rather than draining one.

## Pipeline layout

`pipeline/` is one continuous corpus pipeline. `01_build_india_universe`
through `09_reprocess_articles` build the India 2024 annotation corpus, and
`10_extract_focal_events` onward follow `docs/BUILD_PLAN.md`: `10` is the
focal-event pipeline, `11_probe_fetchability` measured fetchability, `13`–`15`
load the evidence store and run the causal annotator, and the plan continues with
`20` (event mentions), `21` (canonicalization) and `40` (graph build).

`pipeline/dashboard/` is a separate, finished lineage: the country filter,
causal filter, URL validation and Neo4j export that produced
`out/step2_causal_filtered.parquet`, the one file the dashboard reads at
runtime. It shares no code with the corpus pipeline and is rarely re-run.

## Build the India event universe

The first active data stage creates a local working dataset containing every 2024 event whose action location is India. It preserves all event roots, actors, dates, scores, identifiers, and source URLs; protest and causal filters happen later.

Run it from the repository root:

```bash
uv run python pipeline/01_build_india_universe.py
```

The generated files are:

- `data/working/india-2024/events.parquet` — local generated Parquet output, ignored by Git
- `data/working/india-2024/manifest.json` — filter, count, date-range, and schema metadata

The raw `out_parquet/` snapshot is never modified. The India filter uses `ActionGeo_CountryCode = IN`, so foreign actors can remain as context while events must be located in India.

## Filter target unrest roots

After building the India event universe, filter it to the direct unrest target roots:

- `14` — protest
- `18` — assault/violence
- `19` — fight/clash
- `20` — mass violence

Run:

```bash
uv run python pipeline/02_filter_target_roots.py
```

The generated files are:

- `data/working/india-2024/target_events.parquet` — local target-event output, ignored by Git
- `data/working/india-2024/target_manifest.json` — root counts, dates, filter, and schema metadata

This stage does not include contextual roots such as demands, rejection, threats, or coercion. Those will be added separately after the target universe is inspected.

## Remove events without live source links

The annotation set requires a source URL, so this pass checks every unique target-event URL and drops events whose URL is missing or dead. It uses concurrent requests, retries, and a persistent cache so interrupted runs can continue:

    uv run python pipeline/04_validate_target_urls.py

The generated files are:

- data/working/india-2024/target_events_url_validated.parquet — target events with validated source URLs only, ignored by Git
- data/working/india-2024/url_cache.json — per-URL validation cache, ignored by Git
- data/working/india-2024/url_manifest.json — URL counts, status counts, and dropped-event counts

The validator treats 404, 410, 451, connection errors, and repeated timeouts as dead. Redirects, access restrictions, rate limits, and server errors remain usable as source links because the URL still exists.

## Build event-level annotation records

The annotation view keeps one record per `GlobalEventID`. Repeated source URLs are retained as separate event records, so an identical article can support multiple observations without collapsing their event codes, actors, dates, or scores:

    uv run python pipeline/05_build_annotation_units.py

The generated files are:

- data/working/india-2024/annotation_units.json — event-level annotation records, ignored by Git
- data/working/india-2024/annotation_manifest.json — event and unique-source counts

The source event Parquet remains unchanged. The output path keeps its historical filename for viewer compatibility, but its schema is `india-annotation-events.v2` and its records are `event_observation` objects.

## Build the article URL queue

Article retrieval is a separate evidence stage over the complete India event universe. It normalizes HTTP(S) URLs, removes fragments, and produces one queue row per normalized URL. This queue is intentionally not restricted to the target-root event subset:

    uv run python pipeline/06_build_article_queue.py

The generated files are:

- data/working/india-2024/article_urls.parquet — normalized `url_key` and original `source_url` pairs, ignored by Git
- data/working/india-2024/article_urls_manifest.json — queue counts and normalization collisions

## Run the article extractor

Start the local Postgres store before the first ingest run:

    docker compose up -d postgres

Run a small pilot first. `--limit 100` claims 100 URL attempts from the queue; it does not change the queue or delete existing results:

    uv run python pipeline/07_ingest_articles.py --limit 100

The full queue can be resumed with:

    uv run python pipeline/07_ingest_articles.py --concurrency 100 --per-host-concurrency 4

The dispatcher uses one GET per attempt for both liveness and extraction, global concurrency of 100, a per-host cap of 4, database leases for restartable checkpointing, and three retries after the initial request. Host-aware claim selection applies the per-host cap before a URL occupies a worker, so a slow publisher cannot monopolize the global worker pool; restart the dispatcher after changing these settings. Separate indexed claim paths handle expired leases, ready retries, and pending URLs without scanning terminal rows, so a stopped run can resume efficiently. A fetching lease is reclaimed after five minutes if its worker exits. The per-run `Completed` counter records attempts, including retries; query Postgres statuses for unique-URL progress. It stores cleaned article text and metadata in Postgres and gzipped raw HTML under `data/evidence/articles/raw/`. Extraction statuses distinguish readable text, insufficient text, paywalls, bot/access blocks, dead links, unsupported content, oversized responses, parse errors, and exhausted retries. Trafilatura filters promotional blocks, navigation, ads, social widgets, and footer text; inaccessible or paywalled pages remain recorded with their reason instead of being treated as readable evidence.

The dispatcher owns all network requests. The Trafilatura extractor receives the fetched HTML bytes and final URL, removes page boilerplate, and applies a precision-first quality gate. It does not perform an additional request and cannot recover text that is only rendered by JavaScript, hidden behind a login or paywall, or absent from the response. The quality gate rejects short or structurally weak candidates, stale-page title/body mismatches, navigation and recommendation listings, and obvious error pages. It removes syndicated pipe wrappers, repeated lead text, comment widgets, publisher support sections, and leading navigation noise. Strong press-release and promotional signals remain readable but are recorded in `extraction_reason` for downstream filtering.

## Benchmark and reprocess stored article text

Raw HTML is retained so the extractor can be improved without downloading the queue again. Run a deterministic, non-mutating benchmark over a stratified sample of stored pages:

    uv run python pipeline/09_reprocess_articles.py benchmark --sample-size 200

The JSONL report is written under `data/evidence/articles/benchmarks/` and contains the previous database result beside pure Trafilatura precision, pure recall, and the production precision-first candidate. Review this report before promoting a new extraction pass. Promotion is resumable and only reads existing compressed raw HTML:

    uv run python pipeline/09_reprocess_articles.py promote

Promotion updates `status`, `title`, `cleaned_text`, `text_length`, `extraction_reason`, and `extractor_version` for rows with stored HTML. Rows currently being fetched are skipped and can be processed by a later run. The current UI and article API read these same canonical fields, so no frontend migration is required.

## Retrieve focal-event evidence locally

This POC treats one stored article as one primary-event hypothesis. It retrieves evidence with spaCy dependency parsing, Sentence Transformers, and local GLiNER2 NER. Results always remain `PENDING_REVIEW`; neither entities nor ranking scores establish a validated focal event. It does not construct event arguments, cluster articles, or infer causal relationships.

Install with `uv sync --group pipeline --group ml`, then download the pretrained checkpoints once:

```bash
uv run python pipeline/10_extract_focal_events.py prepare-models
uv run python pipeline/10_extract_focal_events.py extract --limit 40 --output data/evidence/focal_events/pilot.jsonl
uv run python pipeline/10_extract_focal_events.py annotate --input data/evidence/focal_events/pilot.jsonl --output data/evidence/focal_events/pilot.annotations.jsonl
```

The defaults are `en_core_web_sm` 3.8.0, `sentence-transformers/all-mpnet-base-v2`, and `fastino/gliner2-base-v1`, on CPU. Model preparation downloads public checkpoints from Hugging Face and records their resolved commit revisions in `data/evidence/focal_events/models.json`. Subsequent extraction loads these exact local snapshots with Hugging Face and Transformers offline mode enabled. No external inference API or generative model is used. `--embedding-model`, `--embedding-revision`, `--ner-model`, `--ner-revision`, and `--model-manifest` allow separate pinned experiments; model manifests are never overwritten. The spaCy parser wheel is locked with the Python dependencies. Inference uses evaluation mode, seed zero, and deterministic PyTorch algorithms. Cross-platform bit-for-bit reproducibility is not guaranteed.

Extraction reads the existing `article_documents` table without changing it. The article ID is the existing `document_id`, serialized as a string. The default sample contains only rows with `status = extracted`, ordered by a seeded hash of normalized URL; `--seed` reproduces selection while the store is unchanged. This is a reproducible pilot sample, not a guaranteed representative or India-2024-validated evaluation set. Review inclusion and article dates manually. Repeated `--article-id 123` arguments select exact records, including empty or inaccessible records for debugging. `--database-url` or the existing `DATABASE_URL` selects the store.

The JSONL retains the complete unchanged cleaned article, its SHA-256, source metadata, every paragraph and sentence in article order, all ranking scores, and the top three candidates in rank order. A separate list retains candidate sentence IDs in article order. Paragraphs follow nonempty lines in the stored cleaned text. IDs are one-based; offsets are zero-based, end-exclusive Python character indices into the saved cleaned article, rather than HTML bytes. Entity offsets are stored relative to both the article and its sentence, with confidence and sentence ID. Repeated entity text is distinguished by offsets. Models, package versions, schema, configuration, and processing errors are retained. The adjacent `.manifest.json` captures article IDs, text hashes, model provenance, counts, and a span audit. The database does not currently store publication timestamps, so `publication_timestamp` remains null; `fetched_at` is retained separately.

An optional `--config path/to/config.json` accepts this configuration:

```json
{
  "headline_weight": 0.6,
  "position_weight": 0.2,
  "event_weight": 0.2,
  "position_decay": 0.2,
  "ner_threshold": 0.5,
  "batch_size": 8,
  "include_event_entities": false
}
```

Raw headline cosine similarity is saved separately from its `[0, 1]` transformation `(cosine + 1) / 2`. Position uses `1 / (1 + position_decay * zero_based_sentence_position)`, so later evidence remains eligible. Event relevance combines verb predicates, subjects, finite verbs, and a fixed action vocabulary; reporting/opinion roots and modal verbs receive penalties. Cue details, including negation, are saved for inspection. Negated developments remain eligible. This is an English heuristic, not a factuality classifier or historical-event detector. Weighted scores are normalized by the sum of active weights. Missing headlines disable headline scoring and normalize the remaining weights. Weights must be nonnegative and include a positive position or event weight. Defaults are experimental rather than calibrated probabilities.

spaCy parses paragraphs in batches; embeddings batch headlines and sentences across articles; GLiNER2 batches selected sentences. Empty text yields `EMPTY_TEXT` with no candidates. Short articles retain all available sentences, without padding. Ranking and NER failures preserve source evidence and produce `ERROR`; a failed extraction command exits with status 2 after saving results. Invalid entity spans are recorded as errors rather than repaired by searching for matching text. Successful NER with no entities remains distinguishable from failed NER. Sentences outside the candidates have `ner_status = NOT_SELECTED`. Entity labels are PERSON, ORGANIZATION, LOCATION (including GPE), and DATE; experimental EVENT extraction requires explicit configuration. GLiNER2 receives whole selected sentences without a word cap. Sentence Transformers has a checkpoint-specific input limit: sentence token counts, `embedding_truncated`, headline truncation, and the model limit are recorded, while full evidence text is preserved. Inspect long-sentence cases during review.

### Review articles in the local frontend

For a protest-focused batch, screen the existing store before inference:

```bash
uv run python pipeline/10_extract_focal_events.py screen --limit 50 --output data/evidence/focal_events/protest-pilot.screening.jsonl
uv run python pipeline/10_extract_focal_events.py extract --screened-input data/evidence/focal_events/protest-pilot.screening.jsonl --output data/evidence/focal_events/protest-pilot.jsonl
uv run python pipeline/10_extract_focal_events.py annotate --input data/evidence/focal_events/protest-pilot.jsonl --output data/evidence/focal_events/protest-pilot.annotations.jsonl
```

Screening reads `target_events.parquet`, defaults to CAMEO root `14`, and requires an India action location and a GDELT `day` in 2024. It normalizes source URLs with the existing queue rules and deterministically samples matching `extracted` database rows. Repeat `--root-code` to include `18`, `19` or `20` for a separately identified broader unrest experiment. `--events-input`, `--seed`, and `--database-url` select another stored snapshot or reproducible sample. GDELT codes and dates are candidate metadata, not verification of an article's primary event, publication date or protest relevance.

The screening JSONL preserves the complete stored article and a separate current-extractor snapshot made from saved compressed HTML. It does not update Postgres or fetch source websites. The manifest records input/output and implementation hashes, observation IDs, candidate scope, selection seed and counts. Missing or unreadable raw HTML retains the original text as `UNVERIFIED`, with the failure recorded. Extractor-rejected pages remain in the screening file as `UNSUITABLE`; inference skips them and records their IDs and reasons in its manifest. Empty/all-rejected batches fail rather than produce fake successful inference. Article IDs are unchanged; any new text requires new sentence/entity annotation offsets, so earlier annotations must not be transferred by article ID alone.

`--short-word-threshold` defaults to 100 whitespace-separated words and is a review flag, not a deletion threshold. Short readable reports remain eligible for inference. Text quality is independent of protest relevance: `READABLE`, `SHORT_REVIEW`, `UNVERIFIED` and `UNSUITABLE` describe extraction, while `relevance_status` stays `PENDING_REVIEW`. Exact headline/body protest-cue spans support inspection; mentions can be historical, quoted, negated or unrelated, and cue presence never accepts an article automatically. All text, including articles outside inference, is retained. Screening and matching GDELT observations also accompany inference results and annotations. Review both protest relevance and body completeness before treating the new batch as an evaluation set.

The generated protest pilot screens 60 deterministic root-14 candidates. The current extractor retained 57 readable bodies and one short report, and rejected two snapshots; all 60 saved HTML files were available. Forty-three snapshots contain a body protest cue, which is a diagnostic rather than a relevance score. Local inference completed for all 58 retained snapshots, and all 2,734 audited evidence spans match their source text. The review-ready files are `protest-pilot.screening.jsonl`, `protest-pilot.v2.jsonl` and `protest-pilot.v2.annotations.jsonl` under `data/evidence/focal_events/`; the original first-pass outputs are retained. Repeating inference on all 58 frozen snapshots produced identical results apart from processing timestamps. The v2 manifest also validates and references the screening selection manifest. Their focal-event accuracy remains unset pending annotation. Screening behavior is covered by `tests/test_focal_event_screening.py`, including URL normalization, geography/date scope, short-text retention, rejected-text preservation, changed-snapshot rejection and Postgres-to-snapshot integration.

The expanded `protest-review-300.screening.jsonl` screens 300 root-14 candidates with the same `protest-screening-v1` seed. Its first 60 screening records exactly match the earlier pilot, so it is a larger nested sample rather than an independent test set. All 300 saved HTML files were available. Screening retained 274 readable articles and five short articles; 21 extractor-rejected snapshots remain in the screening file with their original stored text and reasons. The 279 retained articles cover 58 source hosts and have GDELT observations in every month of 2024. These dates describe the observations, not verified article publication or focal-event dates. Two hundred retained bodies contain a protest cue; relevance remains pending review.

Among the retained articles, word-count quantiles are approximately 134 at the 10th percentile, 206 at the 20th percentile and 363 at the median, using linear interpolation. Removing articles below those percentiles would discard 28 or 56 retained cases respectively, including five short cases already flagged for inspection. The saved 77-word article `559943` contains a protest action, organization, location and publication line, demonstrating why short text merits inspection. Word counts alone do not establish whether focal-event evidence is sufficient. All retained text remains available for review, and the rejected snapshots remain available for extraction debugging. Reproduce the expanded batch with fresh output filenames:

```bash
uv run python pipeline/10_extract_focal_events.py screen --limit 300 --seed protest-screening-v1 --output data/evidence/focal_events/protest-review-300.screening.jsonl
uv run python pipeline/10_extract_focal_events.py extract --screened-input data/evidence/focal_events/protest-review-300.screening.jsonl --output data/evidence/focal_events/protest-review-300.jsonl
uv run python pipeline/10_extract_focal_events.py annotate --input data/evidence/focal_events/protest-review-300.jsonl --output data/evidence/focal_events/protest-review-300.annotations.jsonl
```

Local inference completed for all 279 retained articles, preserving 6,518 sentences, 837 candidates and 3,647 entity predictions. No sentence or headline embeddings were truncated. The saved audit validates all 14,146 spans and finds no inconsistent records. All 279 annotation templates retain `UNREVIEWED` event and eligibility statuses, and ranking/NER accuracy remains null in `protest-review-300.metrics.json`. Source evidence, candidate rank order and entity spans/labels match all 58 overlapping pilot records. Fifty-six records are identical apart from processing timestamps; changing the final two articles' batch composition produces numerical differences up to approximately `3.3e-7` in ranking scores and `2.8e-6` in entity confidence, without changing their extracted spans or rankings. Pinning model revisions and batch configuration does not imply identical floating-point scores across different batch compositions.

`protest-review-300.v2.annotations.jsonl` is a fresh template for the same 279 immutable snapshots, adding the enabled entity schema and separate unreviewed entity-review metadata. The earlier template and exports are retained. Its `protest-review-300.metrics.v3.json` leaves ranking and NER accuracy unset and audits all 14,146 spans successfully. `pilot.user-relevance.metrics.v4.json` preserves the earlier exploratory results while explicitly identifying all ten scored entity-annotation records as legacy AI-assisted labels. These new reports do not establish a person-verified protest benchmark.

`protest-review-300.diagnostics.json` preserves input hashes, word-count bins/quantiles, source-host and GDELT-observation coverage, skipped IDs, pilot overlap and 59 entity spans with multiple predicted labels across 44 articles. These conflicting labels are retained for adjudication before constructing typed graph entities; confidence and exact offsets do not establish a correct entity type. The report does not accept relevance, assign gold event labels, resolve conflicts or cluster events. Host and month counts describe the sampled evidence, rather than verified event coverage.

The 300-record AI-assisted review packet is `protest-review-300.ai-assisted.packet.jsonl`, with the corresponding full-event file in `protest-review-300.ai-assisted.annotations.jsonl`, screening proposals in `protest-review-300.ai-assisted.screening.jsonl`, and provenance in `protest-review-300.ai-assisted.manifest.json`. It includes all 300 screened records: 279 retained snapshots receive full sentence-level drafts and 21 extractor-rejected snapshots remain explicit screening-only exclusions. The current conservative proposals identify 205 usable focal-event drafts, 95 proposed exclusions, 204 records with direct protest language, one protest-linked record, 74 unrelated records and 21 records with insufficient text. They select 477 supporting sentences and copy no model entities into `gold_entities`; entity review remains pending. Every event and screening record remains `UNREVIEWED`, with `reviewer = Codex (AI)` and `label_source = ai_assisted`. The proposal fields are machine-readable review aids, not human-verified gold labels, and must be confirmed against the full saved article before evaluation.

Serve the all-record packet without prediction results for screening and event review, or use the 279-record file with the saved predictions for model inspection:

```bash
uv run python pipeline/08_run_viewer.py --port 8001 --review-annotations data/evidence/focal_events/protest-review-300.ai-assisted.packet.jsonl
uv run python pipeline/08_run_viewer.py --port 8001 --review-annotations data/evidence/focal_events/protest-review-300.ai-assisted.annotations.jsonl --review-results data/evidence/focal_events/protest-review-300.jsonl
```

The packet's summaries and support selections are grounded in the frozen local snapshots and exact sentence offsets. Human reviewers should correct any proposed relevance, event status, summary, support, screening reason or entity list before exporting a reviewed batch; accuracy metrics remain unset while the records are unreviewed.

The completed AI draft packet was checked in `protest-review-300.ai-assisted.audit.json`. All six manifest-referenced files match their hashes, all 300 source IDs are present, the 279 event snapshots and support references match the saved predictions, and the 21 screening-only exclusions preserve their screened text and source metadata. Frontend parsing and Unicode text-hash verification also passed for all 300 records. Actual event, eligibility and entity statuses remain `UNREVIEWED`, and every `gold_entities` field is null. `protest-review-300.ai-assisted.metrics.json` therefore leaves focal-event and NER accuracy unset while validating all 14,146 prediction evidence spans.

Against the 205 proposed usable drafts, retrieved sentences overlap the proposed support in 108/205 Top-1 cases (52.7%) and 155/205 Top-3 cases (75.6%). Fifty proposals have no supporting sentence among the top three; 140 include evidence outside those candidates. These are exploratory agreement counts rather than validated extraction accuracy: the drafting notes disclose access to model candidates, and a targeted qualitative check found incorrect labels. The audit preserves eight cases with exact evidence: technology and agricultural demonstrations labelled as protests (`520546`, `610429`, `527359`); earlier protest background selected instead of crew dismissals or current tear-gas use (`609269`, `549638`); mixed-country or multi-event extracts and unsupported scope (`625433`, `307656`, `210218`). In the dismissal and tear-gas cases, the model already retrieved the primary development, so disagreement must not automatically be treated as ranking failure. This spot check is AI-assisted and is not an exhaustive replacement gold annotation.

The proposal audit also flags 21 `body_quality = INSUFFICIENT_TEXT` values: the supported body-quality label is `INSUFFICIENT`, while `INSUFFICIENT_TEXT` is an exclusion reason. Current eligibility labels are empty, so the files remain importable; copying those proposal values directly into eligibility would fail validation. All 279 retained proposals assign `INDIA_2024` from candidate metadata, which still requires event-level geography/date adjudication. Correct proposal errors and separately verify an evaluation subset before tuning ranking weights; annotate full-article entity occurrences before measuring NER quality. The audit leaves every source and annotation file unchanged.

The actual 279-record file passed the local API/Chromium import/export check, including lossless export, draft recovery after reload, replacement by an authoritative import, rendering all 137 sentences of the longest article, and mobile width. Draft fields used about 98 KB of browser storage; full articles remain in the exported batch and are not duplicated in the draft cache. The exported draft file also passed Python snapshot/evidence validation. To open this larger review batch:

```bash
uv run python pipeline/08_run_viewer.py --port 8001 --review-annotations data/evidence/focal_events/protest-review-300.v2.annotations.jsonl --review-results data/evidence/focal_events/protest-review-300.jsonl
```

Use the original 58-article pilot for calibration and assign development/test splits before tuning on the expanded sample. Previously inspected pilot records must not become held-out test cases. Source and temporal overlap still need review; no independent test split or cohort balance is claimed for the expanded seeded sample.

Open the generated protest batch with:

```bash
uv run python pipeline/08_run_viewer.py --port 8001 --review-annotations data/evidence/focal_events/protest-pilot.v2.annotations.jsonl
```

Then open http://127.0.0.1:8001/review.

Start the existing local viewer and open its review page:

```bash
uv run python pipeline/08_run_viewer.py
```

Open http://127.0.0.1:8000/review. The page automatically loads `data/evidence/focal_events/pilot.annotations.jsonl`. Use `--review-annotations path/to/annotations.jsonl` to serve a different batch, or use **Import annotations** in the page. The existing event viewer remains at `/`. The viewer still requires the local Postgres store at startup; reviewing annotations reads the configured JSONL file without updating the database or the source annotation file.

Read the full article and click numbered sentences to select or remove supporting evidence. Enter the primary-event summary, reviewer name, article type, label source, optional evaluation split, and notes. **Mark reviewed & next** requires a reviewer, provenance, a summary, and at least one supporting sentence; it advances to the next unfinished article. **Exclude article** requires a reviewer, provenance, and an exclusion category or explanatory notes; other reasons require notes. Exclude articles without an identifiable primary event rather than articles where the ranking missed valid evidence. Changes to a reviewed or excluded annotation return it to draft until it is confirmed again. All sentences are available, and model rankings are hidden while the article is a draft. Original full text can be expanded beneath the reading view.

Pass `--review-results path/to/predictions.jsonl` to enable **Inspect model evidence** after a review or exclusion decision is saved. Return to that article in the queue and expand the inspector to compare the top three candidates with selected supporting sentences. It shows the saved ranking signals, exact entity spans, model confidence and provenance. Entity spans assigned multiple labels are marked for adjudication. Failed entity extraction is shown separately from successful extraction with no entities. Inspecting results does not accept an event or copy predictions into gold entities. Returning the article to draft closes and clears the model view.

The local `POST /api/focal-review/evidence/{article_id}` endpoint only reads the configured results file. It checks its schema and evidence audit, then validates the submitted annotation's complete text, hash, headline, sentence segmentation and applicable source metadata against the stored result. Missing results return 404; changed or inconsistent evidence returns 422. Responses include a hash of the exact parsed file bytes and use `Cache-Control: no-store`. The request does not change Postgres, source annotations or extraction files, and cannot choose a filesystem path. Annotation-only review remains available without `--review-results`.

Successful inspection adds an optional `model_evidence_inspections` history entry to the annotation with the result filename, file SHA-256 and first viewing timestamp. Reopening the same results file does not duplicate the entry. These entries survive draft recovery and export, while an authoritative import replaces them with the imported history. Evaluation reports reviewed label-source counts and the number of reviewed articles with recorded model inspection under `annotation_provenance`. Inspection history makes model exposure visible; its absence does not prove that labels were created without assistance elsewhere. Keep independent held-out labels separate from labels revised after viewing model outputs.

Drafts save in browser-local storage for the exact article and sentence batch. Reloading or **Load pilot** restores them and opens the first unfinished article. **Import annotations** treats the imported file as authoritative for its batch, including its labels; it does not overlay older browser drafts on that import. Search and status filters narrow the article queue. Previous/Next buttons and Alt + left/right arrow navigate the whole batch. Reviewer names are remembered in the browser for subsequent articles. Storage failures are shown explicitly; export a backup before closing when storage is unavailable. Browser-local drafts are specific to the browser and local origin, so changing ports or browsers requires an exported backup.

After saving an event review, return to the article and open **Annotate entities**. **Select from original article** expands the complete saved text. Select a written name or date, choose its label, then **Add entity**; remove incorrect occurrences from the gold list and select replacements from the source. Every occurrence needs its own span, including background and repeated mentions. Offsets use Python Unicode character indices and exclusive ends; partial Unicode characters and duplicate same-label spans are rejected. New templates carry the extraction's `entity_schema`; older files use PERSON, ORGANIZATION, LOCATION and DATE. Experimental EVENT is available only when declared in that schema.

Entity review has its own reviewer, provenance and whole-article confirmation. **Confirm entity review** requires the explicit whole-article checkbox, including when no entities are present. Adding, removing or changing entity provenance returns entity review to draft without changing the focal-event decision. Partial entity lists are excluded from NER metrics. New records use `ner_annotation`; legacy entity lists without it retain their earlier exploratory evaluation behavior and are counted separately as `legacy_annotated_articles`. Confirming legacy entities records the separate entity-review provenance. Model predictions are never automatically copied into gold labels.

**Export annotations** downloads the complete annotation JSONL, including unfinished event and entity drafts. It preserves article IDs, hashes, headlines, full text and every sentence's original offsets. Existing gold entities remain unchanged unless explicitly edited. Browser drafts use `focal-review-drafts.v2` and a batch-specific v2 storage key; existing v1 event/screening/inspection drafts migrate without applying entity or source mutations, and the old cache remains available. Imported snapshots are checked against their SHA-256 and Python character offsets, including Unicode characters outside the basic multilingual plane. Article text is rendered as text, rather than HTML. Copy the downloaded file into the local evidence directory, then evaluate it using a new output filename:

```bash
uv run python pipeline/10_extract_focal_events.py evaluate --input data/evidence/focal_events/pilot.jsonl --annotations data/evidence/focal_events/pilot.reviewed.annotations.jsonl --output data/evidence/focal_events/pilot.reviewed.metrics.json
```

Frontend validation is in `tests/test_review_frontend.py`: pure JavaScript import/export and draft validation, manual entity editing, inspection-history/conflicting-label checks, local API integration, and real Chromium review/export/recovery flows whose exports are evaluated by the Python scorer. Coverage includes Unicode selections, entity drafts excluded from NER metrics, whole-article confirmation, separate event/entity provenance and v1 cache migration. It checks that model results stay hidden during draft annotation, that inspection preserves gold evidence, and that changed or inconsistent snapshots cannot be displayed through the API. It uses the installed workspace Playwright dependency. Install its browser once with `node node_modules/playwright/cli.js install chromium --no-shell`, then run `uv run pytest tests/test_review_frontend.py -q`. A custom `PLAYWRIGHT_BROWSERS_PATH` can point to temporary browser installations. Missing Playwright dependencies are reported as skipped browser coverage; missing Chromium causes the browser test to fail rather than pretend to pass.

The **Article screening** section records protest relevance, article-body quality, India/2024 scope and a separate screening reviewer. **Save screening** confirms those decisions without marking event evidence reviewed. Screening progress is shown separately, and the screening review opens again when its labels change. **Exclusion category** distinguishes unrelated articles, insufficient text, wrong geography/time, no focal event and other reasons. A category or explanatory notes is required for exclusion. The screening reviewer is independent of the evidence reviewer, so a person who only checked relevance does not silently become the author of AI evidence labels. Older annotation files without screening labels remain importable and exportable.

Evaluation also reports confirmed `article_screening` label counts and a separate `protest_benchmark`. Unsaved draft labels do not contribute to screening counts; exclusion categories are counted when exclusion is confirmed. That benchmark includes only event-reviewed articles whose screening reviewer classified them as a protest or directly protest-linked development, with substantive body text and confirmed India/2024 scope. Limited previews and unresolved scope remain available in the general metrics but are excluded from this benchmark. Articles with relevance screening alone are not counted as validated event evidence. Legacy labels without eligibility decisions continue to contribute to general metrics, while their protest-benchmark denominator remains zero.

The user-exported pilot decisions are preserved byte-for-byte in `data/evidence/focal_events/pilot.user-relevance.annotations.jsonl`; `pilot.user-relevance.metrics.json` scores them against the unchanged original pilot. Ten records are retained and 30 excluded. General Top-1 accuracy is 5/10 and Top-3 recall is 10/10 against the accepted AI-assisted labels; these are exploratory metrics, not a person-verified protest benchmark. The export changed only review statuses and has no separate relevance, body-quality or scope labels, so the strict protest-benchmark denominator is zero. Its existing reviewer, notes, full text and entities were preserved rather than rewritten. The screening, frontend, model-inspection and evidence-audit changes passed 161 Python tests with no skips, including local Postgres, pretrained models and the Chromium review/export flow; Python and JavaScript linting and the explicit Python 3.13 type checks passed. The local model test emitted seven upstream PyTorch deprecation warnings.

The model inspector also passed the actual 279-article batch through the local API and Chromium. Verification displayed conflicting labels for article `611448`, preserved one inspection-history entry after reload, rejected a changed headline, retained exact evidence and gold entities, and fit the mobile viewport. Temporary browser fixture decisions returned to `UNREVIEWED` before export; the source annotation and extraction files remained byte-for-byte unchanged. That draft export passed Python validation with every accuracy metric still unscored. New reports `pilot.user-relevance.metrics.v3.json` and `protest-review-300.metrics.v2.json` add annotation provenance while preserving the earlier ranking/NER values. The accepted pilot labels report ten AI-assisted reviewed articles and no recorded browser inspections; the expanded source batch remains entirely unreviewed. Earlier files and reports are retained.

The manual entity editor and evaluation gate passed 172 Python tests with no skips, including local Postgres, pretrained models and both Chromium review workflows. Ruff, JavaScript syntax/linting and scoped Python 3.13 type checks passed. The pretrained-model test emitted seven upstream PyTorch deprecation warnings. The separate TypeScript workspace still has no application packages, TypeScript tests, Playwright specs or `tsconfig`; its declared commands do not constitute passing suites for this POC. Browser integration coverage runs through the Python tests above.

The actual v2 279-article batch also passed the entity-editor check through the local API and Chromium. A software fixture selected one exact span in article `611448`, retained its draft entity state after reload, displayed the model results, and rejected a changed entity offset. Source files remained byte-for-byte unchanged and the editor fit the mobile viewport. The temporary export returned all event decisions to `UNREVIEWED`, kept the entity occurrence in draft with explicit software-fixture provenance, and passed Python snapshot validation with every accuracy metric still unset. These verification fixtures are not research annotations.

Freeze a fully reviewed batch into a versioned dataset with a manifest. It refuses unreviewed records, split mismatches, and a `gold` name while any label is AI:

```bash
uv run python pipeline/10_extract_focal_events.py freeze --input data/evidence/focal_events/protest-review-300.focal.v1.packet.jsonl --predictions data/evidence/focal_events/protest-review-300.jsonl --splits-manifest data/evidence/focal_events/protest-review-300.splits.packet.manifest.json --output data/evidence/focal_events/protest-review-300.weak.v1.annotations.jsonl
```

Stored inference results can be audited without model inference or annotations:

```bash
uv run python pipeline/10_extract_focal_events.py audit --input data/evidence/focal_events/protest-pilot.v2.jsonl --output data/evidence/focal_events/protest-pilot.v2.audit.json
```

The audit records the input file hash and checks exact spans, article-text hashes, paragraph containment, full-text coverage, unique sentence/candidate IDs, source order, candidate references and entity labels, confidence ranges and sentence-relative offsets. Candidate objects must agree with their original sentence records; literal substring presence alone does not establish a valid reference. `evidence_consistency` identifies every inconsistent article with span details and structural reasons. `audit` and `evaluate` save their report and exit with status 2 when inconsistencies are found; malformed inputs fail before a report is produced. Extraction also exits with status 2 for an inconsistent evidence result. Existing output files are never overwritten. Empty audit batches fail, while stored empty-text articles remain explicit processing outcomes.

Annotation snapshot validation applies to drafts and exclusions as well as reviewed labels, within the requested evaluation split. Full text, headline, hash, ordered sentence IDs, paragraph IDs and offsets must match the prediction snapshot. Screened snapshots must also retain matching screening/source metadata; legacy unscreened templates may omit source metadata, but any included metadata must agree. Missing predictions, duplicate support/entity annotations, boolean sentence IDs, unsupported entity labels and nonfinite JSON numbers, including numeric overflow, are rejected. Entity sentence references must be integer IDs. A candidate with a mismatched sentence reference cannot count as a Top-1/Top-3 hit; only the first three candidates contribute to Top-3. These checks validate evidence structure and provenance rather than event factuality or causal relationships.

The stronger audits passed all 40 original pilot articles and all 58 screened pilot articles: 4,571 evidence spans and zero inconsistent records. Reports are saved as `pilot.audit.v2.json` and `protest-pilot.v2.audit.json`. Evaluation was repeated in `pilot.user-relevance.metrics.v2.json` and `protest-pilot.v2.metrics.v2.json`; the exploratory 5/10 Top-1 and 10/10 Top-3 results are unchanged, and the screened batch remains unscored. Original files and earlier reports are retained. Regression coverage includes changed draft/excluded snapshots, duplicate support/entities, invalid sentence references, missing full-text coverage, metadata changes, overflowing JSON numbers and command-line failure reports.

### Annotate and evaluate the pilot

Annotation export includes the headline, full article, and numbered sentences without model ranks, reducing anchoring on predictions. Edit each JSONL record using:

- `review_status`: `REVIEWED` after human inspection, `UNSUITABLE` when a single focal event cannot reasonably be identified, or `UNREVIEWED` to leave it out of scored metrics.
- `reviewer` and `label_source`: reviewer identity and `human` or `ai_assisted`. AI drafts require human verification before marking them reviewed.
- `focal_event_summary` and `supporting_sentence_ids`: identify the primary development and every acceptable supporting sentence, including evidence outside the selected three. Announced future actions and ongoing protests can be focal developments; distinguish their status in the summary. Background-only reporting may be unsuitable.
- `cohort`: use `single_event`, `multiple_events`, `historical_background`, `ongoing_protest`, or `government_decision` to inspect the requested article types. Add unsuitable reasons in `notes`.
- `split`: `pilot`, `train`, `dev`, or `test`. Reserve articles for held-out evaluation before tuning weights. With 200–300 reviewed articles, use development labels for tuning and a separate fixed test set; do not add supervised training until baseline errors justify it. Review source overlap and temporal coverage manually before assigning splits.
- `gold_entities`: null means NER has not been annotated. For NER evaluation, exhaustively annotate occurrences of the enabled categories throughout the full article, using objects such as `{"text": "Delhi", "label": "LOCATION", "start_char": 10, "end_char": 15}`. The displayed offsets are illustrative. Annotating only model-selected sentences would hide retrieval losses.
- `ner_annotation`: separate entity `review_status`, `reviewer`, `label_source`, `whole_article_checked` and `reviewed_at`. Only `REVIEWED` entity annotations contribute NER metrics, and a confirmed empty list means no enabled entities were found. Entity drafts do not affect sentence-ranking metrics. Legacy files without this field remain compatible; evaluation reports their contribution separately.
- `entity_schema`: enabled extraction labels and descriptions copied into new templates. When present, evaluation requires an exact match with the prediction schema; legacy files may omit it.

Measure extraction quality after labels are reviewed:

```bash
uv run python pipeline/10_extract_focal_events.py evaluate --input data/evidence/focal_events/pilot.jsonl --annotations data/evidence/focal_events/pilot.annotations.jsonl --output data/evidence/focal_events/pilot.reviewed.metrics.json
```

Use `--split test` for held-out metrics. Evaluation reports Top-1 accuracy and Top-3 recall alongside `gold_support` (mean support sentences and share of the article) and a `random` baseline giving the expected Top-1 and Top-3 hit rate of a uniformly random ranking. Larger support sets raise that floor, so read Top-k against it. It also reports exact-offset-and-label NER precision, full-article NER recall, candidate-only NER recall, evidence-span validity, cohort Top-3 recall, processing counts, and missed focal-event article IDs. Full-article NER recall includes retrieval losses; candidate-only recall isolates NER performance. Headline-only baselines exclude missing headlines and expose their denominator. Reviewed ranking/NER failures remain in the focal-evidence denominator. Missing predictions, duplicate article IDs, unsupported labels, changed text snapshots, and changed sentence segmentation are rejected. Undefined metrics return null, including when no labels have been reviewed; producing candidates alone does not establish quality. Evidence validity audits all saved paragraphs, sentences, candidate sentences, and entity offsets, including unreviewed records.

Start with 30–50 manually screened articles covering the five cohorts, inspect Top-3 misses, then expand to 200–300 human-reviewed articles. Keep AI-assisted drafting provenance and a person-verified test set. The immediate review question is whether the correct focal development is represented in the top three; supervised sentence ranking can be considered only after this baseline is measured. Stored cleaned text can still contain navigation or repeated headlines, which may receive high similarity scores; include these input-quality cases in review notes. Generated full-text evidence, models, and annotations remain private local files under ignored `data/evidence/`. Existing outputs are never overwritten; use a new filename for every extraction or annotation experiment.

The local 40-article batch has a completed AI annotation pass in `data/evidence/focal_events/pilot.ai-assisted.annotations.jsonl`, with provenance, input/output hashes, per-article proposed dispositions and validation counts in the adjacent `pilot.ai-assisted.annotations.manifest.json`. Every saved article was read without viewing model rankings. The batch contains 26 proposed usable focal events, 14 proposed exclusions with reasons, 153 supporting sentence selections and 1,537 entity occurrences across all 40 unchanged snapshots. All records use `reviewer = Codex (AI)`, `label_source = ai_assisted` and `split = pilot`. Their status remains `UNREVIEWED` pending human verification; the completed summaries, evidence, entities and proposed dispositions are available for adjudication, and are not person-verified gold labels. Article type is left unset for eight navigation/title-only snapshots whose cohort cannot be adjudicated from the saved text. The original annotation template and earlier metrics remain unchanged. The separate `pilot.ai-assisted.metrics.json` records evidence validity with focal-event and NER accuracy unset.

Import this file into the review frontend, or serve it directly:

```bash
uv run python pipeline/08_run_viewer.py --review-annotations data/evidence/focal_events/pilot.ai-assisted.annotations.jsonl
```

The pass proposes exclusion of navigation-only and title-only extracts, a redirected homepage, a multi-event calendar, an entertainment guide, general voting instructions and background analyses without a defensible focal development. It retains report findings and clearly identified developments in opinion or promotional reporting with explicit qualifications. Records `421197`, `419299` and `524793` use limited previews or a substantive introductory deck and need re-adjudication for a strict full-body evaluation. Record `379536` describes a meeting in Laos, and `308351` is a declared university advertorial. These labels do not certify India action location, unrest relevance, representativeness or factual accuracy. Relative dates, allegations, proposed policies, future actions, repeated passages and contaminated text are explained in each record's notes.

Entity spans cover the complete saved text, including repeated mentions, background, bylines and extraction noise; excluded records retain entity annotations but are not proposed focal-event evaluation cases. Use non-overlapping written names with exact Python character offsets: named people (including fictional people in the entertainment extract), institutions/parties/companies/publishers/platforms, places and calendar references. A complete institution name takes precedence over an embedded location; separately written acronyms are separate occurrences. Generic roles, family references, laws, schemes and product titles are excluded. Calendar and financial years and relative calendar references remain as written; durations, clock times and legislation identifiers are not dates. Fused bylines and datelines are annotated without editing the original text. The batch passed snapshot/hash checks, sentence and entity span checks, and the frontend's Unicode verification and lossless import/export roundtrip. Focal-event and NER accuracy remain unscored until the labels are human-verified.

Run `uv run pytest tests/test_focal_events.py -q` for unit, CLI, database, and pretrained-model checks. The database integration is skipped when local Postgres cannot be reached; the model integration is skipped until checkpoints have been prepared. These skips are not passing integrations. Set `FOCAL_EVENT_MODEL_MANIFEST` to test an alternate local manifest. The broader Python suite is `uv run pytest -q`; linting uses `uv run ruff check pipeline tests`. The POC was also type-checked on the installed Python 3.13 environment using `uv run mypy --python-version 3.13 pipeline/focal_events.py pipeline/focal_event_evaluation.py pipeline/10_extract_focal_events.py tests/test_focal_events.py`. The repository's default Python 3.11 mypy target cannot parse the installed NumPy stubs that use Python 3.12 type statements; the explicit interpreter-version check does not change that default configuration.

## Open the target event viewer

The viewer reads event-level records and retrieves article text on demand through the local API. Generate the event records and start the API-backed viewer:

    uv run python pipeline/05_build_annotation_units.py
    uv run python pipeline/08_run_viewer.py

Open http://127.0.0.1:8000/ and use Card stack for left-to-right browsing or File list for directory-style browsing. The viewer supports root filtering, text search, keyboard arrows, pointer swipes, source links, and a `Fetch article text` action. That action queues the selected normalized URL, starts a bounded background request using the same extractor and retry rules as bulk ingestion, and polls Postgres until text or a terminal status is available. The JSON file can still be loaded manually for metadata-only review.

## TypeScript workspace status

The Bun workspace currently provides the dependency and tooling foundation. The application packages have not been built yet, so there is no Bun command that starts the planned web interface or gateway at this stage.

The available tooling commands are:

```bash
bun run lint
bun run format
bun run typecheck
bun run test
```

These commands become the standard checks as the new TypeScript packages are added.

## Project status

Archived for reference:

- Previous Python filtering, causal filtering, URL validation, Neo4j export, and FastAPI/D3 dashboard
- Historical curated output and top-country summary

Implemented local workflow:

- India action-location universe builder and target-root filter for the frozen 2024 raw snapshot
- Event-level viewer records keyed by `GlobalEventID`
- Full-universe normalized article URL queue
- Dockerized Postgres article store with leases and checkpointed retries
- Trafilatura article extraction and liveness classification with offline reprocessing
- Local API-backed viewer for on-demand cleaned article text
- Local focal-event evidence ranking, GLiNER2 entities, annotation export, and evaluation
- Local sentence-selection frontend with browser draft recovery and annotation JSONL export

Next active work:

- Separate relevance, body-quality and scope review for the protest-focused pilot
- Validate focal-event evidence on a fixed held-out set before tuning retrieval
- Expand to 200–300 reviewed articles and establish the event representation before causal graph construction

Prepared but still to be implemented after the pilot:

- Canonical event and evidence schemas
- Temporal-uncertainty representation
- Candidate and verified causal-edge extraction
- Prefect workflows
- Qdrant semantic retrieval
- Hono API gateway and React/Vite frontend
- Evaluation for causal precision, evidence grounding, explanation faithfulness, and temporal coherence
