# Phase 9 — Candidate causes, and the evidenced branching factor

**Status: the acceptance check is met.**
- **Retrieval:** every protest seed but one has a stored candidate set, and the
  queue serves candidates across seeds. 663 unreviewed claims cover 63 seeds.
- **GATE 11 re-measured validly:** about 2 named causes per protest, against a
  threshold of 4, so human review of causal edges is affordable.
- **The main finding:** retrieval recall is 0.46. Most missed causes are
  **conditions and grievances, not events**, so the graph needs condition nodes.

## Method

`pipeline/22_retrieve_causes.py`, with the logic in `pipeline/causal_candidates.py`.
It deliberately does not use the GDELT-group scorer: GATE 11 found it retrieves
no textually supported cause.

- **Seeds (63).** Each is an asserted 2024 protest (type 14) that is an article's
  focal event, in an article screened `PROTEST`.
- **Window.** A candidate cause is any canonical event, of any type, whose date
  is up to 7 days before the seed, or which is still under way when the seed
  happens. Nothing after a seed can be its cause.
- **Proposal.** A candidate qualifies if any one of these holds:
  - it is reported in the same article as the seed
  - it shares actor words
  - it shares place words
  - one event's sentences contain the other's actor, target or place words
  - the closest pair of sentences has local `all-mpnet-base-v2` similarity
    ≥ 0.45

  These signals **propose**; none is evidence of cause.
- **Storage and queue.** Every candidate is stored as a claim with
  `verdict: unreviewed`, together with the evidence sentences of both events.
  The queue is round-robin across seeds, ordered within a seed by a retrieval
  score that is never a confidence; GATE 3.5 showed such scores cannot tell
  real pairs from shuffled ones.

| File | SHA-256 |
|---|---|
| `data/evidence/events/protest-review-300.claims.v1.jsonl` (663 claims, queue order) | `3c82183f573493c1d7de75b8cb259fdb9e8d8d9a7f32d2188a4fb474cc11132d` |
| `data/evidence/events/protest-review-300.claims.v1.manifest.json` | `fce021e6682d4823c4d081d13b389289ef44ac7f43e6fcd17835b28c4d2fddaa` |
| `data/evidence/events/protest-review-300.claims.v1.cause-review.jsonl` | `f5ffa3044acce436019184b3be425e93f183a54a6ff2f7cc828297aae8511c60` |
| `data/evidence/events/protest-review-300.claims.v1.cause-review-key.json` | `c906b8d5fabecd0016925920eb335de89fb66995b0b71e9705056091d846ccb4` |
| `docs/cause-rubric.md` | `41964fa324171c8a4a95c2294bc8ead050d8d32cab72961d09827c80649edc11` |

## Output

- **663 claims** over 63 seeds: median 8 per seed, mean 10.5, maximum 42.
- **The one seed with no candidate** is a 31 January fishermen's protest; no
  event in this corpus falls in its window.
- **Signals present on claims:** same article 220, actor 156, place 49, shared
  names 549, similarity ≥ 0.45 219.
- **Candidate types:** protest 279, demand 130, coercion 78, untyped 75 (mostly
  decisions), meeting 42, and others. Upstream non-protest events are included
  on purpose.
- **Lag:** 254 candidates are on the same day as the seed, and the rest are
  spread across 1–14 days. Lags above 7 come from ongoing events whose range
  covers the seed.

## Re-measuring the evidenced branching factor (GATE 11)

Fresh AI judges took **20 seeded-random seeds (221 candidates)** under
`docs/cause-rubric.md`.
- **Accepting a cause** needed an inspectable textual link ("because of",
  "against", "in response to", policy → reaction, escalation, mobilisation),
  with an exact quote. It could never rest on timing, actors, topic or wording.
- **Missed causes:** judges also listed every cause the protest's own article
  names that no candidate represents.
- **Blinding:** judges saw no retrieval signals or scores.

| Measure | Result |
|---|---:|
| Accepted causes | 18 of 221 candidates (8%) |
| **Evidenced causes retrieved per seed** | **mean 0.9**, median 1, max 5; 11 of 20 seeds have at least 1 |
| Named causes the articles state, per seed (found + missed) | **about 1.95** |
| **Retrieval recall of named causes** | **0.46** (18 / 39) |
| Relations | ESCALATES 5, MOTIVATES 5, TRIGGERS 3, PROMPTS_RESPONSE 3, MOBILIZES 2 |
| Lag of accepted causes | 10 same day; the rest 1–7 days |

**GATE 11: passes, validly this time.** Protests name about 2 causes each, well
below the threshold of 4. Reviewing every candidate costs about 10 claims per
seed, so human verification of edges in Phases 10–11 is affordable. The
measurement is AI-judged on 20 seeds and is a direction, not a precise rate.
Accepted counts include two pairs of duplicate events that both represent one
cause.

**Which signals found the real causes.**
- **Shared names** were present on 17 of 18.
- **Same article** on 10, similarity on 12, actors on 4, place on 1.
- **Queue position.** Half the accepted causes ranked in a seed's top 3, but
  some ranked 12–20. The queue order helps, but reviewers must still see each
  seed's whole list.

**Examples of accepted causes.**
- The West Bengal junior doctors' hunger strike: *"Their agitation began after
  an on-duty postgraduate trainee was raped and murdered inside state-run RG
  Kar Medical College and Hospital on August 9."* The cause is the RG Kar
  killing, which Phase 8 had merged from 6 reports. TRIGGERS.
- The Salem doctors' boycott: *"In response to a call from the Indian Medical
  Association (IMA) for a one-day boycott."* MOBILIZES.
- The BJP counter-protest in Bengaluru: answering the Congress protest in New
  Delhi. PROMPTS_RESPONSE.
- The CAA protests: erupting after the government implemented the law.
  TRIGGERS.

## Why 21 named causes were missed (the main finding)

| Kind of missed cause | n | Examples |
|---|---:|---|
| **Condition, grievance or standing policy, not an event** | ~15 | the ongoing Delhi water crisis; rising violence against doctors; a Rs 1 crore PG surety bond; no ACP allowance; alleged NEET irregularities; microfinance exploitation; abolished reservations; a fee hike; alleged corruption |
| **Remark or statement** | 2 | BJP workers calling a Sikh officer "Khalistani"; Mamata Banerjee's alleged word against Modi |
| **In the data, but outside the 7-day window** | 3 | the RG Kar killing, weeks before two later protests; Kejriwal's arrest, 17 days before an AAP fast |
| **Not in this corpus** | 1 | the stabbing of an oncologist in Chennai |

**Consequences for the plan.**
1. **Condition nodes are needed, not optional.** About three quarters of the
   missed causes are persistent states, which an event-only graph cannot
   represent. That is the case the 2026-09-17 plan made for Phase 4 (condition
   nodes), which was deferred. Bring it back before relying on recall.
2. **Statements are events here.** Phase 7's rubric excluded opinions. A
   specific remark by a named party on a date (CAMEO 01, 11, 12) should be
   extracted, because protests respond to remarks.
3. **The window needs a longer grievance stratum.** Seven days misses triggers
   weeks back. Add a 3-week to 6-month window for grievance-type causes, as in
   the deferred strata.
4. **A larger corpus would help:** one named cause simply is not among these
   139 articles.
