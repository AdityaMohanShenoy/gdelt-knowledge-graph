# Phase 2 — AI focal-event review of all 300 records

**These are AI labels, not human gold. No focal-event label is human-made.** By
the 2026-10-31 decision, Claude reviewed every record, recorded as reviewer
`Claude (AI)` / `label_source = ai_assisted`.

## Method

- **Rubric.** `docs/focal-event-rubric.md` covers the primary development, a
  one-sentence summary of at most 30 words, every sentence that states part of
  the development, the cohort, and when to mark `NO_FOCAL_EVENT`.
- **Readers.** Four fresh agents read every sentence of every retained article.
  Three covered pilot, train and dev (118 articles); a separate one covered test
  (21 articles).
- **What they saw.** The rubric, the headline, URL, GDELT dates, the screened
  relevance, and numbered sentences. They did not see Codex's drafts or the
  model's sentence rankings. The rankings are what Phase 6 evaluates, so showing
  them would anchor the gold labels to the system under test.
- **Validation.** Every decision was checked against the real records: all 139
  retained articles are covered, every cited sentence exists, summaries are at
  most 30 words, cohorts are valid, and every low-confidence call has notes.
- **Excluded records.** The 160 records excluded at screening became
  `UNSUITABLE`, with their screening reason as notes.
- **`262860` changes from kept to excluded.** It is the 40-word Samsung strike
  stub that screening kept. The extractor rejected it, so it has no sentences
  to cite. The handoff says the 21 extraction-rejected records stay excluded
  and their evidence must never be invented, so it is now
  `UNSUITABLE` / `INSUFFICIENT_TEXT`.

| File (`data/evidence/focal_events/`) | SHA-256 |
|---|---|
| `protest-review-300.screened.v2.packet.jsonl` (input) | `bc0ca03628cf200f9b2a96e66d598ca7febf113fca1daeb4db127cf4deb3a6ae` |
| `protest-review-300.focal.v1.packet.jsonl` (output) | `92ca07ead2756e4dc96b65c73175dbeb299b5820041a4fe7d477eeb9c43f3e43` |
| `protest-review-300.claude-focal.v1.jsonl` (summary, support, cohort, confidence, notes) | `f314b2dd25b0bc088764f81f414015e62d94116f0bb10e5d6b11676439a5dd98` |
| `protest-review-300.focal.v1.packet.manifest.json` | `7133d11ae1c0b466653ac2e1beefeb2264eef9aa6468c68de8c947544a096aa2` |

## Validation

- **Pilot, train and dev.** `evaluate --split pilot|train|dev` runs cleanly on
  the 279 records that have predictions, with 0 unreviewed. Its metrics were
  not inspected; they belong to Phase 6.
- **Test.** All 48 records pass snapshot, eligibility and support validation.
  No test metric was computed.
- **Extraction-rejected.** All 21 records without a prediction are
  `UNSUITABLE`.
- **Review page.** It loads all 300 records in Chromium with no errors.

## Results

| Split | Reviewed | Unsuitable |
|---|---:|---:|
| pilot | 35 | 27 |
| train | 59 | 83 |
| dev | 24 | 24 |
| test | 21 | 27 |
| **total** | **139** | **161** |

- **Cohorts:** `single_event` 93, `government_decision` 23, `ongoing_protest` 13,
  `multiple_events` 5, `historical_background` 5.
- **Support size:** median 7 sentences, mean 8.3. The largest sets cover long
  single-event reports, such as a bandh reported town by town or a court order
  quoted at length.
- **Confidence:** 26 of the 139 are low confidence. Most low-confidence calls
  turn on which of two developments leads, or on where the support boundary
  falls.

No retained article was found to lack a focal event, so `NO_FOCAL_EVENT` was
not used in this phase.

## Against Codex's drafts

Pilot, train and dev only, 117 articles both reviewed. Test drafts were
stripped and never seen.

| Measure | Result |
|---|---:|
| At least one support sentence shared | 107 / 117 |
| Same first support sentence | 65 / 117 |
| Codex's whole support set inside ours | 64 / 117 |
| Mean Jaccard | 0.27 |
| Mean support size: ours / Codex | 8.3 / 2.6 |

- **Support size.** Codex picked a few key sentences per article. The rubric,
  following the README, asks for every sentence that states part of the
  development. That accounts for most of the low Jaccard.
- **No overlap at all, 10 articles:** `523577`, `590719`, `234684`, `548739`,
  `592726`, `609269`, `615620`, `526710`, `596847`, `623506`. These are mostly
  cases where a different development was chosen as primary, and several are
  among our low-confidence calls.
- **Cohort agreement is 14/117, and it is not informative.** Codex labelled
  113 of the 117 articles `ongoing_protest`, effectively a default.

## Consequences for Phase 6

- **Broader support makes Top-1 and Top-3 easier to hit.** A ranked sentence
  only has to land anywhere in a larger gold set. Report support size beside
  every Top-k metric, and do not compare these numbers with metrics scored
  against Codex's narrower drafts.
- **Test metrics measure agreement with an independent AI reading.** They are
  not accuracy against people. Having a person review the 21 test articles, or
  the low-confidence calls, is the cheapest way to restore a human check.
