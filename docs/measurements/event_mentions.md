# Phase 7 — Atomic event mentions (rules v1 and v2)

**Status: rules v2 is the current extractor, and the acceptance check is not
yet met.**
- **v2 against v1,** on a fresh train sample with blinded review: precision
  0.88 (v1 0.78), estimated recall about 0.5 (unchanged).
- **Field accuracy when filled:** place 0.86, time 0.88.
- **Mentions remain `UNREVIEWED` proposals.** The extractor proposes; review
  decides.

See "Rules v2" and "Where Phase 7 goes from here" below. The v1 sections are
kept as the record that v2 was built against.

## Rules v1: what it does

`pipeline/20_extract_events.py` wraps the logic in `pipeline/event_mentions.py`.

**Finding events.** It parses each stored sentence with spaCy. The sentence
boundaries are the ones the labels use, so offsets index into the frozen snapshot
text, and every mention records that text's `text_sha256`. A mention comes from:
- an event verb, e.g. arrest, march, demand
- a light verb carrying a protest noun ("staged a dharna", "called a bandh")
- a protest noun after "on" ("went on strike")
- a protest noun as subject ("protests erupted")

**Fields.**
- Actor and target come from the subject and object.
- Place and time come from spaCy entities in the sentence.
- `event_type` is a CAMEO root code, set only where the verb settles it.
- `status` is `asserted` or `announced`. A modal verb, or an intent verb such as
  "decided to march", marks the event `announced`.

**Rules.**
- Negated events are never emitted, whether the negation sits on the verb or on
  the noun ("no protest was held").
- An empty field means uncertain. `confidence` stays null until the extractor
  can be calibrated.
- Phase 2's focal event seeds each article. The mention in its core sentence is
  flagged `focal`, or a field-less seed is added when the rules find nothing
  there.
- NER labels map to the store's `entities.kind` in one table,
  `STORE_ENTITY_KIND`.

Every mention is validated on write: pinned hash, evidence inside the text, and
every field equal to the article text at its offsets and inside its evidence.

| File | SHA-256 |
|---|---|
| `data/evidence/events/protest-review-300.mentions.v1.jsonl` | `f37d73011a176375f4000cd92a4fd07ad4727535b99b62203c22faf5dadca358` |
| `data/evidence/events/protest-review-300.mentions.v1.manifest.json` | `98e570f7db9f334f45b35415e8009cae875f0e5a3be7619e0d80f072f1c6f353` |
| `data/evidence/events/protest-review-300.mentions.v1.dev-review.jsonl` (dev judgements) | `434ff60e9b3ec4bb0ac9ab3966a0ae7b13759e909e1fdcbcae8d5449098462f2` |
| `docs/event-mention-review-rubric.md` | `355adc439b299b6459d9bd20cd483895d7a0dfaf4b894329b29cdb1ffd95f63a` |

The input is the frozen v2 labels (`weak.v2`), and the run used spaCy 3.8.18
with `en_core_web_sm` 3.8.0.

## Rules v1: output (all 139 reviewed articles)

- **874 mentions:** 826 from the rules, plus 48 focal seeds where the rules found
  nothing in the core sentence. 131 articles have at least 2 rule mentions; none
  has 0.
- **Event types:** 14 protest 390, 02 demand 90, 17 coerce 70, 04 meet 40, 18
  assault 29, 12 reject 15, 19 fight 4, and untyped 188.
- **Status:** 761 asserted, 65 announced.
- **Fill rates:** actor 53%, target 55%, place 36%, time 46%, type 77%.

## Rules v1: evaluation (dev, 24 articles, 183 rule mentions)

Two fresh AI reviewers judged every dev mention under
`docs/event-mention-review-rubric.md`, and listed the events the rules missed.
These are AI judgements, not human ones.

| Measure | Result |
|---|---:|
| Precision: real events / mentions | **0.79** (144/183) |
| Estimated recall: found / (found + missed) | **0.59** (144/246; 102 missed) |
| Focal event captured by a real rule mention | 14 / 24 (8 are seeds, 2 not real events) |
| `event_type` accuracy when typed | 0.98 (108/110; 34 untyped) |
| `status` accuracy | 0.94 (136/144) |

Field quality is measured over the 144 real events:

| Field | Filled | Accuracy when filled | Right and filled |
|---|---:|---:|---:|
| actors | 91 | 0.85 | 0.53 |
| targets | 67 | 0.93 | 0.43 |
| locations | 53 | **0.58** | 0.22 |
| event_time | 78 | **0.64** | 0.35 |

## Rules v1: failure patterns

1. **Non-events (39 of 183).**
   - Adjectival participles: "agitating doctors", "protesting farmers".
   - Purpose and consequence clauses: "to demonstrate support", "blockade delayed
     trains".
   - Generic or hypothetical uses: "right to protest", "should withdraw".
   - Routine "House met" clauses, typed 04.
2. **Place and time from the wrong clause.** Entities are taken sentence-wide, so
   an event can get:
   - the date of the reporting verb
   - a duration, like "45-minute"
   - a place inside a title, like "Delhi Chief Minister"
   - a march's destination as the clash site
3. **Missed events (102), often the article's main one.** The rules miss:
   - police and state actions phrased as "stopped", "denied permission",
     "lathi-charged", "fired tear gas", "registered a case", "sealed the border"
   - meetings and talks, appeals and invitations
   - fasts phrased as "fast-unto-death"
   - parliamentary disruption
4. **Actors as bare pronouns** ("he", "they"): 10 of the 14 wrong actors. They
   are left as text, never resolved.
5. **Planned actions marked asserted** (8), and duplicate mentions where quotes
   repeat an event.

## Rules v2 (2026-10-31)

**Status: v2 is the current extractor. It is more precise than v1, with equal
recall, and the acceptance check is still not met.**

### Changes

Each change targets a v1 failure pattern:
- **Place and time come from the event's own clause.** A token counts only if
  it is governed by this event and not by another event verb inside it. Places
  that modify a noun ("Delhi" in "Delhi Chief Minister") and durations
  ("45-minute") are dropped.
- **Descriptive and prescriptive uses are not events.** That covers adjectival
  participles ("protesting farmers"), purpose and "right to" clauses, and
  should/must/may/might/could. A protest noun as subject counts only with onset
  verbs ("protests erupted", not "the blockade delayed trains"). "House met" is
  skipped.
- **Pronoun actors and targets stay empty.**
- **New actions:**
  - verb and object pairs: denied permission, registered a case or FIR, fired
    tear gas, sealed the border, imposed a curfew or Section 144, burnt an
    effigy, submitted a memorandum, blocked a road, closed shops
  - meetings and talks
  - appeal and urge
  - lathi-charge, adjourn, walk out
  - intransitive gather, assemble and congregate
  - deploy, typed 15
- **More intent framings** mark an event announced: scheduled, set, prepare,
  propose, agree.

| File | SHA-256 |
|---|---|
| `data/evidence/events/protest-review-300.mentions.v2.jsonl` | `25b420f0fc3e3e84ad9cffa3461ca7fe067730fddf0b2100a674cf3496ef4c8b` |
| `data/evidence/events/protest-review-300.mentions.v2.manifest.json` | `78a338c20d9d56b31df0eaa0d10b3a3d70c068ec1aaf9cebf6faff06c0ea4495` |
| `data/evidence/events/protest-review-300.mentions.v1v2.train-review.jsonl` | `421b6150974492da96ada111082d557fcfb118612abf68e83e5efd02f29d2f8e` |
| `data/evidence/events/protest-review-300.mentions.v1v2.dev-review.jsonl` | `aa166bec1d2eba7621c46e9ca07d84968411299e1205926bf5f9b41d0c2d7687` |
| `data/evidence/events/protest-review-300.mentions.v1v2.review-key.json` (candidate → version map) | `68cee90be80b4927a933bf8be492e9843e00e5b3aec187b9d735d2c7bf004272` |

### Output profile (139 articles)

- **770 rule mentions**, down from 826, plus 47 focal seeds (48 in v1).
- **Fill rates:** place 19% (36% in v1) and time 29% (46%). Actor 50%, target
  50%, type 79%.

### How v2 was evaluated

The comparison is blinded and uses the same judgements for both versions.
- **What reviewers saw.** Fresh AI reviewers judged the union of v1 and v2
  mentions without knowing which version produced which.
- **Where.** On **24 train articles that nobody had reviewed before** (a seeded
  sample, with no overlap with dev), and on dev.
- **Recall.** It is measured against every real event either version found,
  plus the events both missed.

Each cell is v1 → v2.

| Measure | **Fresh train (24)** | Dev (24) |
|---|---|---|
| Precision | 0.78 → **0.88** | 0.85 → **0.89** |
| Estimated recall | 0.52 → 0.49 | 0.56 → 0.57 |
| Focal event captured | 15 → 14 of 24 | 15 → 16 of 24 |
| Place correct when filled | 0.72 → **0.86** | 0.59 → **0.72** |
| Time correct when filled | 0.76 → **0.88** | 0.63 → **0.79** |
| Actor correct when filled | 0.94 → 0.94 | 0.82 → **1.00** |
| Target correct when filled | 0.95 → 0.95 | 0.84 → 0.90 |
| Type / status | 0.97 / 0.93 → 0.97 / 0.95 | 0.97 / 0.95 → 0.98 / 0.97 |

**Reviewer note.** Three of the four reviewers accepted a pronoun actor that
points to the right party; one did not. v2 leaves pronoun actors empty, so the
lenient reviewers favour v1 slightly on actors. Precision, recall, type and
status are unaffected. The v1 dev precision here, 0.85, is higher than in the
original v1 review (0.79), because these reviewers accepted participles that
describe an ongoing protest. The v1 → v2 comparison is fair either way, since
both versions were scored on the same judgements.

### What it shows

1. **v2 is a precision upgrade.** It makes fewer non-events (−10 points of
   error on fresh train), and its place and time are right far more often when
   filled. The cost is lower coverage: place right-and-filled falls from 0.29 to
   0.21 on train. That trade is the project's rule, uncertain over wrong.
2. **Recall did not move. It stays near 0.5, and that is the rules' ceiling.**
   The added vocabulary found some state actions, but the missed events are now
   mostly:
   - court orders
   - police actions phrased in ways no word list anticipates
   - whole headline events (a yatra starting, a bandh call, a special session
     summoned)
   - events in round-up articles

   More word lists give diminishing returns.
3. **The acceptance check is still not met.** Precision is 0.88, and 12% of
   mentions are still not events.

## Where Phase 7 goes from here

The rules extractor (v2) produces span-grounded proposals with about 88%
precision and about 50% recall. Two ways forward:

- **Accept the rules as proposals and add a review step.** Every mention is
  `UNREVIEWED`. Review can confirm or reject mentions, and add the missed
  events, before Phase 8 merges them. That keeps the "ML proposes, review
  decides" rule, but review becomes the main source of recall.
- **Change the extractor.** Recall beyond about 0.5 likely needs a learned
  model (an LLM with strict span validation, or a fine-tuned tagger), not more
  rules. That reopens the API decision made for Phase 7.
