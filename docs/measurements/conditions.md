# Condition nodes, remarks and the grievance window

**Status: done; retrieval recall rose from 0.46 to 0.92 on the same 20 seeds.**
Phase 9 found that most causes the articles name are standing conditions or
remarks, or fall outside the 7-day window. This adds all three. Every label here
is AI (`Claude (AI)`, `ai_assisted`). The recall figure is an upper estimate,
for reasons given below.

## What was built

- **`pipeline/conditions.py`, `pipeline/23_extract_conditions.py`**
  - `apply` turns AI extraction into records whose every field is a verbatim
    span of its sentence, as for event mentions.
    - **Conditions** carry holders, places, `since`/`until`, a kind and a role
      (`protest_cause` / `context`).
    - **Remarks** (CAMEO 01, 11, 12, 13: statements, criticism, rejection,
      threats) become event mentions with `origin: remark_added`.
  - `pairs` proposes cross-article condition pairs for review, using mpnet
    similarity ≥ 0.55, or ≥ 0.40 with a shared holder or place word.
  - `build` merges only judged-same pairs, as Phase 8 does.
- **Validity.** A condition is observed on its article's report date.
  - When the text states a start or end, that is used (`start_stated`).
  - Otherwise its window is a wide, low-confidence guess: 180 days back and 30
    days ahead.
  - Only 7 of 244 conditions state a start, and none states an end.
- **Retrieval v2.** Changes to `pipeline/22_retrieve_causes.py` and
  `causal_candidates.py`:
  - **Conditions** are candidates when their validity window covers the seed's
    day.
  - **Events** are now candidates up to 180 days back. Beyond 7 days a candidate
    needs either the same article, or similarity ≥ 0.45 together with a shared
    name, actor or place. A single weak signal would propose most of the corpus.
  - Conditions use the same stricter rule.
  - Claims carry `cause_kind`. Conditions have no `lag_days`, because their
    start is usually the guessed one.
- **Date fix.** `MONTH_DAY` read "May 2024" as May 20, and "16th February 2024"
  as February 20. A `(?!\d)` guard fixes it, and `since` spans now resolve a
  month and year to the first of the month.
  - The fix affected 6 event mentions and 1 condition.
  - Re-pairing produced 1 new in-band pair, which I judged `different`, and
    dropped 2 already-judged `different` pairs.
  - Canonical clusters are unchanged. For the 20 measured seeds, the only change
    in candidates is one already judged `n`.
  - So the measurement below, made on the v2 artifacts, stands. v4 and claims v3
    are the current artifacts.

## Extraction (139 reviewed articles)

| Output | n |
|---|---:|
| Conditions | 244 (protest_cause 187, context 57) |
| Remarks added as events | 213 (criticise 127, statement 43, threaten 25, reject 18) |
| Values dropped as not verbatim | 0 |

**Audit.** Fresh judges took 20 seeded-random articles under
`docs/condition-audit-rubric.md`.

| Measure | Result |
|---|---:|
| Conditions valid | **24 / 33 (73%)** |
| Remarks valid | **28 / 28** |
| Kind / role correct (valid conditions) | 23 / 24, 24 / 24 |
| Holders: correct / empty / wrong | 12 / 11 / 1 |
| Places: correct / empty | 12 / 12 |
| Protest-cause conditions missed | 7 in 20 articles |

**The main extraction error is demands recorded as conditions.** Seven of the 9
rejected conditions are demands ("legal guarantee of MSP", "inclusion of
Marathas in OBC") with no stated state behind them. One is an accusation and one
names a case ("the so-called liquor scam").
The other weakness is empty holders and places where the text names them. This
weakens the shared-holder signal, but similarity still carries retrieval.

## Merging

**Conditions.** Judges reviewed 244 of the 792 candidate pairs under
`docs/same-condition-rubric.md`: all 144 scoring ≥ 0.65, 60 sampled from
[0.55, 0.65), and 40 sampled below.

| Band | same / judged |
|---|---:|
| ≥ 0.65 | 102 / 144 |
| 0.55–0.65 | 2 / 60 |
| < 0.55 | 1 / 40 |

- The result is **200 canonical conditions**: 21 merged, 19 seen by more than
  one outlet, and 2 flagged CONFLICT by union-find chains.
- The largest are the MSP guarantee (14 reports), threats to doctors' lives (5,
  CONFLICT), NEET irregularities (5), unfulfilled promises (4, CONFLICT),
  Haryana's cut to Delhi's water share (3), the excise policy case (3), and
  reduced devolution of funds (3).
- **Unjudged pairs.** 217 unjudged pairs in [0.55, 0.65) were left unmerged. At
  the sampled rate (2 / 60), that misses about 7 merges. Below 0.55 the sampled
  rate is 1 / 40.

**Remarks into canonical events.** The 43 new in-band event pairs involving
remarks were judged: 8 same, 35 different. Canonical events v3 has 1,073 events,
28 of them merged.

## Retrieval v2

1,915 claims over 63 seeds, against 663 in v1:

| Measure | v1 | v2 |
|---|---:|---:|
| Claims | 663 | 1,915 (285 conditions) |
| Per seed: median / mean / max | 8 / 10.5 / 42 | 27 / 30.4 / 86 |

Every v1 candidate for the 20 measured seeds is still retrieved, including all
18 accepted causes.

## Recall on the same 20 seeds

Judges saw each seed's article, its new candidates (438 in all), and the causes
the Phase 9 judges had listed as missed. They worked under
`docs/recall-rubric.md`:
- **Part A:** judge each new candidate under the cause rubric, with an exact
  quote for every `y`.
- **Part B:** map each missed cause to the candidates that represent it.

| Measure | Result |
|---|---:|
| Missed causes now retrieved | **18 / 21** |
| **Retrieval recall of named causes** | **0.92** (36 / 39), up from 0.46 |
| …found through a condition | 16 (15 conditions only, 1 event and condition) |
| …found through a remark event | 2 (the "Khalistani" remark; Mamata Banerjee's word against Modi) |
| Precision of new candidates: conditions | 34 / 127 (27%) |
| Precision of new candidates: events | 15 / 311 (5%) |
| Accepted new events beyond 7 days | 12 (lags 8–66 days; e.g. Kejriwal's arrest, 13 days before the AAP fast) |

**Still missed (3).**
- The Chennai oncologist stabbing. It is not in this corpus.
- Delhi University student welfare issues. No extraction captured them.
- The RG Kar killing, for one later protest. It is in the data, but the strict
  far-candidate rule did not propose it for that seed. It was found for the
  other seed.

**Why 0.92 is an upper estimate.**
1. **The Part B judges were not blind to the target.** They knew which causes to
   look for. Part A still required an exact quote showing the link, and every
   mapped candidate had to be a `y`, but knowing the target makes a borderline
   `y` easier. Examples:
   - a1faed:n32 is a condition read off another protest's sentence;
   - e308c4:n15 is Kejriwal's arrest extracted as a condition.
2. **The denominator is Phase 9's 39 named causes.** New `y` candidates that
   name causes the earlier judges did not list are not counted. There are 49 of
   them in total, including earlier stages of the same dispute and grievances
   aired at the protest.
3. **Labels are AI-only,** on 20 seeds. The result is a direction, not a rate.

**Cost.** Review load roughly triples, to about 30 candidates per seed, at about
11% precision. Most of the noise is other protests on the same topic, pulled in
by the 180-day stratum. Conditions are the useful addition: 27% precision, and
they account for 16 of the 18 recovered causes. If review cost matters, the
first things to tighten are the far-event rule and the condition fallback window.

## Files

| File | SHA-256 |
|---|---|
| `data/evidence/events/protest-review-300.conditions-remarks.extraction.v1.jsonl` | `7d64426cf7826a653592f8dbd2fdf1cadcd3788e7b94186158222a0adb64c06f` |
| `data/evidence/events/protest-review-300.conditions.v1.jsonl` | `ff3cf9d5e30a038d4766002771ce2ae72ca9f075319acfedef37b3dcb97f3e2a` |
| `data/evidence/events/protest-review-300.conditions.v1.mentions.jsonl` (v2 mentions + remarks) | `07bd899fc40f795ad360e0a32cae265db6e458562da773492d4f64e223864798` |
| `data/evidence/events/protest-review-300.conditions.v1.audit.jsonl` | `d44540848a61079f280038cede04f894286b0471de4e886230c40e65e8c1a50c` |
| `data/evidence/events/protest-review-300.condition-pairs.v1.json` | `a47c4c053ade0aeb97cab2c1509503aca98f085d61e82f2496cf63f286ea5e4d` |
| `data/evidence/events/protest-review-300.condition-pairs.v1.decisions.jsonl` | `b7598926c18e24d6df026ccd8cd6fb457eb82e71c252cab0366157c4e6bfadb9` |
| `data/evidence/events/protest-review-300.canonical-conditions.v1.jsonl` | `7984e38e390732aa90cb53980841b44f127b44ed81817c051bec198e59c5b58e` |
| `data/evidence/events/protest-review-300.pairs.v3.json` | `ec9c9f0ec31d66224f38be6b3d86286830c7274b175a4c7bb635ec75782ea5bd` |
| `data/evidence/events/protest-review-300.pairs.v3.decisions.jsonl` | `bd2c22c3b41a8633a586e494459020af1fa6ebb88a9527e3d2606570db377c4d` |
| `data/evidence/events/protest-review-300.canonical.v3.jsonl` | `63be689001e1008afc50c315dd14a0fec3352210b8bffbfee86dc35149cd775d` |
| `data/evidence/events/protest-review-300.claims.v2.jsonl` (measured) | `46e93c4ae46068cb9da4f0d2dc91dcbbd46122fa4eee155c448981a558c46207` |
| `data/evidence/events/protest-review-300.claims.v2.recall-review.jsonl` | `a6fc4a11890f891041ca38da565041ccbc624a773b001dbcdfb72c752d0c46da` |
| `data/evidence/events/protest-review-300.claims.v2.recall-review-key.json` | `caaf9d5530a1f527c55f03f18857807fdc95f7f9644fbd4fb8d930b2aba9585a` |
| `data/evidence/events/protest-review-300.pairs.v4.json` (date fix) | `7acc1523dd9105d2ada456e829423376872c5605db35f7cd5bcece1896a44910` |
| `data/evidence/events/protest-review-300.pairs.v4.decisions.jsonl` | `085db0d262b7074ddeb2f4cba26a2073debae7dab025c1d7282ab8a89ba409cf` |
| `data/evidence/events/protest-review-300.canonical.v4.jsonl` (current) | `0067ecbec6b4c60bd05e14cac6369b6e384378e6a6bdcd72a5e3c7381354d4ef` |
| `data/evidence/events/protest-review-300.claims.v3.jsonl` (current) | `0045b550ffc3703588b3673fb3c44f9744abece3742c523db1db766996acb751` |
| `docs/condition-remark-rubric.md` | `ed96df0ef3ddf25470fbcfb84b823fbbd90ef06d15f7f20f6514de6487fa216b` |
| `docs/same-condition-rubric.md` | `8ddf9fe1710a3ba58e9c132a01e483a133153a3068364176e679964ab8ca95a2` |
| `docs/condition-audit-rubric.md` | `245d7b9d52b87f0b652cc6ce8298e878c869124f481712da52129fedc9785746` |
| `docs/recall-rubric.md` | `d66b253265c8a0ab12a4a4b03dee9b64a60f07c28c162fe0e3e52711826e64f7` |
