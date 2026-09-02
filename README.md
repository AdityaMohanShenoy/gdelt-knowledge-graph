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
uv sync --locked
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
uv lock --check
uv run python -c "import asyncpg, duckdb, fastapi, neo4j, prefect, qdrant_client, spacy, torch, transformers; print('Python dependencies: OK')"
bun x biome --version
bun x vitest --version
```

If Bun reports blocked lifecycle scripts during installation, trust the required local tooling and reinstall:

```bash
bun pm trust @biomejs/biome esbuild
bun install --frozen-lockfile
```

## Legacy implementation

The former country-filtering pipeline, URL validation, Neo4j export, FastAPI application, frontend, and historical curated outputs are preserved under `archive/legacy-exploration/` for reference. They are not the active data workflow and their old commands should not be used to produce the new working dataset.

The local raw GDELT snapshot remains under `out_parquet/`. It is intentionally ignored by Git and is the input for the fresh India-focused workflow.

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

Next active work:

- A stratified pilot sample and annotation guide
- Node and candidate-edge annotations for a few hundred records

Prepared but still to be implemented after the pilot:

- Canonical event and evidence schemas
- Temporal-uncertainty representation
- Candidate and verified causal-edge extraction
- Prefect workflows
- Qdrant semantic retrieval
- Hono API gateway and React/Vite frontend
- Evaluation for causal precision, evidence grounding, explanation faithfulness, and temporal coherence
