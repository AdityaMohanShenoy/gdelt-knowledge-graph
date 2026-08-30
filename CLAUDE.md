# GDELT Knowledge Graph — notes for Claude

See README.md for what the project does. These are the things that aren't obvious
from the code and that have already caused bugs.

## Runtime reads exactly one file

`app.py` has a single `read_parquet`, pointed at `out/step2_causal_filtered.parquet`
(63MB, committed). Nothing at runtime touches `out_parquet/` or `out/step1_*` —
those are gitignored and are **not present in a cloud sandbox**. Don't try to
re-run the pipeline there; it needs ~1GB of raw data that only exists locally.

Everything downstream of step 2 (dashboard, all endpoints, tests) runs anywhere.

## Never re-add pandas

It was 186MB of Vercel's 250MB bundle limit, serving 9 `.df()` calls. Queries use
`_rows()` (dicts) or raw `fetchall()`/`fetchone()`. Deps are split: root
`requirements.txt` is runtime only; `pipeline/requirements.txt` has polars/aiohttp/neo4j.

## SQL NULL arrives two different ways

`AVG()` over zero rows is NULL. It reaches you as `None` from `fetchone()` tuples
and as `NaN` from `_rows()` dicts. The self-comparison guard `x == x` catches NaN
but **passes `None` straight through** into `float(None)`. Use `num()` for every
numeric that could be an aggregate. Don't write a new `== ` guard.

## Endpoints must be deterministic

Responses are compared byte-identical against saved goldens. Any `ORDER BY` over a
column with ties needs a tiebreaker, and `ROW_NUMBER() OVER (...)` needs a fully
ordered `PARTITION BY`. An untied sort silently returns different rows per run.

## Check

    pip install -r requirements.txt
    python test_app.py     # asserts the NULL guard + hits every endpoint

## Deploy

Push to `main` → Vercel auto-deploys to https://gdelt-knowledge-graph.vercel.app.
PRs get preview deployments. DuckDB is pinned to 1GB/1 thread when `$VERCEL` is set,
because it otherwise sizes itself from the host's /proc/meminfo and gets OOM-killed.
