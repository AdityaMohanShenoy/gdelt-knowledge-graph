# Build plan — two-stage causal knowledge graph

Target: a **causal claim graph** over 2024 India protest events. Every link carries
a grade saying what *kind* of evidence supports it and a confidence saying *how
much*, and every number is re-derivable from stored evidence.

This plan is written to be executed task by task from a CLI session. Read
`CLAUDE.md` first — its invariants bind everything here.

---

## How to drive this from the CLI

Tasks are numbered `P<phase>.<n>`. Each names its goal, the files it touches, and
an acceptance test. A session should be able to take one task and finish it.

    claude
    > read docs/BUILD_PLAN.md and do P0.1
    > P1.2 is failing on rate limits, fix it and re-run the acceptance check

Rules for whoever executes this:

- **One task per branch/PR.** Tasks are sized to be reviewable alone.
- **Acceptance criteria are not optional.** A task is done when its check passes,
  not when the code looks right.
- **Gates are hard stops.** A gate that fails changes the plan; do not route
  around it. Record the measurement in `docs/measurements/` and re-scope.
- **`python test_app.py` must pass before every push.** Existing endpoints are
  compared byte-identical; see CLAUDE.md on determinism.

---

## Where we are now

Already built and on `main`:

| Thing | State |
|---|---|
| `out/step2_causal_filtered.parquet` | 1,120,666 GDELT events, 2024, top-10 countries |
| `pipeline/dashboard/01`–`04` | country filter, causal filter, URL validation, Neo4j export |
| Causal Evidence tab | working demo: 4 of 6 channels, metadata only, full derivation trace |
| `app.py` scoring | `_causal_matrix_rows`, `_token_idf`, `_pick_probes`, `causal_score` |

What does **not** exist yet, and is what this plan builds:

- No article text. `SOURCEURL` only.
- No atomic events — one GDELT row is still treated as one event.
- No canonicalization. Duplicates are not merged.
- No human annotation, so no labelled set, so **no calibrated confidence**.
- No `Condition` nodes, so structural causes are unrepresentable.
- No materialized graph — the demo scores pairs at request time.

Honest total: **Phases 0–6 is roughly 17–20 weeks** at the stated team size. See
*Cut lines* at the end before committing to all of it.

---

## Phase 0 — Measure before committing

Three numbers nobody has. Each can invalidate a later phase, so they come first.
Budget: 1–2 weeks.

### P0.1 — Article fetchability

**Goal.** Find out what fraction of 2024 `SOURCEURL`s are still retrievable.
Everything text-dependent in Phase 2 rests on this.

**Build.** `pipeline/10_probe_fetchability.py`

- Sample 1,000 URLs from the parquet, **stratified by domain** so the result isn't
  dominated by whichever outlet published most.
- For each: fetch with a real user agent and a timeout; record HTTP status, final
  URL after redirects, byte size, detected language, and a paywall guess
  (`<meta name="robots" content="noarchive">`, known paywall markers, body under
  ~500 words with a subscribe form).
- Resumable: keep a cache keyed by URL so a rerun skips completed work.
- Write `out/fetch_probe.json` and a human summary to
  `docs/measurements/fetchability.md`.

**Accept when.** The summary reports overall success rate, rate by domain tier
(top-10 domains vs long tail), and paywall share — and a rerun completes in
seconds from cache.

> **GATE 0.1.** Success below **40%** means Stage 1's text channels will starve.
> Do not proceed to P1.2 at full scope. Re-scope to either (a) a narrower seed set
> concentrated on fetchable domains, or (b) metadata-only Stage 2 with Stage 1
> limited to what can be read. Record the decision in the measurements file.

Note: `pipeline/dashboard/03_validate_urls.py` already does liveness checking. Reuse its
cache format rather than inventing a second one.

### P0.2 — Real branching factor

**Goal.** The annotation budget depends entirely on how many parents an event
actually has. Nobody has measured it.

**Build.** No new code required — use the existing `/api/causal/score` as a
retrieval aid and record by hand.

- Take 20 India 2024 protest events.
- For each, expand causes to depth 3. Record: candidates retrieved, candidates a
  human would accept, at each depth.
- Write `docs/measurements/branching.md` with mean and spread.

**Accept when.** The file states a mean branching factor with a range, and
projects total edges for a 500-seed run at depth 3.

> **GATE 0.2.** Branch factor above **4** projects to >100k edges at depth 3.
> That is not annotatable by hand at any realistic team size, and confirms the
> calibration approach in P3.4 is mandatory rather than optional.

### P0.3 — Taxonomy discovery

**Goal.** Find out which relation types annotators can actually tell apart,
*before* committing months of labels to a taxonomy.

**Build.** A 150-pair pilot.

- Present pairs with evidence; annotators write a **free-text** mechanism
  description. No predefined labels.
- Cluster the descriptions. Measure which distinctions survive inter-annotator
  agreement ≥ 0.6.
- Write `docs/taxonomy.md` with the committed type list and the rejected
  distinctions with their agreement scores.

**Accept when.** `docs/taxonomy.md` names the final types and justifies each
against measured agreement.

> **Expectation, not a gate.** The starting seven (`TRIGGERS`, `MOTIVATES`,
> `MOBILIZES`, `ENABLES`, `ESCALATES`, `PROMPTS_RESPONSE`, `CONTRIBUTES_TO`)
> will likely collapse to four or five. `TRIGGERS`/`ESCALATES` differ only in
> whether the effect already existed; `MOTIVATES`/`CONTRIBUTES_TO` differ mainly
> in annotator confidence, which belongs in the strength field.

---

## Phase 1 — Evidence store

An append-only store, so that later phases can be recompiled rather than
rebuilt. Budget: 2–3 weeks.

### P1.1 — Schema

**Goal.** One place all evidence lands, never rewritten.

**Build.** `store/schema.sql`, `store/db.py`

Tables:

| Table | Holds |
|---|---|
| `sources` | url, published_at, fetched_at, content_hash, storage paths, fetch_status |
| `mentions` | one event as described in one article, with `evidence_start`/`end` |
| `events` | canonical events, with `best_time`, `time_range`, `time_confidence` |
| `conditions` | persistent states with `valid_from`/`valid_to` (Phase 4) |
| `entities` | resolved actors and places |
| `claims` | one scored candidate pair, **including rejected ones** |
| `claim_channels` | per-channel scores and raw inputs for a claim |
| `annotations` | every human accept/edit/reject, with reason and annotator |
| `build_versions` | config hash → graph version |

SQLite locally; keep DDL Postgres-compatible so Supabase remains an option.

**Discipline: evidence tables are append-only.** No `UPDATE` on `sources`,
`mentions`, `annotations`. Corrections are new rows superseding old ones. This is
what makes P5.2 a recompile rather than a migration.

**Accept when.** `python -m store.db --init` creates the schema idempotently, and
a test inserts and reads back one row of each table.

### P1.2 — Article fetcher

**Build.** `pipeline/11_fetch_articles.py`

- Async, concurrency capped **per domain** (not globally) so one slow host doesn't
  stall the run and no host gets hammered.
- Respect `robots.txt`. Real user agent. Exponential backoff on 429/503.
- Raw HTML to disk under `out/articles/` (**add to `.gitignore`**), path recorded
  in `sources`.
- Fully resumable — rerunning processes only `fetch_status IS NULL`.

**Accept when.** Interrupting mid-run and restarting processes only the remainder,
and `sources` row count matches files on disk.

### P1.3 — Text extraction

**Build.** `pipeline/12_extract_text.py`

- `trafilatura` (fallback `readability-lxml`) → main article text, stripped of
  nav/ads/comments.
- Store cleaned text; compute `content_hash` over the cleaned text so two URLs
  serving the same article collapse to one.
- Record extraction failures rather than dropping them silently.

**Accept when.** A report gives extraction success rate and duplicate rate, and
spot-checking 10 outputs shows clean article body with no boilerplate.

> **Dependency note.** `trafilatura`, `aiohttp`, `spacy` go in
> `pipeline/requirements.txt`, **never** the root one. See CLAUDE.md — the root
> requirements file is runtime-only and the Vercel bundle has no headroom.

---

## Phase 2 — Stage 1: Verified Core

The team's original plan, bounded to the seed set. Produces **two** outputs: a
high-precision core graph, and the labelled decisions that calibrate Stage 2.
Budget: 4–5 weeks.

### P2.1 — Atomic event extraction

**Goal.** One article → several atomic events, each pointing at the exact span it
came from.

**Build.** `pipeline/20_extract_events.py`

- spaCy dependency parse → subject-verb-object triples, filtered to
  event-like predicates.
- Map to CAMEO root codes with a rule table seeded from
  `data/reference_lookups/`.
- Every mention records `source_id`, actors, action, target, location,
  `event_time`, `event_type`, `evidence_start`, `evidence_end`, `confidence`.
- Store the structured fields; **do not** store a prose sentence. Human-readable
  text is generated from fields at display time.

**Accept when.** On 20 hand-checked articles, every extracted mention's evidence
span, when sliced out of the cleaned text, contains the event it claims.

### P2.2 — Canonicalization

**Goal.** Many mentions of one real event → one canonical event.

**Build.** `pipeline/21_canonicalize.py`

- Block on (date bucket, location, event type) to avoid all-pairs comparison.
- Within a block, score on actor overlap, action similarity, time proximity.
- Auto-merge above a high threshold; queue the middle band for human review;
  never auto-merge below.
- Canonical event records `supporting_sources`, and `best_time` with its
  confidence and possible range.

**Accept when.** A known multi-outlet event collapses to one node, and the report
gives merge counts by tier (auto / reviewed / rejected).

> **Why this is load-bearing.** Without it the strongest "causal" links will be
> the same event reported twice. It also makes corroboration meaningful — counting
> independent outlets requires knowing which reports are the same story.

### P2.3 — Annotation tool

**Goal.** Humans judge; they do not search.

**Build.** New routes in `app.py` plus `frontend/annotate.html`.

The screen shows: target event, one candidate cause, the primary evidence span in
context, other supporting spans, a suggested relation type, a suggested strength,
and the full article on demand. Actions: **Accept / Edit / Reject**.

- Reject requires a reason from the fixed taxonomy: `NO_CAUSAL_EVIDENCE`,
  `TEMPORALLY_INVALID`, `WRONG_EVENT_MATCH`, `DUPLICATE_EVENT`, `CORRELATED_ONLY`,
  `INSUFFICIENT_EVIDENCE`, `WRONG_DIRECTION`, `OTHER` + free text.
- Store **both** the machine-suggested strength and the human's final value. Never
  overwrite the machine value — P3.4 needs both to measure calibration.
- Every action writes an `annotations` row with annotator id and timestamp.

**Accept when.** A full accept/edit/reject cycle persists correctly, and rejected
candidates are queryable as a set.

> **Rejections are the most valuable output here.** They are the near-misses — the
> hard negatives that make a trained ranker useful. A model trained only on
> accepts plus random negatives learns nothing, because random negatives are
> trivially easy.

### P2.4 — Annotation run

**Goal.** ~600 judged pairs over ~500 India 2024 protest seeds.

- **Bounded.** Seeds only; no unlimited recursion. Recursion comes in P5.3, driven
  by the calibrated scorer rather than by hand.
- One primary annotator per pair; **25% double-annotated**, rotating pairs across
  the four annotators.
- Measure inter-annotator agreement and resolve disagreements by discussion.
  Record the resolution, not just the outcome.

**Accept when.** ≥600 judged pairs exist, IAA is reported per relation type, and
every event has an explicit search status: `PARENTS_FOUND`,
`NO_SUPPORTED_PARENT_FOUND`, `NOT_YET_REVIEWED`, `UNVERIFIABLE`.

> Search status matters more than it looks. Without it, "we looked and found
> nothing" and "nobody has looked yet" are the same empty result, and they mean
> opposite things.

---

## Phase 3 — Stage 2: full six-channel fusion

Upgrade the demo scorer into the real one, and calibrate it on Phase 2's labels.
Budget: 3 weeks.

### P3.1 — Refactor scoring out of `app.py`

**Goal.** `app.py` is ~1000 lines with scoring inline. Split before adding to it.

**Build.** `scoring/` package — `channels/`, `fuse.py`, `grade.py`.

- Move `_causal_matrix_rows`, `_matrix_index`, `_token_idf`, `_pick_probes` and
  the per-channel logic out of `app.py`.
- **API responses must stay byte-identical.** This is a pure refactor.

**Accept when.** `python test_app.py` passes unchanged, and a golden capture of
`/api/causal/score` before and after the refactor diffs clean.

### P3.2 — Real textual assertion channel

**Goal.** Replace the precursor-link proxy with actual connective detection.

**Build.** `scoring/channels/textual.py`

- Find sentences mentioning both events (resolved entities + action match).
- Detect causal connectives over the dependency parse. Score by **directness**:
  explicit causal (`because of`, `caused by`) > explicit response (`in response
  to`, `protesting against`) > temporal-implicative (`following`, `in the wake
  of`) > bare adjacency.
- Check direction — a sentence establishing B→A scores zero for A→B.
- Optionally train a classifier on PDTB `Contingency.Cause` relations.

**Accept when.** On a hand-labelled set of 100 sentences, precision and recall are
reported per directness tier.

### P3.3 — Contradiction channel

**Goal.** The channel currently reporting `available: false`.

**Build.** `scoring/channels/contradiction.py`

- Same machinery as P3.2, inverted patterns: `unrelated to`, `denied any
  connection`, `not in response to`, `rejected suggestions that`.
- Also temporal contradiction — evidence that B actually preceded A.
- Only this channel gets a negative weight.

**Accept when.** A known denial case scores above zero and measurably lowers the
fused confidence, and the channel's `available` flag flips to `true` only when a
corpus is present.

> Keep the unavailable path working. If the corpus is missing for a pair, the
> channel must still report `available: false` rather than 0 — see CLAUDE.md.

### P3.4 — Calibration

**Goal.** Replace the illustrative weights with fitted ones, and attach a real
error rate.

**Build.** `pipeline/30_calibrate.py` → `scoring/weights.json`

- Stratify Phase 2's judged pairs into 5 confidence bands; fit logistic regression
  on the channel scores.
- **Fit per stratum** (trigger / mobilisation / grievance / structural). A missing
  channel means different things at different depths: in the trigger stratum
  absent text is genuine negative evidence; in the structural stratum it is
  expected and therefore uninformative. One global model applies the trigger
  stratum's penalty to exactly the claims the structural stratum exists to
  rescue.
- Emit a calibration curve per band and precision with confidence intervals per
  grade.

**Accept when.** `scoring/weights.json` is loaded at runtime instead of the
hardcoded `CAUSAL_W`, and the UI stops saying weights are uncalibrated because
they no longer are. Report precision ± CI per grade.

### P3.5 — Negative controls

**Goal.** Find out whether the fusion is fitting artifacts — before building on it.

**Build.** `pipeline/31_negative_controls.py`

- Score shuffled event pairs and known-unrelated pairs.
- Measure the false-positive rate at each grade threshold.

**Accept when.** FPR is reported per grade.

> **GATE 3.5.** A high false-positive rate on shuffled data means the model is
> learning noise. Fix it here. Do not proceed to Phase 4 on top of a scorer that
> finds causes in randomness.

---

## Phase 4 — Conditions and strata

The change that lets structural causes exist at all. Budget: 2 weeks.

### P4.1 — Condition nodes

**Goal.** "Declining farm-gate prices, Punjab, 2022–2024" is not an event. It has
no moment of occurrence, so with only `Event` nodes it has nowhere to live — and
better retrieval cannot fix a missing node type.

**Build.** `conditions` table + relations.

- `condition_id`, `description`, `valid_from`, `valid_to` (may be open),
  `indicator_series` (optional link to numeric data), `evidence`.
- Relations: `Condition --SUSTAINS--> Event`, `Event --CHANGES--> Condition`.
- Seed from text assertions of persistent states, plus any indicator series
  available.

**Accept when.** At least one condition node sustains multiple events across an
interval, and it appears in a causal explanation for each.

### P4.2 — Four strata

**Build.** Stratum assignment + per-stratum windows.

| Stratum | Timescale | Node kind | Dominant channel |
|---|---|---|---|
| Trigger | hours – 3 days | Event | textual assertion |
| Mobilisation | 3 – 21 days | Event | textual + actor continuity |
| Grievance | 3 weeks – 6 months | Event or Condition | contrastive |
| Structural | 6 months+ | Condition | statistical + indicators |

Replaces the single 7-day window (`CAUSAL_WINDOW_DAYS`).

**Accept when.** A long-lag relationship that the 7-day window cannot reach is
recovered and graded.

---

## Phase 5 — Stage 3: reconciliation and graph build

Budget: 2 weeks.

### P5.1 — Combined grades

**Build.** `scoring/grade.py` — grades over both stages:

| Grade | Rule |
|---|---|
| Verified & Corroborated | human approved **and** channels independently agree |
| Verified | human approved, channels neutral |
| **Verified but Unsupported** | human approved, channels find no pattern — **flag for re-review** |
| Pattern-based | Stage 1 never saw it, channels strong |
| Disputed | real support **and** an explicit denial |

**Accept when.** Each grade is populated, and the *Verified but Unsupported* set
is exportable as a review queue.

> This grade is the point of running both stages. It finds links a human accepted
> that the data cannot support — which is where journalistic clichés hide. Neither
> approach alone can produce it.

### P5.2 — Graph materialization

**Goal.** The graph as a **compiled artifact**, not a hand-edited database.

**Build.** `pipeline/40_build_graph.py`

- `build(config)` reads the claims table and emits a versioned graph.
- Config: thresholds, fusion weights version, taxonomy version, window params.
- Record config hash in `build_versions`. Every version reproducible from
  evidence + config.
- Emit both the detailed claim records and a flat edge table for fast traversal.

**Accept when.** Two runs with the same config produce byte-identical output, and
changing one threshold produces a different version without touching the evidence
store.

### P5.3 — Recursive expansion

**Build.** Drive expansion with the calibrated scorer.

- Each accepted parent becomes the next target.
- Stop at: no parent above threshold, depth limit, or 2024-01-01.
- Converge on existing canonical nodes rather than duplicating.
- Instance graph is acyclic for free — every claim requires cause time < effect
  time, so following arrows backwards always moves back in time.

**Accept when.** A seed expands to a multi-level DAG, branches converge on shared
nodes, and a cycle check finds none.

---

## Phase 6 — Query layer and external validation

Budget: 3 weeks.

### P6.1 — Query grounding over event sets

"Why were farmers protesting?" has no single referent — a movement is dozens of
events over months. Ground to a **cluster**, answer over it, offer constituents
for narrowing. Ask for clarification when several clusters match.

### P6.2 — Path ranking and coverage

- Rank by causal strength + query relevance + evidence quality + corroboration.
- **Report coverage with every answer**: what fraction of the target's causal
  support the explanation accounts for.
- Expose the grade filter: *confirmed only* for a defensible claim, *include
  pattern-based* for the fuller picture.

### P6.3 — External validation

Three tests, none of which consults the annotation pool:

1. **Temporal holdout.** Fit on Jan–Sep, test whether recovered causal parents
   improve prediction of Oct–Dec events over a base-rate model.
2. **Documented-chain recovery.** 15–20 events with published post-mortems; the
   2024 farmers' movement has extensive retrospective coverage. Measure recall
   against the chains those accounts establish. Genuine external ground truth,
   about a week to assemble.
3. **Negative controls.** Rerun P3.5 against the final model.

**Accept when.** All three are reported in `docs/validation.md`.

> IAA measures whether annotators agree with each other, never whether they are
> right. Without these three, the system validates itself against itself.

### P6.4 — Dashboard integration

Replace the demo Causal Evidence tab with the real graph. Carry over the
derivation trace — it is the auditability story and it already works.

Also close the gaps the demo left open:

- `/api/causal/matrix` has no UI. The endpoint works and the scorer uses it.
- Global sidebar filters (country / event class / date range) do not reach the
  tab; it has its own country dropdown and always uses the full 2024 range.
- Only the ~12 seed events per country are reachable; the endpoint accepts any id
  but there is no search.
- `app.py` sets `s-maxage=31536000` — a **one-year** CDN cache — on every `/api/`
  response. Predates this work, but it makes any API shape change slow to
  propagate. Revisit before the API is used in anger.

---

## Constraints that bind every task

From `CLAUDE.md`, repeated because they have already caused bugs:

- **Never re-add pandas.** Root `requirements.txt` is runtime-only.
- **`num()` for every numeric that could be an aggregate.** `AVG()` over zero rows
  is NULL and arrives as `None` from tuples, `NaN` from dicts.
- **Every `ORDER BY` with ties needs a tiebreaker.** Responses are compared
  byte-identical.
- **Runtime reads one parquet.** Don't add a second runtime data source without
  deciding deliberately how it deploys.
- The Causal Evidence scoring invariants — spike days, `available: false` never 0,
  IDF-weighted actor tokens, one-type-one-candidate — are all documented in
  `CLAUDE.md`. Read that section before touching `scoring/`.

---

## Cut lines

If time runs short, cut in this order. Each leaves a coherent system.

1. **P6.3 tests 1 and 2.** Keep negative controls. You lose external validation
   and must say so explicitly in any writeup.
2. **Phase 4 entirely.** You lose structural causes and keep the single window.
   This is the largest capability loss on the list — cut it only if Phase 2
   overran badly.
3. **P3.2 / P3.3 real text channels.** Fall back to the precursor proxy and a
   permanently-unavailable contradiction channel. The architecture still stands;
   two of six channels stay weak.
4. **P5.3 recursion.** Ship depth-1 explanations only. Still useful, much less
   interesting.

**Do not cut:** P0 (the gates), P2.3–P2.4 (no labels means no calibration means no
error rate), P3.4 (the whole claim of the design), P3.5 (cheapest and most
diagnostic test you have).

---

## Open decisions

Resolve these before the phase that depends on them.

| Decision | Needed by | Note |
|---|---|---|
| SQLite vs Postgres/Supabase | P1.1 | SQLite is simpler; Supabase matters only if annotators work concurrently from different machines |
| Extraction: rules vs trained model | P2.1 | Rules are faster to build and debug; a model needs labels you don't have yet |
| Whether checks 3 and 4 stay separate | P3.4 | Empirical. If fitted weights show one absorbing the other, merge them |
| Neo4j or stay in SQL | P5.2 | `pipeline/dashboard/04_export_neo4j.py` exists. Recursive CTEs over a materialized edge table may be enough, and deploy far more easily |
| Article text redistribution | P1.2 | Full text stays private to the team unless licensing says otherwise |

---

## What this will and will not establish

It produces **causal claims graded by evidential support, with a measured error
rate**. It does not verify causality — nothing built on observational news data
can, because February cannot be rerun without the policy announcement.

Name the relation `SUPPORTED_CAUSE`, not `CAUSES`. Call the artifact a *causal
claim graph*. State the ceiling before a reviewer states it for you.
