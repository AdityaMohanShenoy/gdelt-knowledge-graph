# Focal-event rubric — India 2024 protest corpus

Every article you get has already been screened as protest-related, in India, in 2024, with a
usable body. Your job is to identify its **single primary development** and the sentences that
support it. Judge only from the numbered sentences given. Do not browse the web.

Each sentence is shown as `[sentence_id | paragraph_id] text`. Read the whole article first.

## 1. The primary development

The one current news development the article is reporting — usually what the lead is about.
Not background, history, context, or a different event mentioned in passing. If the lead is
about a protest's consequence (arrests, a government decision) and the article was screened
`PROTEST_LINKED`, that consequence is the primary development.

Announced, called, ongoing, ended and called-off actions can all be primary developments —
say which in the summary.

## 2. focal_event_summary

One sentence, at most 30 words: **who** did **what**, **where**, **when** (if the text says), and
its **status** (held / ongoing / announced / called off / ended). Use only facts in the text.

Good: "Punjab farmers held a rail roko at 22 sites on 15 Feb 2024 demanding MSP guarantees."
Good: "Air India Express sacked 25 cabin crew after a mass sick-leave protest; talks set for 9 May."

## 3. supporting_sentence_ids

**Every** sentence that directly states part of the primary development: that it happened,
who took part, the action, place, time, scale, the participants' stated demand or cause,
immediate outcome (detentions, injuries, talks, a decision announced *in response*).

Include: quotes from participants or officials that *describe* the development.
Exclude: history and earlier events; other developments; general commentary, analysis or
reactions that do not themselves report the development; navigation, captions, bylines,
"Also read" lines, repeated headline fragments. If a sentence mixes background and the
development, include it only if it states a fact of the development.

Usually 2–8 sentences. At least 1 is required for a REVIEWED record.

## 4. cohort

- `single_event` — one clearly bounded development (a march held, a strike called, arrests made).
- `ongoing_protest` — the development is a continuing protest (day N of a sit-in, a strike that continues).
- `government_decision` — the development is a decision by government, police, a court or an
  institution, typically responding to a protest.
- `multiple_events` — the article reports several developments with similar weight; you chose
  the lead one. Explain in notes.
- `historical_background` — most of the article is background, but a current development is
  identifiable. Explain in notes.

## 5. When there is no single development

If, after reading everything, no single primary development can be identified (a round-up of
unrelated items, pure analysis), set `decision` to `UNSUITABLE` with
`exclusion_reason: "NO_FOCAL_EVENT"` and explain in notes. Do this only when genuinely
necessary — screening already judged these articles usable.

## Output fields

- `decision`: `REVIEWED` or `UNSUITABLE`
- `focal_event_summary`, `supporting_sentence_ids` (list of ints, ascending), `cohort`
  — required for REVIEWED; null / [] / null for UNSUITABLE
- `exclusion_reason`: null for REVIEWED; `"NO_FOCAL_EVENT"` for UNSUITABLE
- `confidence`: `"high"` or `"low"` — low when the choice of primary development or the
  support boundary is a genuine judgement call
- `notes`: at most 30 words — required when confidence is low, cohort is multiple_events or
  historical_background, or decision is UNSUITABLE; otherwise null
