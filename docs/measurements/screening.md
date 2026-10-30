# Phase 1 — AI screening of the pilot, train and dev records

**These are AI decisions, not human gold labels.** By the 2026-10-31 decision,
Claude screened the 252 pilot, train and dev records. The 48 test records are
untouched and are screened by a human, blind.

## Method

- **Rubric.** `docs/screening-rubric.md` defines relevance, body quality, scope,
  the order of exclusion reasons, and when to flag low confidence.
- **Readers.** Six independent agents each read the complete saved text of
  about 42 articles, roughly 19,000 words per batch. Each agent saw only the
  headline, text, URL, GDELT dates and the screener's word count. None saw
  Codex's proposals.
- **Validation.** Every decision was checked against the allowed values and the
  exclusion order, and all 252 IDs are present exactly once.
- **One normalization.** The 24 records with no usable body had relevance guessed
  from the URL or headline, inconsistently across agents. All 24 were set to
  `UNCERTAIN`. They are excluded as `INSUFFICIENT_TEXT` regardless, and the
  agents' guesses are kept in the sidecar.
- **Storage.** Decisions are written as `eligibility` (`REVIEWED`, reviewer
  `Claude (AI)`), the shape the review page's **Save screening** produces.
  Article snapshots and Codex's event drafts are unchanged.

| File (`data/evidence/focal_events/`) | SHA-256 |
|---|---|
| `protest-review-300.splits.packet.jsonl` (input) | `f51c60aa2f4529105c0afb0976fa4e6435067a4ede98df025b47186c4cb99477` |
| `protest-review-300.screened.packet.jsonl` (output) | `dad25a9d727e9000611b26479e0e8b63b4d9cf147f427ae20627eee52f84c18b` |
| `protest-review-300.claude-screening.jsonl` (reasons, confidence, Codex comparison) | `a1dd94cca87d20acb3df5dd7697db3da256eff126ee08575f13cc607cb109038` |
| `protest-review-300.screened.packet.manifest.json` | `b84157b176f100c9e802e5af42803793709cd31e1d337b00ff64fc9f1f0cdf1e` |
| `docs/screening-rubric.md` | `87c4340be3d77f3aa97560a14587d3bad9642a4c138152cd11ceca21286ec054` |

The review page loads the screened packet in Chromium with no errors.

## Results

| | Kept | Excluded |
|---|---:|---:|
| pilot (62) | 34 | 28 |
| train (142) | 60 | 82 |
| dev (48) | 24 | 24 |
| **total (252)** | **118** | **134** |

- **Relevance:** `PROTEST` 99, `PROTEST_LINKED` 33, `UNRELATED` 96, `UNCERTAIN` 24.
- **Body quality:** `COMPLETE` 189, `LIMITED` 39, `INSUFFICIENT` 24.
- **Scope:** `INDIA_2024` 203, `OUT_OF_SCOPE` 26, `UNCERTAIN` 23.
- **Exclusion reasons:** `UNRELATED` 96, `INSUFFICIENT_TEXT` 24, `OUT_OF_SCOPE` 10,
  `NO_FOCAL_EVENT` 4. An article that is both unrelated and out of scope is
  recorded as `UNRELATED`, per the rubric's order.
- **Confidence:** 59 of the 252 decisions are low confidence.

## Against Codex's proposals

| Label | Agreement |
|---|---:|
| Keep/exclude | 197 / 252 (78%) |
| Scope | 222 / 252 (88%) |
| Protest relevance | 170 / 252 (67%) |

The keep/exclude disagreements run almost entirely one way:

- **53 records:** Claude excludes, Codex keeps. Of these, 40 have only a passing,
  historical, quoted or rhetorical protest mention. Nine are protests or
  aftermath abroad: Bangladesh, Canada, the UK and US, Pakistan, the Maldives.
  Four are round-ups or opinion pieces with no single development.
- **2 records:** Claude keeps, Codex excludes.

Codex labelled every retained record `INDIA_2024`, as Adarsh's notes said it
would, taking scope from GDELT metadata. Reading the text finds 26
out-of-scope articles.

Most relevance disagreements (32) are `PROTEST_LINKED` versus Codex's
`PROTEST`, because Codex rarely used the linked category. Both count toward the
protest benchmark, so this does not change any keep/exclude call.

**Spot-check.** Four disputed articles were read by hand, and all four went
Claude's way:

| ID | Article | Codex | Correct call |
|---|---|---|---|
| 608937 | exam-results website listing | `PROTEST` | unrelated |
| 584749 | biofuel plant inauguration | `PROTEST` | unrelated |
| 420243 | Maratha quota rally marching on Mumbai | `UNRELATED` | protest |
| 262860 | 40-word Samsung strike stub | excluded | kept, low confidence |

## Human review

`protest-review-300.screening-review-list.md` (gitignored, because it quotes
headlines) orders the work:

1. **16 records to decide.** Keep/exclude disagreements where Claude is unsure,
   plus both records Claude keeps that Codex excludes.
2. **39 records to skim.** Disagreements where Claude is confident; the
   spot-checks favour Claude on this kind.
3. **44 records, optional.** Keep/exclude agrees, but a label is low confidence.

A human's change to any screening decision replaces Claude's, and the reviewer
field records who made it.

## Known gap

`evaluate` rejects the full 300-record packet with `Missing prediction for
annotated article 422894`. The 21 extraction-rejected records have no
prediction. P4.1 (`freeze`) must handle screening-only records.
