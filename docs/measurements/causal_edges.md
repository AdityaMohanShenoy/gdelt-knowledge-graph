# Phase 10 — Causal annotation

**Status: the acceptance check is met, with AI annotators.**
- Every candidate claim (1,101) is judged and stored with its reviewer and
  timestamp. The result is **156 accepted edges** and **945 rejections**, each
  rejection with its reason.
- A quarter of the claims were double-annotated, and agreement is reported per
  relation type.
- The tightened retrieval holds up on 43 protests it was not tuned on.

All labels are AI (`Claude (AI) A` / `B`, `ai_assisted`). The agreement figures
are between two instances of the same model, so read them as consistency, not as
human agreement.

## Method

- **Tools.** `pipeline/24_annotate_causes.py` with `pipeline/causal_annotation.py`,
  under `docs/causal-annotation-rubric.md`.
- **Blind packets.**
  - Each packet is one protest with its full article(s) and its candidates in
    shuffled order.
  - Packets carry no retrieval signals or scores.
  - Eight primary judges took about 138 claims each.
- **What a judgement records.**
  - **Accept:** a relation, a strength (1–3), `explicit`/`implicit` evidence
    quality, and an exact quote. The quote is located in the article text and
    stored as a span.
  - **Reject:** one of the plan's eight reasons.
  - **Missed causes:** each judge also lists the causes the article names that
    no candidate represents.
- **Validation.** `apply` refuses any accept whose quote is not verbatim
  article text, and any value outside the taxonomy.
- **Double annotation.** Whole protests, drawn at random until they held 25% of
  claims, went to two further judges: 283 claims in 19 protests.
- **Edges JSONL.** It carries every field the plan lists:
  - `source_event_id`, `source_kind`, `target_event_id`;
  - `relation_type`, `machine_relation_type`, `machine_strength`,
    `final_strength`, `temporal_gap`;
  - `primary_evidence`, `supporting_evidence`, `evidence_quality`,
    `corroboration_count`;
  - `review_status`, `reviewer_id`, `reviewed_at`.

  `machine_relation_type` and `machine_strength` are null: no model predicts
  them yet, and the retrieval score is not a strength.
- **JSONL first, as in Phase 9.** The existing annotator works on the Postgres
  store, which these canonical nodes reach only in Phase 12. Loading edges into
  `claims`/`annotations` happens there, and so does human review in the
  annotator.

## Results

| Measure | Result |
|---|---:|
| Claims judged | 1,101 (63 protests) |
| **Accepted edges** | **156** (14%): from conditions 91, from events 65 |
| Accept rate: conditions / events | 91 / 139 (65%) / 65 / 962 (7%) |
| Protests with at least one edge | 59 / 63; mean 2.5, median 2, max 9 |
| Strength 3 / 2 / 1 | 55 / 57 / 44 |
| Evidence explicit / implicit | 112 / 44 |
| Corroborated by a second outlet | 4 |
| Accepted events more than 7 days back | 14 (lags 8–66 days) |

| Relation | Edges | Mostly from |
|---|---:|---|
| MOTIVATES | 82 | conditions (74) |
| TRIGGERS | 24 | events (23) |
| ESCALATES | 21 | events |
| CONTRIBUTES_TO | 18 | conditions (16) |
| MOBILIZES | 7 | events |
| PROMPTS_RESPONSE | 4 | events |
| ENABLES | 0 | — |

**Rejections (945), the hard negatives.**

| Reason | Rejections |
|---|---:|
| NO_CAUSAL_EVIDENCE | 401 |
| CORRELATED_ONLY | 269 |
| DUPLICATE_EVENT | 118 |
| INSUFFICIENT_EVIDENCE | 76 |
| WRONG_DIRECTION | 73 |
| TEMPORALLY_INVALID | 5 |
| OTHER | 3 |

Rejections are queryable as a set: `review_status == "REJECTED"` in the edges
file, each with its reason, the judge's `why`, and the claim's evidence.

## Retrieval on fresh protests

The thresholds from `docs/measurements/conditions.md` were chosen on 20
protests. These are the first figures on the other 43.

| | Tuning seeds (20) | **Fresh seeds (43)** |
|---|---:|---:|
| Precision (accepted / claims) | 53 / 374 (14.2%) | **103 / 727 (14.2%)** |
| …conditions | 29 / 50 | 62 / 89 |
| …events | 24 / 324 | 41 / 638 |
| Recall: accepted / (accepted + missed) | 53 / 61 = **0.87** | 103 / 124 = **0.83** |
| Recall, excluding demands and commentary listed as "missed" | 53 / 59 = 0.90 | 103 / 118 = 0.87 |

**The tuned rule generalises.** Precision is identical on fresh seeds, and
recall is within a few points.

**About the recall figures.**
- The accepted count includes a few causes that appear as two nodes, such as the
  RG Kar killing as two nodes for one march. That raises recall slightly.
- 8 of the 29 "missed causes" are demands (a farmers' pension, no tariff hike)
  or commentary ("eyeing the coming Lok Sabha elections", a columnist's fears).
  They are not causes under the rubric. The second row of recall drops them. That
  call is mine, not a judge's.

**What is still missed** (21 genuine).
- Mobilisation calls not extracted as events: the SKM's Bharat Bandh and protest
  calls.
- Events outside this corpus: the Chennai stabbing, the Wayanad landslide.
- Grievances no extraction captured: student welfare at DU, the CBI's alleged
  failure.
- One judge error. For 2d3910 the judge rejected Mamata Banerjee's alleged
  remark as `CORRELATED_ONLY`, although its sentence reads "The protest comes
  after … allegedly used an offensive word". That is explicit wording, and the
  Phase 9b judge had accepted it. It stays as judged, and it is listed here.

## Agreement (283 double-annotated claims)

| Measure | Observed | Cohen's κ |
|---|---:|---:|
| Accept / reject | 0.979 | **0.93** |
| Relation, where both accepted (46) | 0.935 | **0.88** |
| Reject reason, where both rejected (231) | 0.922 | 0.88 |

| Relation | First | Second | Both | Specific agreement |
|---|---:|---:|---:|---:|
| TRIGGERS | 7 | 8 | 7 | 0.93 |
| MOTIVATES | 28 | 29 | 27 | 0.95 |
| ESCALATES | 7 | 7 | 7 | 1.00 |
| MOBILIZES | 1 | 1 | 1 | 1.00 |
| CONTRIBUTES_TO | 3 | 1 | 1 | **0.50** |

**Where the annotators split.**
- 6 accept/reject splits:
  - five of them are primary-reject versus second-accept;
  - four involve `INSUFFICIENT_EVIDENCE`;
  - all of them are weak relations (CONTRIBUTES_TO, ESCALATES, MOBILIZES).
- The relation confusions are CONTRIBUTES_TO↔MOTIVATES (2) and
  MOTIVATES↔TRIGGERS (1).

## Taxonomy revision

The plan expected the seven types to collapse to four or five. The measurement
supports five:

1. **Merge CONTRIBUTES_TO into MOTIVATES.** It is the only type that disagrees
   (0.50), and its confusions are all with MOTIVATES. As the plan predicted, the
   difference is confidence, and `final_strength` already carries that.
2. **Drop ENABLES.** It was never used in 1,384 judgements.
3. **Keep TRIGGERS and ESCALATES apart.** The plan expected them to merge, but
   they never were confused (both 7/7, 1.00). The "did the protest already
   exist" test is easy to apply from the text.
4. **Keep MOBILIZES and PROMPTS_RESPONSE.** They are rare but distinct.
5. **A gap: solidarity protests.** A protest held in support of another protest
   elsewhere has no clean type. Judges used ESCALATES in one batch and MOTIVATES
   in another. Name it, either as a `SOLIDARITY` type or by defining it under
   ESCALATES, before human annotation starts.

The edges keep the seven-type labels as judged. The revision applies to the
rubric for the next round, and Phase 12 can map CONTRIBUTES_TO → MOTIVATES when
loading.

## Known limits

- **AI only.** Agreement between two runs of one model overstates what two
  humans would reach. A human spot-check of a sample of accepts and rejections
  is the cheapest next validation.
- **Duplicate cause nodes.** Some causes exist as two canonical nodes, such as
  the RG Kar killing extracted once as an event and once as a condition. Both
  get accepted, so edges are over-counted per real cause. Phase 8 and 9b merges
  are judged within kind only. Cross-kind merges (event ↔ condition) are not
  attempted yet.
- **Corroboration is thin.** 152 of 156 edges rest on one outlet's text, because
  most protests are reported once in this 139-article corpus.

## Files

| File | SHA-256 |
|---|---|
| `data/evidence/events/protest-review-300.edges.v1.jsonl` (1,101 primary edges) | `e08fd9c7463a40cee015e04d5b7cd29d7e5a091896df3d1e8fd6118f44c0897a` |
| `data/evidence/events/protest-review-300.edges.v1.second.jsonl` (283) | `99853e5c8377075391b950a6b58cbd67c75260519bb351ad41bf6bd8a81c4788` |
| `data/evidence/events/protest-review-300.edges.v1.missed.jsonl` (29) | `180a2efad2e96cf030ae96790e2710c7baaba996edbdc87ade0b783afa1f4d31` |
| `data/evidence/events/protest-review-300.edges.v1.manifest.json` | `c151ad26bd3cdcfb098fc3d8fca82436e5e689da08822451a509b9fd5fdf5666` |
| `data/evidence/events/protest-review-300.edges.v1.key.json` | `4afa2b2813bb4cb2f61f98b395266d4fd3eee22b9ffd2c5c835730f91b6bfa10` |
| `data/evidence/events/protest-review-300.edges.v1.judgements.jsonl` | `14868099501556a13617b6127b41c449c9c29a1545ce67c942c055a1d813645e` |
| `data/evidence/events/protest-review-300.edges.v1.second-judgements.jsonl` | `c6dae536bb9ee5c612f65b21a7546a4b5f630b9a7412de838cb3d07357a621b9` |
| `docs/causal-annotation-rubric.md` | `10dcc8b21eeba8f1d29e2d067a65ff988cfc724200f3051d996c543dddea6728` |
