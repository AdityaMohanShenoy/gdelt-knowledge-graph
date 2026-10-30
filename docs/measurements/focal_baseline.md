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

## Findings

1. **The model does not beat headline similarity.** Pooled Top-1 is 0.85 for
   both. On harder subsets the headline baseline is level or ahead:
   - long articles: 0.87 vs 0.83
   - hard cases (support under a third): 0.78 vs 0.74
   - protest-linked articles: 0.88 vs 0.76
   - historical background: 2/3 vs 0/3

   The position and event components (0.4 of the weight) add nothing
   measurable and may cost a little.
2. **The metric is near saturation.** Gold support covers 54% of an article's
   sentences on average, so random ranking already gets Top-1 0.54 and Top-3
   0.85. Top-3 is about 1.00 for every method and cannot separate them.
3. **Limited bodies are at chance.** Partial or preview texts score Top-1 0.44
   against a random 0.50, for the model and the headline baseline alike.
4. **Short articles are barely above chance:** 0.69 against a random 0.61.

## Error analysis — every Top-1 miss (18 of 118 non-test)

| Kind | n | Articles | What happened |
|---|---:|---|---|
| **Headline echo** | 11 | `420893` `380787` `380384` `422243` `421237` `420834` `421597` `421983` `422235` `421838` `420243` | The model picks sentence 1, a repeat or near-repeat of the headline that does state the development. The rubric excludes "repeated headline fragments" from support, so these count as misses. In `420243`, sentence 1 is word-for-word identical to gold sentence 3, an extractor duplication. |
| **Judgement call** | 3 | `422283` `506010` `625419` | The model's sentence belongs to the story, and the miss turns on the support boundary or which development leads. |
| **Real error: background first** | 3 | `592726` `234684` `592667` | Background or history ranked first, e.g. "More than four years ago…", "has been protesting for more than three years". |
| **Real error: caption** | 1 | `590691` (dev's only miss) | A photo caption ("Stray cattle feeding on garbage…") ranked first. |

Counting headline echoes as hits, pooled Top-1 is about 0.94 (111/118). Either
way, the model and the headline baseline stay level.

Top-3 misses: 1 of 118 (`592726`, a 114-sentence analysis piece).

## What this means, and the decisions it needs

The ranker is not yet better than its strongest single input, and the
evaluation as labelled is too easy to show a difference. Before Phase 7 relies
on it:

1. **Decide the headline-echo policy (a labelling decision).** A body sentence
   that repeats the headline is real text that states the event. Either:
   - count it as support, which means relabelling dev, train and pilot by rule.
     This is cheap and mechanical, but it makes the metric even easier; or
   - keep excluding it and drop headline echoes from the ranker's candidates.
     That is a pipeline change, tuned on dev.
2. **Add a harder target before tuning.** Mark one *core sentence* per article:
   the single body sentence that best states the development. Top-1 against
   that is not saturated, and separates the model from the baselines. It costs
   one label per retained article.
3. **Tune on dev only.** Try headline-only and position-down weightings, and
   filtering captions and echoes. Report each change against the random and
   headline baselines, and never against test.
4. **Leave test untouched** until the human test review and a v2 freeze; then
   score it once.
