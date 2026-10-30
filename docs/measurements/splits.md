# P5.1 — Splits for the 300-record review batch

Assigned before any human review, with `pipeline/10_extract_focal_events.py split`.

    .venv/bin/python pipeline/10_extract_focal_events.py split \
      --input data/evidence/focal_events/protest-review-300.ai-assisted.packet.jsonl \
      --pilot data/evidence/focal_events/protest-pilot.screening.jsonl \
      --pilot data/evidence/focal_events/pilot.jsonl \
      --output data/evidence/focal_events/protest-review-300.splits.packet.jsonl

Seed `focal-splits-v1`, test 0.2, dev 0.2. **Reviewers work from
`protest-review-300.splits.packet.jsonl`.**

## Inputs and outputs

| File | SHA-256 |
|---|---|
| `protest-review-300.ai-assisted.packet.jsonl` (input) | `63cccabfb0590abb6af9ac297ddac067899bde81e3e664196e86992e2d65749c` |
| `protest-pilot.screening.jsonl` (pilot) | `41a7cbccc923a597493d69e286e8daa3ee24cd757db254b4c46982fc278d6b12` |
| `pilot.jsonl` (pilot) | `12c2e0c20fe5df047b53acc085bcde93da423b484ae5b668ca772bafc4f92118` |
| `protest-review-300.splits.packet.jsonl` (output) | `f51c60aa2f4529105c0afb0976fa4e6435067a4ede98df025b47186c4cb99477` |
| `protest-review-300.splits.packet.manifest.json` | `6d0c0debae3b4bd757f186aa75d601635a60a06802ffe26a5df5b4a6172f2ada` |

The input packet matched its AI-assisted manifest, along with the five other
files that manifest lists. `audit` on `protest-review-300.jsonl` reproduced
279 complete records and 14,146/14,146 valid spans, with 0 inconsistent.

## Counts

Relevance and quality below are the **AI proposals** and screener status, before
human review. They describe the mix, not gold labels.

| Split | Articles | AI: protest | AI: unrelated | AI: uncertain / linked | Readable | Unsuitable text |
|---|---:|---:|---:|---:|---:|---:|
| `pilot` | 62 | 46 | 14 | 2 / 0 | 60 | 2 |
| `train` | 142 | 89 | 37 | 16 / 0 | 126 | 16 |
| `dev` | 48 | 33 | 11 | 3 / 1 | 45 | 3 |
| `test` | 48 | 36 | 12 | 0 / 0 | 48 | 0 |

"Readable" includes the screener's `SHORT_REVIEW` flag.

- **Pilot (62).** These are the 60 protest-pilot records, which are the first 60
  of the 300, plus 2 articles shared with the original 40-article pilot. Both
  sets were inspected against model output or user relevance decisions, so
  neither can be held out.
- **Test (48), blind.** Test records keep only the frozen snapshot. The AI
  draft (`ai_proposal`, summary, support, cohort, reviewer) is removed. Train,
  dev and pilot keep their drafts.
- **No extraction-rejected record is in test.** That happened by chance (about
  3%), not by design. It means every test record has readable text.

## Duplicates

One group was found: 7 articles from easternmirrornagaland.com (`37318`,
`37333`, `37425`, `38052`, `38071`, `38205`, `38448`). None has a usable body:
four extracted as empty text, and three as the same 65-word block of site
boilerplate. The stored copies share boilerplate content hashes. The group is
kept together in `train`, and all seven are expected to be excluded at
screening.

No two articles in different splits share a URL, final URL, content hash, text
hash, or near-duplicate text (word 5-shingle Jaccard ≥ 0.8).

## Coverage

- **Hosts.** Test draws on 27 hosts, 20 of which also appear in train or dev. At
  300 articles concentrated on a few Indian outlets, separating by host would
  leave test with only minor outlets. Host overlap is accepted. URL and content
  overlap are not.
- **Months.** Every split covers all 12 months of 2024, by first GDELT
  observation. Only the 21 extraction-rejected records lack an observation date.

## Still to do

Protest cohort is a review label, so it is added after Phase 2. If cohorts turn
out badly skewed, re-split with a new seed, but only before any test record has
been reviewed. Once tuning begins, the test split is frozen.
