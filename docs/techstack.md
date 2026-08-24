# Decoding the Domino Effect — Technology Stack

## Purpose

This document records the technology choices for the first local, batch-oriented version of **Decoding the Domino Effect**.

The immediate goal is reproducible research on a single machine. The stack keeps data contracts portable, but cloud deployment and realtime ingestion are intentionally deferred.

## Decision summary

| Area | Choice | Reason |
|---|---|---|
| Repository | Polyglot monorepo | Keeps Python research services and TypeScript applications versioned together. |
| Python | Python 3.11 | Stable compatibility target for scientific Python, PyTorch, and NLP packages. |
| Python dependencies | `uv` + `pyproject.toml` | Fast, reproducible environments with a lockfile. |
| TypeScript runtime | Bun 1.3.14 | Package management and runtime for the Hono gateway and frontend tooling. |
| TypeScript workspace | Bun workspaces | Lightweight workspace support without introducing a larger monorepo platform. |
| Data processing | DuckDB + PyArrow | Efficient SQL and columnar processing over Parquet on one machine. |
| Batch orchestration | Prefect local server + worker | Provides visible, resumable batch flows without building a streaming system. |
| Normalized source of truth | Parquet + JSON manifests | Immutable, portable artifacts with explicit provenance. |
| Graph database | Neo4j | Cypher-based event path queries and a clear path to managed Neo4j later. |
| Vector database | Qdrant in Docker | Local semantic retrieval with metadata filtering and a service boundary. |
| Backend API | Hono gateway + FastAPI core | TypeScript-facing APIs with Python-owned research and graph semantics. |
| API contract | REST + OpenAPI + Zod | Inspectable cross-language contracts and typed frontend validation. |
| Frontend | React + Vite + TypeScript | Focused client application without requiring a server-rendered framework. |
| Frontend data | TanStack Router + TanStack Query | Typed routing and server-state caching. |
| Graph UI | Cytoscape.js | Graph-native layouts, path highlighting, and interaction support. |
| UI system | Tailwind CSS + shadcn/ui | Accessible primitives with control over the research dashboard design. |
| NLP | spaCy + Hugging Face Transformers | Rule-based linguistic features plus local semantic/NLI models. |
| ML runtime | PyTorch | Standard Hugging Face inference and experimentation path. |
| Initial embeddings | `all-MiniLM-L6-v2` | Compact English model suitable for CPU-compatible local batch runs. |
| Observability | OpenTelemetry + Jaeger | Local traces for API requests and Prefect pipeline runs. |
| Python quality | Ruff + mypy | Fast linting/formatting plus static type checking. |
| TypeScript quality | Biome | One fast formatter and linter. |
| Testing | pytest + Vitest + Playwright | Covers Python logic, TypeScript services, and full user workflows. |
| CI | GitHub Actions | Runs cross-language quality checks and tests consistently. |

## Service boundaries

```text
React/Vite frontend
        |
        v
Hono + Zod gateway
        |
        v  REST/OpenAPI
FastAPI Python core
        |
        +--> DuckDB / Parquet
        +--> Qdrant
        +--> Neo4j
        +--> Prefect-managed batch flows
```

The frontend communicates only with Hono. Hono owns the frontend-facing API shape, but it does not own causal semantics or issue Cypher directly.

The Python core owns:

- GDELT ingestion and normalization.
- Event and protest-episode construction.
- NLP and semantic inference.
- Causal candidate retrieval and verification.
- Neo4j projection and graph queries.

FastAPI publishes the internal OpenAPI contract. A generated TypeScript client and Zod validation keep the Hono gateway aligned with the Python service.

## Local infrastructure

Docker Compose will eventually provide the local services:

- Neo4j.
- Qdrant.
- Prefect server.
- Prefect worker.
- Jaeger.
- Python core.
- Hono gateway.

The React application can run through Bun/Vite during development.

Suggested ports:

| Service | Port |
|---|---:|
| Vite frontend | 5173 |
| Hono gateway | 3000 |
| FastAPI core | 8000 |
| Neo4j browser | 7474 |
| Neo4j Bolt | 7687 |
| Qdrant | 6333 |
| Prefect | 4200 |
| Jaeger UI | 16686 |

## Data and model dependencies

Python runtime dependencies are declared in `pyproject.toml` and mirrored in `requirements.txt` for pip-based environments.

The locked Python environment includes:

- DuckDB, PyArrow, Polars, and pandas for data work.
- FastAPI, Uvicorn, Pydantic, and Pydantic Settings for the Python service.
- Neo4j and Qdrant clients.
- Prefect for batch orchestration.
- spaCy, Transformers, and PyTorch for local NLP/NLI processing.
- OpenTelemetry packages for tracing.

The TypeScript workspace manifest contains the planned Hono, Zod, React, TanStack, Cytoscape, Vite, Tailwind, Biome, Vitest, and Playwright dependencies. Application packages will be added when implementation begins.

## Reproducibility policy

- Use `uv.lock` for Python dependency resolution.
- Use `bun.lock` for TypeScript dependency resolution.
- Pin the Bun runtime version in `package.json`.
- Keep Python compatible with `>=3.11,<3.15`.
- Keep raw GDELT data immutable.
- Store normalized data as Parquet.
- Store run configuration and provenance in JSON manifests.
- Keep full retrieved article text in private local storage only.

Recommended setup commands:

```bash
# Python environment
uv sync

# TypeScript workspace
bun install
```

For a pip-only machine:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Deliberately deferred

The following are not part of the current setup:

- Cloud provider selection.
- Kafka or another stream broker.
- Realtime ingestion.
- Public deployment.
- Authentication.
- A separate model-serving service.
- Graph Data Science algorithms in Neo4j.
- An LLM or autonomous agent.
- External economic or political datasets.

The first implementation remains a local, batch-oriented research system.
