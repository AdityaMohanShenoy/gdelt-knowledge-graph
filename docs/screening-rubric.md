# Screening rubric — India 2024 protest corpus

You are screening news articles for a protest-event dataset. For each article, read the
**complete `article_text`** (not just the headline) and decide four labels. Judge only from
the saved text, headline, URL and GDELT dates given. Do not browse the web.

The **primary development** is the main news event the article reports — usually what the
lead is about — not background, history or context paragraphs.

## protest_relevance

- `PROTEST` — the primary development is a protest action: protest, demonstration, strike,
  bandh, march, rally against something, sit-in, dharna, blockade / rasta roko / rail roko,
  gherao, hunger strike, protest boycott, or a clash/riot/police action arising during a
  protest. Ongoing protests count. A group *calling, announcing or threatening* a protest or
  strike counts when that call is the main development.
- `PROTEST_LINKED` — the primary development is not itself a protest action but the text
  explicitly ties it to one: arrests, FIRs or court cases *after* a protest; government
  concessions, talks or decisions responding to protesters; aftermath reporting (injuries,
  compensation) of a named protest.
- `UNRELATED` — the primary development has nothing to do with protest. Includes articles
  where protest appears only as history/background, in a quote, metaphorically ("protest"
  in a sports appeal), negated ("no protest was held"), or as a passing mention.
- `UNCERTAIN` — you cannot tell after reading everything (e.g. the text cuts off before the
  development is clear). Use sparingly, always with `confidence: "low"`.

## body_quality

- `COMPLETE` — a substantive, readable article body that describes the development.
- `LIMITED` — only a preview or lead, a partial body, or heavy navigation/boilerplate mixed
  in, but a development is still identifiable.
- `INSUFFICIENT` — empty, navigation or boilerplate only, title-only, an error or login page,
  text that does not match the headline/URL, or too little to identify any development.

## scope

- `INDIA_2024` — the primary development happened in India, during 2024.
- `OUT_OF_SCOPE` — it happened outside India (diaspora protests abroad, protests in
  Bangladesh, Pakistan, etc.), or outside 2024. GDELT days are *report* dates, all in 2024;
  a January 2024 report of a December 2023 event is `OUT_OF_SCOPE`. Do not assume India just
  because GDELT tagged it — check the text.
- `UNCERTAIN` — location or date cannot be verified from the text (typical for
  `INSUFFICIENT` bodies).

## exclusion_reason

`null` when the article is retained. Otherwise the **first** that applies, in this order:

1. `INSUFFICIENT_TEXT` — body_quality is `INSUFFICIENT`.
2. `UNRELATED` — protest_relevance is `UNRELATED`.
3. `OUT_OF_SCOPE` — scope is `OUT_OF_SCOPE`.
4. `NO_FOCAL_EVENT` — protest-related, but no single identifiable primary development
   (round-ups of many unrelated events, event calendars, pure opinion/analysis with only
   background).

Never use `OTHER`. `PROTEST`/`PROTEST_LINKED` + in scope + a primary development → `null`.
`UNCERTAIN` relevance or scope with a usable body → `null` (a human will decide).

## confidence and reason

- `confidence`: `"high"` when the labels are clear; `"low"` when any label is a judgement
  call between two categories, or the text is partly garbled. Be honest — low-confidence
  cases go to a human, which is the point.
- `reason`: at most 25 words naming the primary development and what decided the labels,
  e.g. "Farmers' rail roko in Punjab on 15 Feb; PROTEST, in India 2024."
