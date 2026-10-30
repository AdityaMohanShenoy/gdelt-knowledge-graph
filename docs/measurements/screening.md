# Phase 1 — AI screening of all 300 records

**These are AI decisions, not human gold labels. No screening label is
human-made.** By the 2026-10-31 decision, Claude screened all 300 records in
three stages:
1. **First pass:** the 252 pilot, train and dev records.
2. **Adjudication:** the 16 disagreements with Codex that most affected
   keep/exclude.
3. **Blind test screen:** the 48 test records.

The final packet is `protest-review-300.screened.v2.packet.jsonl`.

## Stage 1 — first pass (252 records)

### Method

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

### Results

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

### Against Codex's proposals

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

## Stage 2 — adjudication (16 records)

These are the tier-1 records: keep/exclude disagreements with Codex where the
first pass was unsure, plus both records the first pass kept and Codex excluded.
A fresh agent read each article in full. It was shown the two prior labellings
as "Reader A" and "Reader B", in an order shuffled per article, without knowing
which was which, and decided under the same rubric.

- It sided with the first pass on 15 of 16 and with Codex on 1. That one is
  `592726`, a CPI(M)–SDPI feud that broke out at a named Mangaluru street
  vendors' protest, which is now kept as `PROTEST_LINKED`.
- 11 of its 16 calls are low confidence. Most turn on how much a secondary
  protest should count against an article's main story.
- **Caveat:** the adjudicator is also Claude. Blinding stops it from knowing
  which labelling was its own, but not from sharing the first pass's habits.
  Agreeing 15 times out of 16 is consistent with the first pass being right, and
  also with a shared bias.

## Stage 3 — blind test screen (48 records)

Two fresh agents each read 24 test articles. They saw only the rubric and their
batch: no Codex proposals, no first-pass decisions, no other files.

- 21 kept and 27 excluded; 10 calls are low confidence.
- **Against Codex:** 33/48 agree on keep/exclude, and all 15 disagreements are
  Codex keeping what the blind screen excludes. That is the same one-sided
  pattern as Stage 1, reproduced by readers who never saw Stage 1.
- One noteworthy catch: `167708` is dated January 2024 by GDELT, but the page
  says "Last Updated on November 4, 2023", so it is excluded as out of scope.

## Final (all 300)

| Split | Kept | Excluded |
|---|---:|---:|
| pilot | 35 | 27 |
| train | 60 | 82 |
| dev | 24 | 24 |
| test | 21 | 27 |
| **total** | **140** | **160** |

- **Relevance:** `PROTEST` 122, `PROTEST_LINKED` 36, `UNRELATED` 117, `UNCERTAIN` 25.
- **Scope:** `INDIA_2024` 243, `OUT_OF_SCOPE` 33, `UNCERTAIN` 24.
- **Confidence:** 65 of the 300 decisions are low confidence.

| File (`data/evidence/focal_events/`) | SHA-256 |
|---|---|
| `protest-review-300.screened.v2.packet.jsonl` | `bc0ca03628cf200f9b2a96e66d598ca7febf113fca1daeb4db127cf4deb3a6ae` |
| `protest-review-300.claude-screening.v2.jsonl` (stage, reasons, confidence, Codex and first-pass labels) | `22d57fef9a18872651a6797b7cec3e22ef72395a1d8080027f0895533eba1ab8` |
| `protest-review-300.screened.v2.packet.manifest.json` | `37a19ed52728ea266a754a1ec52b7f27c89dd53ed77487eb85049be9419ba939` |

The v2 packet loads in the review page in Chromium with no errors. Every record
has `eligibility.review_status = REVIEWED`.

**What this means for test.** Metrics on `test` measure agreement with an
independent AI screen, not accuracy against people. A person reviewing the test
records, or at least the 10 low-confidence calls, would turn that into a human
check.

## Known gap

`evaluate` rejects the full 300-record packet with `Missing prediction for
annotated article 422894`. The 21 extraction-rejected records have no
prediction. P4.1 (`freeze`) must handle screening-only records.
