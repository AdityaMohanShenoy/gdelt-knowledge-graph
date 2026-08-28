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
uv run python -c "import duckdb, fastapi, neo4j, prefect, qdrant_client, spacy, torch, transformers; print('Python dependencies: OK')"
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

Next active work:

- India action-location filtering for the frozen 2024 raw snapshot
- A small reproducible working dataset for protests and civil unrest
- Canonical event and evidence schemas
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
