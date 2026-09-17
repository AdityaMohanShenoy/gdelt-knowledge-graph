# GDELT Knowledge Graph — notes for Claude

See README.md for what the project does. These are the things that aren't obvious
from the code and that have already caused bugs.

`docs/BUILD_PLAN.md` is the phased plan for building out the full causal knowledge
graph — numbered tasks with acceptance criteria, meant to be executed one at a time.

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

## Causal Evidence scoring has invariants that look like cruft

The tab scores candidate causes across six channels (`/api/causal/score`). Four
things there look like obvious simplifications and are not.

**Presence means a spike day, not any day.** A root code counts as present on a day
only when its count exceeds its own 75th percentile. Raw presence is useless at day
granularity — common codes fire nearly every day in a busy country, so sufficiency
came out near 1.0 for every pair and nothing discriminated.

**A channel with no data reports `available: false`. It never scores 0.** The
contradiction channel needs article text this repo does not ship. Scoring it 0 would
make "nobody denied it" and "we never looked" identical, which is the exact failure
the grading exists to prevent.

**Actor tokens are weighted by corpus rarity, not string length.** `UNITED` appears
in 10.9% of events and `POLICE` in 0.9%, but `UNITED` is the longer string, so length
ranks precisely the wrong one first. `_token_idf` counts document frequency in one
scan; `_pick_probes` drops `df == 0` tokens (maximum idf, can never match anything)
and anything above `ACTOR_MAX_SHARE`. Tokens are interpolated into SQL, so
`_actor_tokens` keeps alphanumerics only.

**One event type is one candidate.** The same type recurring on five days is one
cause seen five times, so candidates are deduplicated by root code at their
strongest lag.

Two things the scoring does not handle, both deliberate and both worth knowing
before quoting a number:

Where cause and effect share a root code, their spike days are the same set, so
sufficiency and necessity come out identical by construction and the contrastive
channel measures recurrence rather than a distinct relation. The trace flags this;
the weighting does not discount it.

The fusion weights are fixed and illustrative. In the design they are fitted on
labelled decisions and this repo has no labelled set, so no confidence the tab
shows is calibrated. The UI says so. Don't quote them as accuracy.

## Check

    pip install -r requirements.txt
    python test_app.py     # asserts the NULL guard + hits every endpoint

## Deploy

Push to `main` → Vercel auto-deploys to https://gdelt-knowledge-graph.vercel.app.
PRs get preview deployments. DuckDB is pinned to 1GB/1 thread when `$VERCEL` is set,
because it otherwise sizes itself from the host's /proc/meminfo and gets OOM-killed.
