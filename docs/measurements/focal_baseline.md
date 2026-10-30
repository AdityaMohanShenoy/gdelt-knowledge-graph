# Phase 6 — Focal-event baseline (dev)

**Status.** This is the baseline on dev. Pilot and train are shown for context,
and pooled, because 24 dev articles are too few to break down. **Test has not
been scored.** It waits for the human test review and is then scored once.

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
3. **Next: tune on dev only, against core Top-1.** Filter headline echoes and
   captions, then try re-weighting. Report each change against the random,
   position and headline baselines. Pilot and train may be pooled for error
   analysis, but are not used to pick settings.
4. **Leave test untouched.** It is scored once, after the human test review
   (which should add core sentences for its 21 articles) and a v3 freeze.
