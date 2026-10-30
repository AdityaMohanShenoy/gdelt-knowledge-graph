# Build plan — evidence-backed causal temporal knowledge graph

Target: a temporal knowledge graph that explains the causal histories of protest
events in India during 2024. It is event-centric:

    Source article → Event mention → Canonical event → Causal relation → Causal explanation

GDELT is the discovery and metadata layer. A GDELT row or a source article is not
automatically a graph event. Every accepted event and causal edge stays traceable
to an exact text span in a GDELT-backed article.

> **ML retrieves and proposes; evidence and human review decide.**

This plan follows the focal-event work in `pipeline/10_extract_focal_events.py`
and its review frontend (PR #8), and the project handoff of 2026-10-30. It
supersedes the plan of 2026-09-17. Work that plan already delivered is kept and
mapped onto the phases below. Read `CLAUDE.md` first; its invariants bind
everything here.

---

## How to drive this from the CLI

Tasks are numbered `P<phase>.<n>`. Each names its goal, the files it touches, and
an acceptance test.

    claude
    > read docs/BUILD_PLAN.md and do P4.1

Rules for whoever executes this:

- **One task per branch/PR.**
- **Acceptance criteria are not optional.** Done means the check passes.
- **Gates are hard stops.** Record the measurement in `docs/measurements/` and
  re-scope rather than routing around a failed gate.
- **Never overwrite a source file.** Screening, extraction, prediction and
  template files are immutable. Every reviewed export and experiment gets a new
  filename.
- **Commit the measurement, not just the data.** `data/evidence/` is gitignored, so
  every metrics file that a decision rests on gets a summary in
  `docs/measurements/` with its input hashes.
- **`python test_app.py` must pass before every push.**

---

## Where we are now

### Focal-event review batch

| Item | State |
|---|---:|
| Screened records | 300 |
| Retained full article snapshots | 279 |
| Extraction-rejected records | 21 |
| Proposed usable focal events | 205 |
| Proposed exclusions | 95 (74 unrelated + 21 insufficient text) |
| Proposed direct protest / protest-linked | 204 / 1 |
| Supporting sentence selections | 477 |
| Completed entity labels | 0 |
| Human-verified records | 0 |

Every record is `review_status = UNREVIEWED`, `reviewer = Codex (AI)`,
`label_source = ai_assisted`. **None of these are gold labels.** The 52.7% Top-1 /
75.6% Top-3 overlap in the README is measured against AI drafts, not human
judgement, and is not a baseline.

Authoritative files, all under `data/evidence/focal_events/`:

| File | Role |
|---|---|
| `protest-review-300.ai-assisted.packet.jsonl` | all 300 records; serve this for screening |
| `protest-review-300.ai-assisted.annotations.jsonl` | 279 full sentence-level records |
| `protest-review-300.ai-assisted.screening.jsonl` | screening proposals |
| `protest-review-300.ai-assisted.manifest.json` | hashes of the above |
| `protest-review-300.jsonl` | saved predictions (279) |
| `protest-review-300.v2.annotations.jsonl` | blank template, no AI draft, no ranks |
| `protest-review-300.screening.jsonl` | source screening |

The first 60 screening records are the earlier pilot, so the 300 are a nested
sample, not an independent one.

### Already built on `main`

| Thing | State | Used by |
|---|---|---|
| Article fetcher + extractor (`07`, `09`) | working; GATE 0.1 passed at 71.1% | all phases |
| Evidence store (`store/schema.sql`) | `sources`, `mentions`, `events`, `entities`, `claims`, `claim_channels`, `annotations`, `build_versions`; evidence tables append-only by trigger | P7–P12 |
| `13_load_sources.py` | `article_documents` → `sources`, keyed by `article_document_id` | P7 bridge |
| Causal annotator (`14_run_annotator.py`, `annotator/`) | accept/edit/reject with the fixed rejection taxonomy; stores machine and human strength; machine score hidden by default; deployable to Vercel against a Supabase `evidence` schema | P9–P10 |
| `15_link_sources.py` | attaches source articles to store events | P9 |
| `scoring/` | retrieval and fusion lifted out of `app.py` | P9 |
| Negative controls (`31`) | **GATE 3.5 failed**: the `pattern` grade fires as often on shuffled pairs as on real ones | P9, P14 |
| Branching worksheet (`out/branching_worksheet.csv`) | 15 seeds, 323 candidates to depth 3, **0 judged** | P11 gate |
| Dashboard Causal Evidence tab | metadata-only demo, uncalibrated weights | P13 |

---

## Phase 0 — Access and environment

### P0.1 — Share the review packet

**Goal.** The review files exist only on the machine that generated them.
Nobody else can start Phase 1 until they have them.

**Build.** Copy the seven files above plus their manifest to a shared location.
Recipients verify every hash in the manifest before opening the viewer.

**Accept when.** A second machine reproduces every manifest hash.

### P0.2 — Environment

    docker compose up -d postgres
    .venv/bin/python pipeline/08_run_viewer.py --port 8001 \
      --review-annotations data/evidence/focal_events/protest-review-300.ai-assisted.packet.jsonl

Open http://127.0.0.1:8001/review. For model inspection, serve the 279-record
annotations file with `--review-results data/evidence/focal_events/protest-review-300.jsonl`.

- Review needs no database. Without Postgres the viewer logs a warning, serves
  `/review` from the local JSONL, and answers 503 on the article routes.
- Where a local `docker-compose.override.yml` publishes the container on 5433
  (because Homebrew Postgres holds 5432), set
  `DATABASE_URL=postgresql://gdelt:gdelt_local@localhost:5433/gdelt`. Otherwise
  the viewer and the Postgres tests reach the wrong server and fail with
  `role "gdelt" does not exist`.
- Install with `uv sync --group pipeline --group ml`. If `uv` cache permissions
  fail, set `UV_CACHE_DIR=/tmp/gdelt-uv-cache`, or use `.venv/bin/python`
  directly.

---

## Phase 1 — Human screening review

**Goal.** A human decision on all 300 records: protest relevance, body quality,
India/2024 scope, and exclusion reason.

**Do P5.1 first.** Run `split` before any review (see Phase 5), and review from
its output packet in this phase and the next. Test records arrive without AI
screening proposals as well as without focal-event drafts. `split` refuses input
that already has reviews.

Read the complete saved article. Cue counts are not enough: a protest cue may be
historical, quoted, negated, or unrelated to the article's primary development.

Allowed values (`focal_event_evaluation.ELIGIBILITY_LABELS`):

| Field | Values |
|---|---|
| `protest_relevance` | `PROTEST`, `PROTEST_LINKED`, `UNRELATED`, `UNCERTAIN` |
| `body_quality` | `COMPLETE`, `LIMITED`, `INSUFFICIENT` |
| `scope` | `INDIA_2024`, `OUT_OF_SCOPE`, `UNCERTAIN` |
| `exclusion_reason` | `UNRELATED`, `INSUFFICIENT_TEXT`, `OUT_OF_SCOPE`, `NO_FOCAL_EVENT`, `OTHER` (requires notes) |

**Fix on the way through.** Twenty-one AI proposals carry
`body_quality = INSUFFICIENT_TEXT`. That is an exclusion reason, not a body
quality. Correct them to `INSUFFICIENT`, or validation fails once they are
saved.

The 21 extraction-rejected records stay explicit exclusions unless the source is
re-acquired and extracts cleanly. Do not invent evidence for them.

**Accept when.** All 300 records have `eligibility.review_status = REVIEWED`. Each
has a human screening reviewer (not `Codex (AI)`) and a valid relevance value.
Every insufficient or unrelated record has an exclusion reason.

---

## Phase 2 — Focal-event review

**Goal.** For each usable article, the single primary development and every
sentence that supports it.

For each usable article: read the whole text, and decide the primary development.
Edit the summary, select the supporting sentence IDs, and remove historical or
irrelevant sentences. Confirm the event is protest-related. Record reviewer,
provenance, split and notes. For each unsuitable article: mark it `UNSUITABLE`,
set the exclusion reason, and explain any unusual exclusion in the notes.

The 205 proposed usable records are starting points. The 74 proposed unrelated
records also need human review, because automatic relevance can be wrong.

**Provenance.** Use `label_source = human` when the reviewer wrote or changed the
label. Keep `ai_assisted`, with the human named as `reviewer`, when an AI draft
was accepted unchanged. Phase 4 reports the two separately.

**Test records are reviewed blind.** The packet from P5.1's `split` command has
already stripped every AI draft from test records, so serve that packet. Do not
open the model inspector on a test record before its review is saved. This
mirrors the annotator's hidden machine score: a label that started from the
system's own proposal cannot measure that system.

**Accept when.** Reviewed records have `REVIEWED`, a non-empty human reviewer, a
`label_source`, a non-empty `focal_event_summary`, and valid non-empty
`supporting_sentence_ids`. Excluded records have `UNSUITABLE`, a reviewer, and
an `eligibility.exclusion_reason`. Every article text, hash, headline, sentence
boundary and offset is unchanged; `10_extract_focal_events.py audit` and the
snapshot validation in `evaluate` both pass.

---

## Phase 3 — Entity annotation

**Goal.** An exhaustive NER benchmark over `PERSON`, `ORGANIZATION`, `LOCATION`,
`DATE`.

Annotate every occurrence in the full article, not only the support sentences.
That includes repeated mentions, background text and bylines:

    {"text": "Delhi", "label": "LOCATION", "start_char": 10, "end_char": 15}

- Use exact Python character offsets, and never edit article text.
- Never copy model predictions automatically.
- An article with no eligible entities gets a confirmed `[]`, not `null`.
- Set `whole_article_checked = true` only after reading the complete text.
- The 21 rejected snapshots have no reliable text and are not annotated.

**Scale.** The model predicted 3,647 entity spans across the 279 snapshots, about
13 per article. Exhaustive annotation is the largest single labelling job in this
plan. Start with the test split (see *Cut lines*).

**Double review.** Have a second reviewer annotate at least 20% of the records
independently. Report exact-offset-and-label agreement before freezing.

**Accept when.** Every benchmark record has `gold_entities` as a list,
`ner_annotation.review_status = REVIEWED`, `whole_article_checked = true`, and a
reviewer. Inter-reviewer agreement is reported.

---

## Phase 4 — Freeze the gold dataset

### P4.1 — `freeze` command

**Build.** Add a `freeze` subcommand to `10_extract_focal_events.py`. Today there
are `prepare-models`, `screen`, `extract`, `annotate`, `evaluate` and `audit`,
and nothing writes the manifest.

Output: `protest-review-300.gold.v1.annotations.jsonl` plus a manifest with:
- input and output hashes
- article, reviewed and unsuitable counts
- entity counts
- reviewer provenance, with counts by `label_source`
- schema version and the exclusions
- validation results and a creation timestamp

The command refuses to write a file named `gold` if any record's reviewer is
`Codex (AI)`. If labels were accepted from AI without human inspection, name the
dataset `ai-assisted` or `weak` and keep it apart from the test set.

    .venv/bin/python pipeline/10_extract_focal_events.py evaluate \
      --input data/evidence/focal_events/protest-review-300.jsonl \
      --annotations data/evidence/focal_events/protest-review-300.gold.v1.annotations.jsonl \
      --output data/evidence/focal_events/protest-review-300.gold.v1.metrics.json

Confirm `evaluate` accepts the 21 screening-only records against the 279-record
prediction file before relying on this command.

**Accept when.** `freeze` runs twice and produces byte-identical output, the
manifest hashes verify, and `evaluate` passes on the frozen file.

---

## Phase 5 — Splits

### P5.1 — Assign stable splits, before review

| Split | Use |
|---|---|
| `train` | model fitting |
| `dev` | threshold and rule tuning |
| `test` | final one-time evaluation |
| `demo` | interactive demonstration subset |

    .venv/bin/python pipeline/10_extract_focal_events.py split \
      --input data/evidence/focal_events/protest-review-300.ai-assisted.packet.jsonl \
      --pilot data/evidence/focal_events/protest-pilot.screening.jsonl \
      --output data/evidence/focal_events/protest-review-300.splits.packet.jsonl

The command writes a new packet with `split` set on every record, plus a
`.manifest.json` beside it. Reviewers then serve the new packet. Nothing is
overwritten.

- Same URL or final URL, same `content_hash`, same text, or word 5-shingle
  Jaccard ≥ 0.8 puts articles in one group, and a group never spans splits.
- **The 58 previously inspected pilot records never enter `test`.** Pass every
  pilot file with `--pilot`. A pilot article's group becomes `pilot`, since a
  duplicate of an inspected article has been inspected too.
- The remaining groups are ordered by a seeded hash and fill `test` (20%), then
  `dev` (20%), then `train`.
- **Test records come out blind.** They keep only the frozen snapshot
  (`SNAPSHOT_KEYS`), and every AI draft field is dropped. Train and dev keep
  their drafts.
- Protest cohort is a review label, so it cannot stratify a split made before
  review. The manifest reports host overlap and month coverage now. Check cohort
  balance after Phase 2, and re-split with a new seed only if it is badly skewed
  and test review has not started.
- `evaluate` accepts only `pilot`, `train`, `dev`, `test`. Keep `demo` as a
  separate ID list, or extend the validator.
- The test split is frozen once tuning begins.

**Accept when.** A committed `docs/measurements/splits.md`, written from the
manifest, reports counts per split and the duplicate groups. Cohort counts are
added after Phase 2. The split manifest is hashed into the Phase 4 manifest.

---

## Phase 6 — Baseline

**Goal.** Measure the current system before introducing a new model.

Report focal-event Top-1 accuracy and Top-3 recall, and evidence-span validity.
Report NER precision, full-article recall, candidate-only recall, and
exact-offset-and-label accuracy. Break results down by protest cohort, by article
quality, and for short and noisy articles.

Analyse errors on:
- Top-3 misses and wrong focal summaries
- historical or quoted protest mentions
- navigation-contaminated text
- multi-event articles
- conflicting entity labels
- long sentences and offset errors

**Accept when.** `docs/measurements/focal_baseline.md` reports dev-set metrics
with input hashes and the error analysis. Test-set numbers are reported once,
separately, and are not used for any later tuning.

---

## Phase 7 — Atomic event mentions

**Goal.** One article → several structured mentions. The focal event is one of
them, not the only one.

    E1 Government announced a policy   E2 Union rejected the policy
    E3 Union called for a march        E4 Demonstrators blocked a road

**Build.** `pipeline/20_extract_events.py`, writing to the store's `mentions`.

Fields: `event_mention_id`, `source_article_id`, actors, action, target/topic,
location, `event_time`, `event_type`, `evidence_start`, `evidence_end`,
`confidence`, `review_status`. Every field is backed by an exact span or
explicitly marked uncertain. ML may propose mentions; it must not invent
unsupported ones.

- **Bridge.** A focal `article_id` is `article_documents.document_id`. In the
  store, that is `sources.article_document_id`.
- **Offsets need a pinned text.** Screening snapshots re-extract from saved HTML
  with the current extractor, so they can differ from the stored cleaned text.
  Each mention records the hash of the exact text its offsets index into.
- **Schema migration.** `mentions` lacks `review_status`, target/topic and
  location, and holds only two actor slots. `entities.kind` uses
  `actor`/`place`/`organisation`, while NER emits
  `PERSON`/`ORGANIZATION`/`LOCATION`; map them in one place. The store is
  append-only, so add columns; do not rewrite rows.
- Seed from Phase 2: each reviewed focal event and its support sentences become
  the article's first mention.

**Accept when.** On 20 hand-checked articles, every mention's evidence span, sliced
from its pinned text, contains the event it claims, and no field is unsupported.

---

## Phase 8 — Canonicalization

**Goal.** Mentions of the same real event in different articles → one canonical
event.

**Build.** `pipeline/21_canonicalize.py`, writing the store's `events` and
`mentions.event_id`.

- Block on date bucket, location and event type. Within a block, score actor and
  location overlap, date proximity, action and semantic similarity, shared
  entities, and supporting evidence.
- Automate high-confidence merges. Send ambiguous ones to human review. Never
  auto-merge below the review band.
- Canonical events carry `canonical_event_id`, description, `event_type`,
  actors, location, `best_time`, `time_range`, `time_confidence`,
  `supporting_sources`, and `review_status`.
- **Never** merge because two articles share a URL or a GDELT event row. Today
  `events.external_id` holds a GDELT GlobalEventID, from annotator seeding.
  Canonical events must not be seeded one-to-one from GDELT rows.

**Accept when.** A known multi-outlet event collapses to one node, and the report
gives merge counts by tier (auto / reviewed / rejected).

> Without this, the strongest "causal" links are the same event reported twice,
> and corroboration counts outlets that are really one story.

---

## Phase 9 — Candidate causes

**Goal.** For each accepted 2024 India protest seed, a broad and inspectable set
of candidate causes.

**Build.** Re-point `14_run_annotator.py seed` and `scoring/retrieval.py` at
canonical events instead of GDELT rows.

1. Search backward through GDELT-backed events, starting with a 7-day window.
2. Retrieve broadly on actor, entity, location, date, event type and text.
3. Allow upstream events outside the protest category, and attach evidence
   articles (`15_link_sources.py`).
4. Store every candidate, including ones that will be rejected.

Similarity, embeddings, temporal order and actor overlap create candidates. They
never establish causality. GATE 3.5 already showed that the fused score cannot
tell real pairs from shuffled ones at the `pattern` grade. Use it to order the
queue, never as a confidence.

The 3,642 claims already seeded from 40 GDELT-row targets are a legacy pilot.
The store is append-only, so keep them, tagged, and exclude them from results.

**Accept when.** Every seed has a candidate set stored as `claims`, and the queue
serves candidates across seeds rather than draining one seed first.

---

## Phase 10 — Causal annotation

**Goal.** Human-verified edges, and a preserved set of rejections.

Use the existing annotator. It already implements accept/edit/reject, the
rejection taxonomy, machine and human strength stored side by side, and a hidden
machine score.

Relation types: `TRIGGERS`, `MOTIVATES`, `MOBILIZES`, `ENABLES`, `ESCALATES`,
`PROMPTS_RESPONSE`, `CONTRIBUTES_TO`.

Each edge stores:
- `source_event_id`, `target_event_id`
- `relation_type`, `machine_relation_type`
- `machine_strength`, `final_strength`, `temporal_gap`
- `primary_evidence`, `supporting_evidence` (mention spans)
- `evidence_quality`, `corroboration_count`
- `review_status`, `reviewer_id`

Of these, `machine_relation_type`, the evidence spans, `evidence_quality` and
`corroboration_count` are not in `claims`/`annotations` yet, and need adding.

**Accept** only on inspectable text:
- explicit "because of" wording
- explicit response wording
- protest-against wording
- a clear policy–response linkage
- clearly described escalation
- direct mobilization or organizing language

**Never accept** on temporal order, actor similarity, shared topic, embedding
distance, or a model prediction alone.

**Reject with a reason:** `NO_CAUSAL_EVIDENCE`, `TEMPORALLY_INVALID`,
`WRONG_EVENT_MATCH`, `DUPLICATE_EVENT`, `CORRELATED_ONLY`,
`INSUFFICIENT_EVIDENCE`, `WRONG_DIRECTION`, or `OTHER`. Rejections are the hard
negatives a later ranker trains on.

**Agreement.** Double-annotate 25% of pairs and report agreement per relation
type. Expect the seven types to collapse to four or five. `TRIGGERS` and
`ESCALATES` differ only in whether the effect already existed. `MOTIVATES` and
`CONTRIBUTES_TO` differ mostly in confidence, which belongs in strength. Revise
the taxonomy from the measured agreement.

**Accept when.** Every judged pair persists with its reviewer and timestamp,
rejected candidates are queryable as a set, and agreement is reported per type.

---

## Phase 11 — Recursive expansion

**Goal.** When `A → B` is accepted, A becomes the next target.

Stop a branch when:
- no supported parent is found
- 2024-01-01 is reached
- the evidence becomes unverifiable
- the branch is rejected

Record each event's search status: `PARENTS_FOUND`,
`NO_SUPPORTED_PARENT_FOUND`, `NOT_YET_REVIEWED`, `UNVERIFIABLE`. Without that
status, "we looked and found nothing" and "nobody has looked" read the same.

Precision over recall: an unsupported edge stays absent rather than becoming a
low-confidence guess. Converge on existing canonical events rather than
duplicating them. Cause time precedes effect time, so the instance graph is
acyclic by construction.

> **GATE 11 — branching factor.** Judge `out/branching_worksheet.csv` (15 seeds,
> 323 candidates, none judged yet) and write `docs/measurements/branching.md`.
> A mean above **4** accepted parents projects to more than 100k edges at depth
> 3, which no team can verify by hand. In that case, bound the depth or the
> number of seeds before starting human-verified recursion.

**Accept when.** A seed expands to a multi-level DAG, branches converge on shared
nodes, and a cycle check finds none.

---

## Phase 12 — Graph storage and build

The store already keeps these separate: source articles (`sources`), event
mentions (`mentions`), canonical events (`events`), entities, causal edges
(`claims`), annotation decisions (`annotations`) and config versions
(`build_versions`). Rejected candidates and evidence spans live in those tables
too. Large raw HTML and cleaned text stay on the evidence volume or in object
storage, never inside graph tables.

**Build.** `pipeline/40_build_graph.py`, which compiles the graph from the store
plus a config. It is a versioned, reproducible artifact, not a hand-edited
database. Every edge keeps:
- source article IDs, exact spans and URLs
- event dates
- reviewers and review history, including rejections
- confidence values

**Accept when.** Two builds with the same config are byte-identical, and changing
one threshold yields a new version without touching the evidence store.

---

## Phase 13 — Query and explanation

    User question → Event grounding → Causal subgraph retrieval → Path ranking → Evidence-backed explanation

- Ground a question to a cluster of events when it names a movement rather than
  one event. Ask for clarification when several clusters match.
- Rank paths by relation strength, query relevance, evidence quality and
  corroboration. Report coverage: how much of the target's causal support the
  answer accounts for.
- Explanations cite canonical events, dates, relation types, edge strengths,
  source articles and exact spans. Prose is generated from graph records.
  Explanations never create new relationships.
- Dashboard integration replaces the demo Causal Evidence tab. The runtime still
  reads one data source (see `CLAUDE.md`), so decide deliberately how the
  compiled graph deploys.

---

## Phase 14 — Final evaluation and release

The project is complete when:
- all final screening records are reviewed
- every accepted focal event has exact evidence
- every excluded record has a reason
- all benchmark NER records are confirmed against the whole article
- the test set was never used for tuning
- every causal edge is human-verified, with source evidence
- rejected candidates are preserved
- the graph builds reproducibly from versioned inputs
- evaluation reports are saved with hashes
- queries return evidence-backed explanations
- the demo traces a path from question to source article and sentence

External checks, none of which consult the annotation pool:
1. **Documented-chain recovery.** Take 15–20 events with published post-mortems
   (the 2024 farmers' movement has extensive retrospective coverage) and measure
   recall against the chains those accounts establish.
2. **Negative controls.** Rerun `31_negative_controls.py` against the final
   retrieval and report false positives.

Agreement between reviewers measures consistency, not correctness. Without these
checks, the system only validates itself against itself.

---

## Responsibilities

| Agent | Human reviewer |
|---|---|
| schema validation; hash and offset checks | ambiguous protest relevance |
| candidate retrieval; model proposals | focal-event correctness |
| duplicate detection | entity inclusion decisions |
| manifests; repeatable exports; metrics | canonicalization disputes |
| browser and database tests | causal direction and relation type |
| preserving provenance | final edge acceptance; test-set protection |

---

## Constraints that bind every task

- **Never re-add pandas.** Root `requirements.txt` is runtime-only. Pipeline deps
  go in `pipeline/requirements.txt` and the `pipeline` group, and model deps in
  the `ml` group.
- **Exact Python character offsets**, against a pinned text hash. Article text is
  never edited.
- **Evidence tables are append-only.** Corrections are new rows.
- **`num()` for every numeric that could be an aggregate**, and **every
  `ORDER BY` with ties needs a tiebreaker**. Responses are compared
  byte-identical.
- **`available: false`, never 0**, for a signal with no data. "Nobody denied it"
  and "we never looked" must stay distinguishable.

---

## Cut lines

Cut in this order. Each leaves a coherent system.

1. **Phase 3 beyond the test split.** Exhaustive NER on the test split only.
   Training NER waits.
2. **Phase 13 query grounding.** Ship fixed explanations for the seed events.
3. **Phase 11 recursion.** Ship depth-1 causes only.
4. **External check 1.** Keep the negative controls, and say so in any writeup.

**Do not cut:** Phases 1–2 human review, test-set protection (Phases 2 and 5),
preserved rejections, or edge agreement in Phase 10.

### Deferred from the 2026-09-17 plan

Not scheduled. Revisit after Phase 12:
- condition nodes and the four timescale strata (structural causes such as
  "falling farm-gate prices, Punjab, 2022–2024" have no node type until then)
- the six-channel fusion's textual and contradiction channels
- calibrated weights fitted on Phase 10's machine-versus-human strengths
- the combined grades

---

## Open decisions

| Decision | Needed by | Note |
|---|---|---|
| Where the review packet is shared | P0.1 | Must preserve bytes; hashes are checked |
| Can unchanged AI drafts enter gold? | Phase 4 | Recommended: yes for train/dev with `ai_assisted` provenance; never for test |
| `demo` as a split or a separate list | P5.1 | `evaluate` rejects unknown split values |
| Local Postgres vs Supabase | Phase 12 | Handoff says stabilize locally first; the annotator already deploys against a Supabase `evidence` schema |
| Seven relation types or fewer | Phase 10 | Decide from measured agreement |
| Article text redistribution | P0.1 | Full text stays private to the team unless licensing says otherwise |

---

## What this will and will not establish

It produces **causal claims backed by inspectable evidence and human review, with
measured agreement and a protected test set**. It does not verify causality.
Nothing built on observational news data can: February cannot be rerun without
the policy announcement.

Name the relation `SUPPORTED_CAUSE`, not `CAUSES`. Call the artifact a *causal
claim graph*.
