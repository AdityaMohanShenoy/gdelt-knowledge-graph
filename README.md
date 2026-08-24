# Decoding the Domino Effect

Decoding the Domino Effect is a research project on evidence-backed causal reasoning over temporal knowledge graphs built from GDELT data.

The repository currently contains the existing Python exploration pipeline and dashboard. The new local-first Python/Bun environment is installed and reproducible, but the planned Hono gateway, React frontend, Prefect orchestration, and verified causal graph are not implemented yet.

See [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) for the research context and [docs/techstack.md](docs/techstack.md) for the technology choices.

## Agent and contribution workflow

Repository-wide agent instructions are in [AGENTS.md](AGENTS.md). The local GitHub workflow skill is in [.agents/gh/SKILL.md](.agents/gh/SKILL.md) and defines the required commit, branch, testing, and draft pull-request process.

## Requirements

- Python 3.11–3.14
- [uv](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh/) 1.3.14 or newer
- GDELT 2024 event Parquet data under `out_parquet/events/year=2024/`
- Neo4j is optional and only required for the Neo4j export step

The data files are not committed because of their size.

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

## Run the current pipeline

Run commands from the repository root. The pipeline stages are sequential:

```bash
uv run python pipeline/01_filter_countries.py
uv run python pipeline/02_causal_filter.py
uv run python pipeline/03_validate_urls.py
```

The URL validation stage makes external HTTP requests and may take time. The generated files are written to `out/`.

To export the processed data to Neo4j, start a local Neo4j instance and provide its connection settings. For macOS/Linux:

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=yourpassword
uv run python pipeline/04_export_neo4j.py
```

The Neo4j export is optional; the first three stages do not require Neo4j.

## Run the current dashboard

The dashboard reads the output produced by the causal-filtering stage, or the URL-validation output when it exists:

```bash
uv run uvicorn app:app --reload --port 8000
```

Open <http://localhost:8000> in a browser.

If the dashboard reports that no processed data was found, run at least:

```bash
uv run python pipeline/01_filter_countries.py
uv run python pipeline/02_causal_filter.py
```

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

Runnable today:

- Python GDELT filtering, causal filtering, URL validation, and optional Neo4j export
- Existing FastAPI/D3 dashboard

Prepared but still to be implemented:

- Canonical event and evidence schemas
- Temporal-uncertainty representation
- Candidate and verified causal-edge extraction
- Prefect workflows
- Qdrant semantic retrieval
- Hono API gateway and React/Vite frontend
- Evaluation for causal precision, evidence grounding, explanation faithfulness, and temporal coherence
