# Phase 12 — Graph storage and build

**Status: the acceptance check is met.**
- **Determinism.** Two builds with the same config are byte-identical.
- **New version from a threshold change.** Raising one threshold gives a new
  graph version, and the evidence tables are not touched.
- **Everything is stored.** The whole text pipeline (Phases 7–11) is in the
  evidence store, including every rejection and every evidence span.

## Where it lives

The text pipeline is loaded into its own Postgres schema, **`text_graph`**,
created by `store.db.init`. It gets the same tables, the same append-only
triggers and the same `build_versions`.

The store's `public` schema keeps its GDELT-era rows untouched: 370k sources,
2,347 GDELT events, the scorer's 3,642 claims and the annotator queue. The two
pipelines use different event identities: GDELT rows versus canonical text
events. Mixing them in one `claims` table would put both in front of the
annotator. Choosing `--schema public` would merge them on purpose later. Dropping
`text_graph` removes this load completely.

**Schema additions** (`store/schema.sql`, `ADD COLUMN IF NOT EXISTS`, safe on the
existing store):
- **`external_id` on every table, holding the pipeline id.** That is `ce:` /
  `cc:` / `cl:` / mention ids, or the article id on `sources`. A reload converges
  and never duplicates.
- **Events:** `status`, `actors`, `targets`, `locations`, `time_confidence_label`
  and `search_status`. The pipeline grades dates high/medium/low and never
  computed a probability, so the label is stored as it is, not invented as
  `time_confidence`.
- **Conditions:** `kind`, `role`, `holders`, `locations`, `valid_from_stated` and
  `search_status`.
- **Mentions:** `condition_id` (a mention reports an event or a condition),
  `text_sha256` (the cleaned text that the offsets index into), the field
  `spans`, `reviewer` and `label_source`.
- **Claims:** `retriever`, `signals`, `temporal_gap_days`, `expansion_level` and
  `machine_relation_type`. That last one is null until a model predicts
  relations.
- **Annotations:** `primary_evidence`, `supporting_evidence`, `evidence_quality`,
  `corroboration_count`, `reviewed_at` (when the judgement was made, not when it
  was loaded), `label_source` and `role` (primary / second / spot-check).

## Load (`pipeline/26_load_store.py`)

| Table | Rows | From |
|---|---:|---|
| sources | 139 | reviewed articles (URL, content hash, raw HTML path; text stays on the evidence volume) |
| events | 1,073 | canonical events v4 |
| conditions | 200 | canonical conditions v1 |
| mentions | 1,368 | 1,124 event mentions and 244 condition mentions, with their spans |
| claims | 2,748 | levels 1–3; 244 accepted, **2,504 rejected and kept** |
| annotations | 3,521 | 2,748 primary, 733 second-annotator, 40 human spot-check |

**Idempotent.** A second run inserted 0 rows in every table.

**Search status** is the one mutable value. It is stored on events and
conditions from Phase 11's latest status file.

**Human spot-check.** Each verdict is stored as its own annotation: agreeing
repeats the AI's call, and disagreeing flips it. A claim's `verdict` stays the
primary annotator's. The one human disagreement is a reject the human would
accept. It shows up in that claim's review history, but it adds no edge,
because an edge needs an evidence span and the spot-check gave none.

## Build (`pipeline/40_build_graph.py`)

`compile_graph(snapshot(store), config)` is a pure function:
- rows are read in `external_id` order;
- JSON is written with sorted keys and no timestamps of its own;
- the version is the SHA-256 of the bytes;
- the file is `data/evidence/graph/causal-graph.<version[:16]>.json`.

If a file for that version already exists, it is checked byte for byte and
never overwritten. A difference would mean the build is not deterministic.

`--register` records the build in `build_versions`. Its key covers both the
config and the store's fingerprint, so the same config over a changed store
counts as a new build.

**Config** (`pipeline/graph_config.v1.json`):
- `relation_map` applies Phase 10's taxonomy revision at build time
  (CONTRIBUTES_TO → MOTIVATES). The judged label stays on the edge as
  `judged_relation`.
- `kinds`, `evidence_quality`, `min_strength`, `min_corroboration` and
  `include_ai_labels` are filters.

**Every edge keeps:**
- source article ids, exact evidence spans and the article URLs;
- the cause and effect dates;
- its strength, with the machine strength and machine relation (null for now);
- its temporal gap and expansion level;
- its full review history: every annotator, role, action, relation or reject
  reason, review time and label source.

  Six edges carry a dissenting second annotator's rejection.

## Results

| Build | Config | Version | Edges | Nodes |
|---|---|---|---:|---:|
| A | `graph_config.v1.json` | `57acd8f502198625` | 244 | 212 |
| A again | same | `57acd8f502198625` (byte-identical) | 244 | 212 |
| B | same, but `min_strength: 0.5` | `a03b7b1283fe6a81` | 171 | 176 |

Every build reports the same store fingerprint, `718f6af4174a…`. The evidence
tables keep the same row counts before and after building. Only
`build_versions` gained a row.

**Graph A:**
- **Edges by relation:** MOTIVATES 143, TRIGGERS 42, ESCALATES 38, MOBILIZES 12,
  PROMPTS_RESPONSE 9.
- **Nodes:** 133 events and 79 conditions. The 4 protests with no accepted cause
  are not in the graph.
- **Search status of nodes:** PARENTS_FOUND 101, NO_SUPPORTED_PARENT_FOUND 94,
  UNVERIFIABLE 7, OUT_OF_SCOPE 5, NOT_YET_REVIEWED 5.

**Test.** `tests/test_graph_store.py` checks all of this against a throwaway
schema:
- a reload inserts nothing;
- two builds are byte-identical;
- a stricter `min_strength` gives a new version with fewer edges;
- building leaves every evidence table's row count unchanged;
- a second annotator's rejection travels with the edge;
- edges carry spans and URLs.

## Not done here

- **Entities are not built.** Actors and places stay as text lists on nodes.
  `entities` and the `*_entity_id` columns remain empty until entity resolution
  is worth doing.
- **Missed causes and the Phase 9/9b recall reviews stay in JSONL.** They are
  measurements of retrieval, not graph evidence.
- **The annotator is not pointed at `text_graph` yet.** It reads GDELT-shaped
  events (`source_urls`, `external_id`) from `public`. Human review of these
  edges in the annotator needs it to read this schema.

## Files

| File | SHA-256 |
|---|---|
| `pipeline/graph_config.v1.json` | `49c2c821fce2e3f0c6fe5dc9bf2fed61826deaf07b249b0195351021a50d4faf` |
| `data/evidence/graph/causal-graph.57acd8f502198625.json` (build A) | `57acd8f5021986256d1c10d59491f95c7ef2ab809eaf75d0498adab163e4cca1` |
