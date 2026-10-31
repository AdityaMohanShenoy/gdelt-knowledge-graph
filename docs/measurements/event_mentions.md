# Phase 7 — Atomic event mentions, rules v1

**Status: built and evaluated. The acceptance check is not yet met.**
The extractor runs on all 139 reviewed articles and every field is an exact span.
But on dev, 21% of its mentions are not events, and place and time are often taken
from the wrong clause. Mentions stay `UNREVIEWED` proposals. The extractor
proposes; review decides.

## What it does

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

## Output (all 139 reviewed articles)

- **874 mentions:** 826 from the rules, plus 48 focal seeds where the rules found
  nothing in the core sentence. 131 articles have at least 2 rule mentions; none
  has 0.
- **Event types:** 14 protest 390, 02 demand 90, 17 coerce 70, 04 meet 40, 18
  assault 29, 12 reject 15, 19 fight 4, and untyped 188.
- **Status:** 761 asserted, 65 announced.
- **Fill rates:** actor 53%, target 55%, place 36%, time 46%, type 77%.

## Evaluation (dev, 24 articles, 183 rule mentions)

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

## Failure patterns

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

## Next: rules v2

Each fix comes from a failure pattern above:
- Scope place and time to the event verb's own dependency subtree, not the whole
  sentence.
- Skip adjectival participles (`amod`/`acl`) and purpose clauses.
- Leave pronoun-only actors empty: uncertain beats wrong.
- Add police and state actions, meetings, fasts and parliamentary disruption to
  the vocabulary.
- Detect planned and scheduled actions.

Measure v2 on a fresh sample, such as 24 train articles, as well as on dev.
These dev judgements have now been read while designing the fixes, so dev alone
would overstate v2.
