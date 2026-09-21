# Changelog

## 2026-09-21 — P2.3: the annotation tool, pulled forward

`pipeline/14_run_annotator.py` plus `frontend/annotate.html`. Scheduled in
Phase 2, built now because labelling is the actual bottleneck: P3.5 showed the
scorer's `pattern` grade has no discriminative power, and the fix (P3.4
calibration) cannot start without labels.

    python pipeline/14_run_annotator.py seed --targets 40
    python pipeline/14_run_annotator.py serve --port 8200

**The machine's score is hidden by default.** P3.4 measures calibration by
comparing machine strength against the human's, which is worth nothing if the
human read the machine's number first. Press `m` to reveal it deliberately.
This is the one design decision the brief really turns on.

A local server rather than routes in `app.py`, which the plan assumed. `app.py`
is the Vercel function, CLAUDE.md holds it to one runtime data source, and it
could not reach this Postgres anyway. Same shape as `08_run_viewer.py`.

Seeding writes real evidence-store rows — an `events` row per event, a `claims`
row per pair including ones the scorer would drop, `claim_channels` per channel
— so what gets judged is the record rather than a scratch file. 40 targets
produced 3,642 claims.

The queue serves each target's **strongest unjudged candidate**, not the next
claim by id. At ~90 candidates per target, id order would exhaust one event
before the next was ever seen; P2.4 wants ~600 pairs across ~500 seeds, so
coverage has to spread across targets.

Interface: the lag axis is the hero — cause left, effect right, the day gap as
real horizontal distance, since that is the comparison every judgement turns on.
System serif for evidence, system sans for chrome, no webfonts so it works
offline. Keyboard-first: `a`/`e`/`r`, `1`-`8` for rejection reasons, `m` for the
machine score.

Two bugs found while wiring it up. `best_time` is TIMESTAMPTZ, so seeding a bare
date was read as local midnight and stored as 18:30 UTC the day before — every
event sat on the wrong UTC day. GDELT days are UTC days and are now stored as
such. And `ON CONFLICT` cannot infer a partial unique index, so
`events.external_id` uses a plain one.

`httpx` was declared as a dev dependency but never installed in this venv, which
is why `tests/test_article_api.py` had been silently skipping all along. It is
installed now and those 3 tests pass, alongside 6 new ones covering queue
spread, the machine value surviving beside the human one, rejection requiring a
taxonomy reason, and the rejected set staying queryable.

Incidentally confirmed the append-only discipline is real: clearing test
annotations with DELETE was refused by the trigger.

## 2026-09-21 — P3.5: negative controls, and GATE 3.5 fails

`pipeline/31_negative_controls.py` scores pairs that cannot be causal and
reports how often the fusion calls them one. Three arms, all through the same
code path as the live endpoint: the real 7-day window, a `shuffled` window drawn
from elsewhere in the year, and a `future` window after the target that cannot
be its cause.

**The gate fails, and the headline number hides it.** False-positive rate is a
reassuring 4.0% shuffled and 3.1% future. But the number that matters is how
much more often a grade fires on real pairs than on random ones:

| Grade | real / shuffled |
|---|---|
| confirmed | never fires on shuffled |
| reported | never fires on shuffled |
| **pattern** | **0.95×** |
| weak | 0.98× |

`pattern` fires *slightly less often* on real pairs than on shuffled ones. That
grade exists precisely to catch links Stage 1 never saw, and it is finding them
just as readily in randomness. It is reading corpus structure: `prior` and
`contrastive` are country-level type-pair statistics that know nothing about the
specific pair in front of them.

The clean separation in `confirmed` and `reported` is not a counter-argument.
Both are carried by the `documented` channel, which is empty by construction in
both control arms, so their gap is guaranteed rather than measured. Reporting it
as evidence of a working scorer would be circular.

Per the plan, Phase 4 does not proceed on this. The fix belongs in P3.2 — a
textual channel that reads the specific pair — and P3.4, weights fitted on
labelled decisions rather than the illustrative ones in use now. Both of which
this result reclassifies from "planned" to "load bearing".

`scoring.candidate_groups` was extracted from `app.py` so the control scores the
same query the endpoint does rather than a copy that could drift. Golden capture
still hashes identically (`a07087a522f6d601`); `app.py` is down to 783 lines.

## 2026-09-21 — P3.1: scoring out of app.py

`app.py` goes from **1,116 to 796 lines**. The Causal Evidence scoring now lives
in `scoring/`: `config.py`, `sql.py`, `retrieval.py`, `channels/`, `fuse.py`,
`grade.py`.

A pure move, and the acceptance criterion is behavioural rather than structural.
A golden capture of 46 responses — `/api/causal/seeds`, `/api/causal/matrix` and
`/api/causal/score` across three countries and twelve seeds each, plus empty,
missing, malformed and bad-country inputs — hashes identically before and after:
`sha256 a07087a522f6d601`. `test_app.py` passes unchanged.

`num`, `safe` and `rows` moved to `scoring/sql.py` so the package never imports
the app. `app.py` re-exports `_token_idf`, `_pick_probes`, `ACTOR_PROBES` and
`ACTOR_MAX_SHARE`, which `test_app.py` reaches for directly; keeping one import
surface was preferable to editing the deploy gate during a refactor that is
supposed to change nothing.

`scoring/channels/` holds the six channels as `score()` and `explain()`. P3.2
and P3.3 add `textual.py` and `contradiction.py` beside them, which is why the
package shape the plan specified is worth having before the channels get real.

8 new tests lock the CLAUDE.md invariants where they now live: an unavailable
channel is not a zero, probe tokens are rare and their ties break
deterministically, stop actors carry no signal, contradiction is the only
negative weight, the logistic saturates without overflowing, and the grade
ladder follows its documented rules.

## 2026-09-21 — The extractor keeps the publication date

trafilatura returned `date`, `language` and `author` on every extraction and the
extractor kept only title and text. `ExtractionResult` now carries
`published_at`, `article_documents` has a `published_at` column, and both the
fetch path and the offline reprocess persist it.

**A bound is required, not optional.** Unbounded, htmldate falls back to a
page's last-modified or render date. Measured on stored articles: **11 of 74
dates were the crawl year rather than publication** — real 2024 stories reading
as 2026, one of them with `/20240913/` in its own URL. `original_date=True` did
not help. Passing `max_date` recovered the true 2024 date for 10 of those 11 and
dropped the last: 63 correct rose to 73, and 11 wrong fell to 0. A wrong
publication date is worse than a missing one for anything temporal, so the
extractor takes a `max_date` and the pipelines expose `--max-article-date`.

`published_at` is a `datetime.date`, not the ISO string trafilatura hands back:
the column is a DATE, and a malformed value now becomes None instead of failing
a whole batch.

`EXTRACTOR_VERSION` is bumped to `v3`, and the bump is load bearing.
`09_reprocess_articles` only promotes rows whose `extractor_version` differs, so
without it a backfill would silently skip every already-extracted row.

Measured on a 300-row backfill: 71.7% carry a date, 94% of those land in 2024.
The residual 6% (a pair in 2011, five in January 2025) is left alone
deliberately. A second bound inside the extractor would be another guess; the
principled check is against the GDELT event day when `sources` is loaded, which
is where the event date is actually known.

`language` is **not** captured. trafilatura populated it in 0 of 60 stored
articles — it is inert without `py3langid`, which is not installed. The
`<html lang>` heuristic in `probe_branching`'s sibling P0.1 probe remains the
better source. `author` is populated in roughly half of pages but has no
consumer in the plan.

Backfilling the existing corpus needs no refetching — the stored HTML is on
disk. Run one promote pass once the refetch finishes:

    python pipeline/09_reprocess_articles.py promote --max-article-date 2025-01-31

## 2026-09-21 — P1.1: the evidence store

`store/schema.sql` and `store/db.py`. `python -m store.db --init` applies it
idempotently; `--check` reports row counts per table.

Nine tables per the plan: `sources`, `entities`, `events`, `mentions`,
`conditions`, `claims`, `claim_channels`, `annotations`, `build_versions`.

Two deliberate departures from the plan's letter:

**Postgres, not SQLite.** The plan says "SQLite locally". But Postgres is already
running with the 640k-row article corpus; P2.4 wants four annotators working
concurrently, which is the plan's own stated trigger for choosing Supabase over
SQLite; and SQLite would put the evidence store in a different database from the
articles it references — no foreign keys across them, and two backup stories.
The open decision in the plan is therefore settled by what is already deployed.
The DDL stays portable.

**`sources` is its own table, not a view over `article_documents`.**
`article_documents` is a mutable work queue with statuses, leases and retries.
The evidence store wants the settled record, and the plan requires `sources` to
be append-only, which a view over a mutable queue cannot be. `sources` holds the
metadata and references the article row for its text.

Append-only is enforced by trigger on `sources`, `mentions` and `annotations`,
not left as a convention. A correction is a new row that supersedes, so what was
believed when survives — that is what makes P5.2 a recompile rather than a
migration. `claims.verdict` stays mutable, since review changes it.

Constraints that encode plan requirements rather than merely documenting them:
rejections carry a reason from P2.3's fixed taxonomy (enforced by CHECK);
`annotations` keeps both `machine_strength` and `human_strength`, since P3.4
measures calibration by comparing them; `claim_channels.available` is a boolean
distinct from a zero score, because absent evidence and evidence of absence are
different inputs to the fusion; rejected claims are retained as the hard
negatives a trained ranker needs.

`sources.published_at` is nullable and currently unpopulated. trafilatura
already returns `date`, `language` and `author` on every extraction and the
extractor discards all of it, keeping only title and text. Recovering it needs
no refetching — the 4.6GB of stored HTML can be reprocessed — but it is P1.3
work, not P1.1.

6 tests: idempotent init, a row round-tripping every table through its real
foreign keys, append-only enforcement on update and delete, mutability of
`claims`, retention of rejected claims, and refusal of a reason-less rejection.

## 2026-09-18 — Separate the two pipeline lineages

`pipeline/` held two unrelated pipelines sharing one number space, with `01`
through `04` appearing twice. `docs/BUILD_PLAN.md` adds `11`, `12`, `20`, `21`,
`30`, `31` and `40`, so the ambiguity was about to get worse.

The corpus pipeline keeps the top level and is now continuous:
`01_build_india_universe` → `09_reprocess_articles` → `10_probe_fetchability`,
with the plan's future scripts extending the same run.

The dashboard lineage moved to `pipeline/dashboard/`: the country filter, causal
filter, URL validation and Neo4j export that produced
`out/step2_causal_filtered.parquet`. It is a finished, rarely re-run concern that
shares no code with the corpus pipeline — the four scripts have no cross-imports,
so the move needed no rewiring.

Also removed `pipeline/article_extractor 2.py`, the obsolete stdlib extractor.
Nothing imported it, and it scored 5.6% against the current extractor's 34.9% on
the same corpus. Git history keeps it.

`pipeline/utils.py` moved with the lineage it belongs to. It is currently
imported by nothing and is a deletion candidate once someone confirms the CAMEO
lookups are genuinely unused.

Paths updated in `README.md`, `docs/BUILD_PLAN.md` and the usage strings inside
`04_export_neo4j.py`. `vercel.json` already excluded `pipeline/**`, so the
bundle is unchanged. 45 tests and `test_app.py` pass.

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
