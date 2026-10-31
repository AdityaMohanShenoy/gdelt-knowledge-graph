# Phase 8 — Canonical events

**Status: built, and the acceptance check is met.** The 911 reviewed event
mentions (Phase 7) become **866 canonical events**.
- **Merged events:** 26 combine reports from several articles, and 24 of them
  are backed by more than one independent outlet.
- **Acceptance case:** Kejriwal's 21 March 2024 arrest by the ED, reported in 7
  articles, is one node.
- **How merges were decided:** every merge is a reviewed decision (AI, at no
  cost). No score threshold was safe enough to merge automatically.

## Method

`pipeline/21_canonicalize.py`, with the logic in `pipeline/canonical_events.py`.

1. **Dates.**
   - **Anchor.** No article has a publication date, so each mention's time
     expression is resolved against its article's report date, the earliest
     GDELT observation day. Report days never spread more than 3 days within an
     article.
   - **Calendar dates** take the year that keeps them nearest the report: on
     the past side for asserted events, the future side for announced ones.
   - **Relative expressions.** Weekdays, "today", "yesterday", "last week" and
     bare months each have their own rule. With no expression, the date falls
     back to the report date with a wide, low-confidence range.
   - **Rules used (911 mentions):** report date 612, weekday 160, calendar date
     104, today 21, yesterday 6, month 5, last week 3.
2. **Blocking (`pairs`).** Pairs must come from different articles, share the
   same status, have the same or an unknown event type, and overlap in date
   range within 1 day. That gives **3,515 candidate pairs**. Blocking decides
   nothing.
3. **Score.** The weights are sentence similarity (local `all-mpnet-base-v2`) 3,
   actor overlap 2, place overlap 1.5, action overlap 1 and target overlap 1. An
   unstated field is skipped, not counted as a mismatch. The score **orders
   review**; it is not a merge probability.
4. **Decisions.** Fresh AI judges labelled pairs under `docs/same-event-rubric.md`.
   Same incident means same; related but distinct developments are different,
   as are different days of a campaign. The rubric says to be strict.
5. **Build.**
   - **Merging.** Only judged-same pairs merge, joined transitively into
     clusters. A cluster containing a pair judged different is kept but marked
     `CONFLICT`.
   - **Fields.** Each canonical event carries the plan's fields. `best_time`
     and `time_range` come from the best-dated members only.
   - **Corroboration.** `supporting_sources` lists the articles, and
     `independent_outlets` lists distinct hosts, so syndicated copies do not
     count as independent confirmation.

### Choosing the tiers (calibrated sample, 256 pairs)

| Score | Same / judged |
|---|---:|
| ≥ 0.9 | 10 / 11 |
| 0.8–0.9 | 3 / 4 |
| 0.7–0.8 | 6 / 9 |
| 0.6–0.7 | 7 / 13 |
| 0.5–0.6 | 9 / 30 |
| 0.4–0.5 | 13 / 89 |
| 0.25–0.4 (sample) | 3 / 60 |
| < 0.25 (sample) | 0 / 40 |

- **Auto-merge: off.** No threshold had precision 1.0. Even at ≥ 0.95, 1 of 10
  pairs was a different event: the same "camping at Shambhu since Feb 13"
  sentence reported on two different days. `--auto` exists but is unset.
- **Review band: score ≥ 0.25,** every pair judged (593 decisions).
- **Below 0.25: never merged.** No merge was found in a sample of 0/40, which
  puts a 95% upper bound of about 7% on the share of merges missed down there.

## The date bug, found and fixed during this phase

The first build resolved an asserted "March 21", in an article reported on
21 March, to **2023**. The "past side" test in `nearest_year` excluded every
date from three days before the report onward, including the report day itself.

The new tests caught it. **24 of 911 mentions** had the wrong year. The fix
added 200 candidate pairs and removed 12, none of them judged. All 569 earlier
judgements still applied with unchanged scores, and the 24 new in-band pairs
were judged. Six were merges, all Kejriwal's arrest, which the wrong year had
kept apart. The v1 pairs and canonical files are superseded by v2.

## Result

| File (`data/evidence/events/`) | SHA-256 |
|---|---|
| `protest-review-300.pairs.v2.json` | `a79d4d74d87a5a538be242e65aecbb692a88462c8cc67b2c03ba88e1c97ff78c` |
| `protest-review-300.pairs.v2.manifest.json` | `439f5dc929dcaa46972383a58b1e092d97e2c39c7470724b531ac017383cc3c1` |
| `protest-review-300.pairs.v2.decisions.jsonl` (593 judged pairs) | `44235286a2a5320a9a853ca9decf7a790cd217dd1c0a908f9ada49d0cb5b9c4f` |
| `protest-review-300.canonical.v2.jsonl` (**canonical events**) | `20e822714ed69c148d4d90a7a3836bbc4291bc5a66a04319b8caca28fdafaee0` |
| `protest-review-300.canonical.v2.manifest.json` | `c87f2860cfeed37ea9bdafcd5f1666a25b7ebe72b3619b80820aa9db91fd6301` |
| `docs/same-event-rubric.md` | `19b7d24d57802c8bae0a0dfb90e61261863c3544b6aee341e1a776244b01faad` |

**Merge counts by tier, as the plan's check requires:**

| Tier | Pairs |
|---|---:|
| Auto | 0 |
| Reviewed: merged | 67 |
| Reviewed: rejected | 526 |
| In band, unreviewed | 0 |
| Below the review floor, not merged | 2,922 |

**Events.** 866 canonical events: 26 merged from several articles, 24 of them
with at least 2 independent outlets, and 1 `CONFLICT`. The largest are:
- Kejriwal's ED arrest: 7 reports, 21 March 2024, high date confidence, 5
  outlets
- the RG Kar rape-murder: 6
- the Kolkata police arrest in the RG Kar case: 5
- AAP's party decision after the arrest: 4
- the junior doctors' protest: 3

**The conflict.** It is a Punjab/Bharat Bandh call for 30 December, joined to
the unions' road-blockade instructions through a third report. The judges called
the two ends different, so it stays flagged for review rather than being trusted.

## Known limits

- **Ongoing campaigns split into one event per day.** Under the strict rubric,
  the farmers' camp at Shambhu and Khanauri and Dallewal's fast are new events
  each day they are reported. That is safe, because it never merges wrongly,
  but one continuing protest becomes many nodes. A "same campaign" link here, or
  a condition node in Phase 12, would represent it better than a forced merge.
- **The corpus is small.** These are 139 articles from a random sample, so only
  a few real events are covered by several outlets. Most canonical events are
  single reports.
- **Outlets are counted by host,** so syndication across different hosts would
  be undercounted as independence. None was seen here.
- **Every decision is AI.** A person checking a sample of merges and rejections
  would make this human-verified.
