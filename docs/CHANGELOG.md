# Changelog

## 2026-09-18 — Fetcher correctness, P0.1, and the branch merge

Two bugs in the article fetcher, the first gate of `docs/BUILD_PLAN.md`, and the
merge of `development` into `main`.

### The headline

Article extraction across the corpus sat at **8.5%**. That was never a property
of the web — it was two bugs stacked on each other. Fresh fetches now come back
at **48–71%** depending on sample, and GATE 0.1 clears at **71.1%** against its
40% threshold.

---

### 1. The fetcher truncated every article to its first chunk

`pipeline/article_fetch.py` read response bodies with
`await response.content.read(max_response_bytes + 1)`.

aiohttp's `StreamReader.read(n)` does not read `n` bytes. For `n >= 0` it waits
only until the buffer is non-empty and returns whatever is already there; only
`n < 0` loops to EOF. Every stored article was therefore cut off after roughly
its first TCP segment.

Measured on the live corpus: **86% of stored HTML had no closing `</html>`**.

| Stored HTML | extracted | failed | success |
|---|---|---|---|
| Complete | 42 | 14 | **75%** |
| Truncated | 64 | 280 | 18.6% |

The same line silently disabled the `response_too_large` cap, which only ever
measured one chunk.

Fixed by streaming to EOF with the cap enforced per chunk, so oversized
responses abort mid-stream instead of after buffering.

**Why it shipped:** the existing fetch mocks returned the whole body from a
single `read(limit)` call, asserting an API contract aiohttp does not honour.
The tests encoded the bug as correct behaviour. They now model a real chunked
stream.

Stored HTML from before this fix is incomplete on disk and cannot be repaired by
reprocessing — it has to be refetched.

### 2. Exponential backtracking hung the fetcher outright

`_normalize_extracted_block` trimmed pipe runs off block edges with
`^(?:\s*\|\s*)+` and `(?:\s*\|\s*)+$`. Both backtrack exponentially: `\s*` can
match empty, so a whitespace-padded pipe run has exponentially many ways to
split before the anchor fails.

Measured on the real function: 14 pipes 0.5s, **18 pipes 39 seconds**, roughly
4x per additional pipe.

`Home | News | Sport | ...` is exactly that shape, and trafilatura runs with
`include_tables=True`, so nav bars and table rows arrive as single pipe-heavy
blocks. `extract_article` is called synchronously inside `fetch_once`, so one
bad block freezes the entire event loop — every in-flight request stalls, no row
reaches a terminal status, and the process sits at 100% CPU with its DNS threads
parked and Postgres idle.

This was dormant until fix #1. Fragments cut off after one TCP chunk rarely
contained a whole nav bar; full pages always do. Fixing the truncation is what
exposed it.

Replaced with a linear character strip. Interior pipes are untouched and
`normalize_text` already handled the whitespace-only edges the old pattern
skipped, so output is unchanged.

### 3. P0.1 — article fetchability, GATE 0.1 cleared

New `pipeline/10_probe_fetchability.py`. Samples round-robin across all 2,073
domains so no single outlet dominates, fetches through the production fetcher so
it measures what the pipeline will actually receive, and records the result in
`docs/measurements/fetchability.md` per the gate procedure.

On 1,000 URLs:

| Metric | Result |
|---|---|
| Success rate | **71.1%** (threshold 40%) |
| Top-10 domains | 100% |
| Long tail | 70.8% |
| Paywalled | 4.6% |
| Median extracted length | 3,688 chars |

Two results that bear on later phases:

- The corpus is effectively **monolingual English** — 700 of 711 extracted
  articles. P2.1 needs no multilingual handling.
- **Bot-walls are now the ceiling** at 15.3% blocked, ahead of
  `insufficient_text` at 8.7%.

Language detection uses the native `<html lang>` attribute with Unicode script
ranges as fallback, rather than adding a dependency. The probe is resumable and
reruns in ~1s from cache.

### 4. `development` merged into `main`

The plan assumes one tree, but the article pipeline lived on `development` while
the dashboard and its causal scoring lived on `main`. P0.2 needs both.

Conflicts and how they were resolved:

- **`requirements.txt`** — kept main's runtime-only set. development's root file
  had grown to include pandas, torch, transformers and spacy, which is what
  `CLAUDE.md` forbids: the root file is the Vercel bundle. Pipeline deps the code
  actually imports moved to `pipeline/requirements.txt`.
- **`frontend/index.html`** — the branches had unrelated apps under one name.
  main's "GDELT INTEL" dashboard keeps `index.html` because `app.py` and Vercel
  serve it; development's "India // Unrest Index" viewer moved to
  `frontend/viewer.html`, with `08_run_viewer.py` and `test_frontend.py`
  repointed.
- **`README.md`** — kept development's uv/bun install, added a dashboard
  section, corrected the claim that the dashboard is archived.

Git additionally detected development's archival of the old exploration as a
*rename* of main's current `app.py`, and staged the live 1,116-line dashboard
into `archive/legacy-exploration/`. That would have emptied the repo root and
broken the deploy while looking like a clean automatic merge. `app.py`,
`pipeline/01`–`04` and `pipeline/utils.py` are restored at root; the archive
keeps development's older 493-line copy.

`vercel.json` gained excludes for `archive/**`, `docs/**`, `tests/**`, the
lockfiles and the P0.1 evidence — none are read at runtime, and the merge would
otherwise have dragged about 3MB of dead weight into the serverless function.

### Deployment impact

`app.py`, `frontend/index.html`, `vercel.json` (excludes only) and
`test_app.py` are byte-identical to the previously deployed revision.
`requirements.txt` differs by two comment lines; the three pinned dependencies
are unchanged. `out/step2_causal_filtered.parquet`, the only file the API reads
at runtime, is untouched. The dashboard is unaffected by this release.

### Operational notes

`pipeline/refetch_all.sh` drives the ingest in bounded batches so a stall costs
one batch rather than the whole run. A full-corpus refetch of ~612k documents
runs at roughly 25 rows/sec.

Note that `blocked` rises to ~33% under sustained refetch versus 15.3% on the
one-shot probe — refetching the same hosts hard trips bot-walls the probe did
not. If it climbs further, loosen the per-host pacing.

### Tests

45 pipeline tests plus `test_app.py`, all passing. The default
`ARTICLE_DATABASE_URL` points at :5432; the local Postgres serves :5433, so
export it before running the Postgres-backed tests.
