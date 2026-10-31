# Phase 6 — Focal-event baseline (dev)

**Status.** This is the baseline on dev, with pilot and train for context.
**Test was scored once (2026-10-31) with the final ranker v2;** see "Test
(scored once)" at the end.

**These labels are AI.** The gold labels are the AI-assisted v1 freeze, every
label `Claude (AI)`. The scores below measure agreement with an independent AI
reading, not accuracy against people.

## Inputs

| File (`data/evidence/focal_events/`) | SHA-256 |
|---|---|
| `protest-review-300.weak.v1.annotations.jsonl` (frozen labels) | `285dd20c87a41fa7a787035d337273aece4ee19763a668c8268ba4f79de36f61` |
| `protest-review-300.jsonl` (predictions) | `b727bb4ce302a3dbc1fe217acd605bdd7b5d3a2231a7776aeba6253048e23781` |
| `protest-review-300.weak.v1.dev.metrics.json` | `a4955a9f5ea6ea6feceddf70ca96db3f8db27e1a649269f4f73caa81d586b74b` |
| `protest-review-300.weak.v1.train.metrics.json` | `46d69b3f0331d8db3a71a7a1ba97fa2fb45841ab3353b374a5acbb0ac057560d` |
| `protest-review-300.weak.v1.pilot.metrics.json` | `3fd7c6913b34b0c24affd9f69e330bc3327f846b107f274198f5fd96107741ce` |

**Ranker.**
- Models: `all-mpnet-base-v2` embeddings and spaCy `en_core_web_sm`.
- Weights: headline 0.6, position 0.2, event 0.2, position decay 0.2.
- Nothing has been tuned.

## Results

Each cell is Top-1 / Top-3.

- **Random** is the expected rate of a uniformly random ranking. Larger gold
  support raises it.
- **Position** ranks earlier sentences higher.
- **Headline** ranks by similarity to the headline.

| Split | n | Gold support (share) | **Model** | Random | Position | Headline |
|---|---:|---:|---:|---:|---:|---:|
| **dev** | 24 | 9.6 (0.58) | **0.96 / 1.00** | 0.58 / 0.86 | 0.58 / 1.00 | 0.92 / 0.96 |
| train | 59 | 7.9 (0.49) | 0.81 / 1.00 | 0.49 / 0.83 | 0.64 / 0.93 | 0.81 / 1.00 |
| pilot | 35 | 9.1 (0.59) | 0.83 / 0.97 | 0.59 / 0.87 | 0.66 / 0.89 | 0.86 / 0.97 |
| all non-test | 118 | 8.5 (0.54) | 0.85 / 0.99 | 0.54 / 0.85 | 0.64 / 0.93 | 0.85 / 0.98 |

Dev Top-1 is 23/24 (Wilson 95% interval 0.80–0.99), against 22/24 for the
headline baseline. Evidence validity is 1.00 on every split. NER is not
scored, because no entity labels exist yet (Phase 3).

### Breakdowns (all 118 non-test articles)

| Subset | n | Support share | Model Top-1 [95% CI] | Random | Headline |
|---|---:|---:|---:|---:|---:|
| short (< 12 sentences) | 35 | 0.61 | 0.69 [0.52–0.81] | 0.61 | 0.71 |
| medium (12–24) | 60 | 0.55 | 0.95 [0.86–0.98] | 0.55 | 0.92 |
| long (≥ 25) | 23 | 0.39 | 0.83 [0.63–0.93] | 0.39 | 0.87 |
| hard: support share < 0.33 | 27 | 0.22 | 0.74 [0.55–0.87] | 0.22 | 0.78 |
| body COMPLETE | 100 | 0.54 | 0.92 [0.85–0.96] | 0.54 | 0.92 |
| body LIMITED | 18 | 0.50 | 0.44 [0.25–0.66] | 0.50 | 0.44 |
| relevance PROTEST | 93 | 0.56 | 0.87 [0.79–0.92] | 0.56 | 0.84 |
| relevance PROTEST_LINKED | 25 | 0.47 | 0.76 [0.57–0.89] | 0.47 | 0.88 |
| cohort single_event | 78 | 0.59 | 0.87 [0.78–0.93] | 0.59 | 0.85 |
| cohort government_decision | 19 | 0.47 | 0.84 [0.62–0.94] | 0.47 | 0.89 |
| cohort ongoing_protest | 13 | 0.51 | 0.85 [0.58–0.96] | 0.51 | 0.85 |
| cohort multiple_events | 5 | 0.32 | 1.00 [0.57–1.00] | 0.32 | 0.80 |
| cohort historical_background | 3 | 0.15 | 0.00 [0.00–0.56] | 0.15 | 0.67 |

## Core-sentence target (v2, added 2026-10-31)

The full-support metric above saturates, so a harder target was added. Each of
the 118 non-test reviewed articles now has one **core sentence**: the
supporting sentence that, on its own, best states the development
(`docs/core-sentence-rubric.md`).
- **How it was labelled.** Three fresh agents chose it from the gold support,
  seeing no model ranking. 22 calls are low confidence.
- **Shape.** The core is the first supporting sentence in 97 of 118 articles.
- **Test.** The 21 test articles have no core sentence yet; they are left for
  the human test review.
- **Scoring.** `evaluate` scores it as `core_sentence`, with its own random
  (1/N), position and headline baselines.

| File (`data/evidence/focal_events/`) | SHA-256 |
|---|---|
| `protest-review-300.weak.v2.annotations.jsonl` (frozen v2 = v1 + core sentences) | `b3e2425f3b24dbe7d336cfd73fc9fc9989319d12993639a097cc528f8061eac4` |
| `protest-review-300.weak.v2.annotations.manifest.json` | `df646d5e219cfd498134e19cf28f232aa71db818207afc9def6674869b0132dc` |
| `protest-review-300.claude-core.v1.jsonl` (core choices, confidence, notes) | `f3704c813db665a822c9748cb44946727b0411c4d432ed83e5d29b5251560113` |
| `protest-review-300.weak.v2.dev.metrics.json` | `ce39db8340472d11b39c21224f0a42b073ee4bacbd1c11e9cf1066f923e088fa` |
| `protest-review-300.weak.v2.train.metrics.json` | `78e799431814bbdfeb7aaa7ba832adfb78b4f776c6f8b4bb4a52f4765e86ed66` |
| `protest-review-300.weak.v2.pilot.metrics.json` | `39941f7a796ea2448b3fa542f4eeb6c11b3bb0a453b66ef285c09effab1652cc` |

Core sentence, Top-1 / Top-3, with 95% Wilson intervals on Top-1:

| Subset | n | **Model** | Random | Position | Headline |
|---|---:|---:|---:|---:|---:|
| **dev** | 24 | **0.71** [0.51–0.85] / 1.00 | 0.07 / 0.21 | 0.50 / 1.00 | 0.58 [0.39–0.76] / 0.88 |
| train | 59 | 0.66 [0.53–0.77] / 0.88 | 0.08 / 0.24 | 0.58 / 0.81 | 0.58 [0.45–0.69] / 0.85 |
| pilot | 35 | 0.77 [0.61–0.88] / 0.89 | 0.08 / 0.25 | 0.51 / 0.83 | 0.51 [0.36–0.67] / 0.83 |
| **all non-test** | 118 | **0.70** [0.62–0.78] / 0.91 | 0.08 / 0.23 | 0.54 / 0.86 | 0.56 [0.47–0.65] / 0.85 |
| long (≥ 25 sentences) | 23 | 0.74 / 0.96 | 0.03 / 0.09 | 0.43 / 0.91 | 0.52 / 0.70 |
| body LIMITED | 18 | 0.33 / 0.78 | 0.14 / 0.41 | 0.22 / 0.50 | 0.22 / 0.89 |

**Paired comparison, pooled non-test.** On core Top-1, the model is right where
headline similarity is wrong in 23 articles, and the reverse happens in 6.
A two-sided sign test gives **p = 0.0023**. Dev alone (24 articles) is too
small to show this by itself.

## Ranker v2 — headline-echo filter (added 2026-10-31)

`RankingConfig.drop_headline_echoes` (in `pipeline/focal_ranking.v2.json`)
ranks a sentence last when at least 80% of its content words are headline
words. The default stays off, so the v1 run reproduces exactly from its saved
config; that was checked for all 279 rankings.

**Choosing the rule (dev only).**
- **Lexical overlap at 0.6–0.9: no effect on dev, and no core sentence
  flagged.** Dev contains no echo errors, so it cannot pick a threshold. 0.8
  was fixed in advance as a conservative definition, rather than chosen by
  train or pilot scores.
- **Cosine similarity to the headline: rejected.** At 0.80–0.90 it hurt dev
  core Top-1 (as low as 0.54), because it also flags genuine lead sentences
  that paraphrase the headline.

**The re-run.** Extraction was re-run with the v2 config.
- Text and sentence segmentation are identical for all 279 articles, and every
  frozen label validates against the new predictions.
- Library drift is negligible: headline similarity moved at most 6.6e-7, and
  event relevance did not move.
- The filter flagged echoes in 34 articles and changed the top sentence in 21.

| File | SHA-256 |
|---|---|
| `pipeline/focal_ranking.v2.json` | `53f32d3066b85bbee656ec6e835db0b3f9743eb734077a321777d56987f02b2b` |
| `protest-review-300.v2.jsonl` (v2 predictions) | `e4d85346809e8eb876ec1f55997fca49ec82728d3586dae3ca9efa5b954fd6fb` |
| `protest-review-300.v2.manifest.json` | `09f06500519c931dd5ef763fa2bde6373237d8f39addfe9b547181a6fdf9c0da` |
| `protest-review-300.v2.weak.v2.dev.metrics.json` | `1b2d8f10e489750ef5bcc27aa03c658d92267fed65fee26ac7116ba3083a9f4c` |
| `protest-review-300.v2.weak.v2.train.metrics.json` | `04f31db5ca644ce280a353a1bd1fa597c0c5df633b648d9e2c2c8449ee1ce9eb` |
| `protest-review-300.v2.weak.v2.pilot.metrics.json` | `4cf9d84bf753c98c5c3460eaaba0c3d7cb9ad96df2336d1dbb38bc8c82969e3d` |

| Subset | Ranker | Core Top-1 [95% CI] | Core Top-3 | Support Top-1 |
|---|---|---:|---:|---:|
| dev (24) | v1 | 0.71 [0.51–0.85] | 1.00 | 0.96 |
| dev (24) | **v2** | 0.71 [0.51–0.85] | 1.00 | 0.96 |
| train + pilot (94, check only) | v1 | 0.70 [0.60–0.79] | 0.88 | 0.82 |
| train + pilot (94, check only) | **v2** | **0.77** [0.67–0.84] | 0.88 | 0.88 |
| all non-test (118) | v1 | 0.70 [0.62–0.78] | 0.91 | 0.85 |
| all non-test (118) | **v2** | **0.75** [0.67–0.82] | 0.91 | 0.90 |

Paired over non-test on core Top-1, v2 gains 6 articles and loses none (sign
test p = 0.031). The six gains are headline-echo errors from the analysis
below.

**v2 is the ranker from here on.**

Dev's seven remaining core misses are a different problem:
- **Six: a different supporting sentence of the same event ranked first.** This
  is fine-grained, and partly reflects how subjective the core-sentence label
  is.
- **One: a photo caption** (`590691`). Captions are the next error class to
  address. No marker-based caption rule would catch this one.

## Findings

1. **The ranker beats its baselines once the target can tell them apart.** On
   the core sentence it reaches Top-1 0.70, against 0.56 for headline
   similarity, 0.54 for position and 0.08 for chance (p = 0.0023, paired).
   Combining headline, position and event signals helps.
2. **Correction.** An earlier version of this file concluded that the ranker
   was "level with headline similarity". That conclusion came from the
   saturated full-support metric, not from the ranker. Full support covers 54%
   of each article's sentences, so random ranking already gets Top-1 0.54, and
   every method's Top-3 is about 1.00. Use full-support Top-k only as a sanity
   check.
3. **Limited bodies remain the weak spot.** Partial or preview texts score core
   Top-1 0.33, though that is still above random (0.14), position and headline
   (both 0.22).
4. **Headline echoes are the main remaining error.** See the error analysis
   below. They cost core Top-1 directly.

## Error analysis — every full-support Top-1 miss (18 of 118 non-test)

| Kind | n | Articles | What happened |
|---|---:|---|---|
| **Headline echo** | 11 | `420893` `380787` `380384` `422243` `421237` `420834` `421597` `421983` `422235` `421838` `420243` | The model picks sentence 1, a repeat or near-repeat of the headline that does state the development. The rubric excludes headline repeats from support, because they add no evidence beyond the headline. In `420243`, sentence 1 is word-for-word identical to gold sentence 3, an extractor duplication. |
| **Judgement call** | 3 | `422283` `506010` `625419` | The model's sentence belongs to the story, and the miss turns on the support boundary or which development leads. |
| **Real error: background first** | 3 | `592726` `234684` `592667` | Background or history ranked first, e.g. "More than four years ago…", "has been protesting for more than three years". |
| **Real error: caption** | 1 | `590691` (dev's only miss) | A photo caption ("Stray cattle feeding on garbage…") ranked first. |

Top-3 misses: 1 of 118 (`592726`, a 114-sentence analysis piece).

## Decisions and next steps

1. **Headline echoes: decided.** Keep excluding them from gold support, and
   treat a ranker that picks one as making an error. The fix belongs in the
   ranker: drop sentences that repeat the headline before ranking.
2. **Harder target: done.** The core sentence (v2) is the tuning target from
   here on.
3. **Echo filter: done (ranker v2).** Next, tune on dev only, against core
   Top-1: captions, then re-weighting. Report each change against the random,
   position and headline baselines. Pilot and train may be pooled for error
   analysis, but are not used to pick settings.
4. **Leave test untouched.** It is scored once, after the human test review
   (which should add core sentences for its 21 articles) and a v3 freeze.

## Test (scored once, 2026-10-31)

**How the test labels were made.**
- **A blind second reading.** A fresh AI reviewer re-labelled the 21 reviewed
  test articles from scratch (main event, support, cohort, core sentence),
  seeing no earlier labels and no model rankings.
- **Agreement with the Phase 2 labels was very high:**
  - 21/21 kept
  - same first supporting sentence in 21/21
  - mean support Jaccard 0.89
  - cohort 19/21
  - every blind core sentence inside the Phase 2 support
- **The result.** Phase 2's summary and support were kept, and the blind core
  sentences were added, giving frozen **v3**.
- **A human spot-check.** The user reviewed a few test articles by hand and
  found them appropriate. Which ones was not recorded, so every label is still
  AI.

| File (`data/evidence/focal_events/`) | SHA-256 |
|---|---|
| `protest-review-300.test-blind-review.jsonl` | `f48d1a2043945c7fb4e6ae96676ff621196816b1b6fe5774c878d7015d2b97ff` |
| `protest-review-300.weak.v3.annotations.jsonl` (v2 + test core sentences) | `100cbfa34758c90cdcb1f5bcce3a555329d8fc8d8c668deee1d653bded3da079` |
| `protest-review-300.weak.v3.annotations.manifest.json` | `609b651e649d6d1ed4aac34b509beba2a7876b03c1fb2c2666ff963aed2abdde` |
| `protest-review-300.v2.weak.v3.test.metrics.json` | `5cfcb0456fa9d57227c879a5ba676a75050e5c4c42794df7820ab6ce717e1a7f` |

| Test (21) | Final ranker (v2) | Random | Position | Headline |
|---|---:|---:|---:|---:|
| **Core Top-1** | **0.67** [0.45–0.83] | 0.09 | 0.48 | 0.52 |
| Core Top-3 | 1.00 | 0.26 | 0.90 | 0.81 |
| Full-support Top-1 | 0.86 (v1: 0.76) | 0.53 | — | — |

Evidence validity is 1.00.

**Reading.** On held-out articles the ranker beats every baseline, as it did on
dev (0.71) and non-test (0.75). The headline-echo filter shows on test as a
full-support Top-1 gain, from 0.76 to 0.86. Core Top-1 is the same for v1 and
v2 on test. With 21 articles the interval is wide: this confirms the
direction, not a precise level.

**Test is now spent.** Any further ranker change must be judged on dev, and
reported on test only together with this result.
