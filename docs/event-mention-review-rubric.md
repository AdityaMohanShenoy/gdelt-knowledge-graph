# Event-mention review rubric

An automatic extractor proposed event mentions for each article. Each mention names a
sentence (`sentence_id`), an `action` phrase, and optional fields copied from that sentence:
`actors`, `targets`, `locations`, `event_time`, `event_type` (a CAMEO root code), `status`.

CAMEO roots used: 14 protest; 17 coerce (arrest, detain, ban); 18 assault (attack, kill,
injure); 19 fight (clash); 02 appeal/demand; 04 consult (meet); 12 reject. null = not typed.

## For every mention, judge

- `real_event` — `yes` if the sentence reports this action as a concrete development that
  happened, is ongoing, or is announced/planned (as the sentence says), by or to identifiable
  parties. `no` if it is not an event: a generic/habitual statement, a hypothetical, a
  quotation's figure of speech, a description, a denied event, or a misparse.
- For each of `actors`, `targets`, `locations`, `event_time`: `correct` (filled and the right
  referent for THIS action), `wrong` (filled but not right for this action — wrong party,
  location of a different clause, a date that is not this action's time), or `empty`.
  Partial spans that contain the right referent count as `correct`.
- `event_type`: `correct`, `wrong`, or `untyped` (null).
- `status`: `correct` or `wrong` (asserted = happened/ongoing; announced = planned/threatened).

Only judge mentions where `real_event` is `yes` for the field questions; for `no`, set the
fields to `n/a`.

## Then list missed events

Read the whole article. List every concrete development in it that NO mention captures —
protest actions, police/security actions, violence, government/court/institutional decisions,
meetings or talks, demands or announced actions. Not opinions, background summaries, or
statements that merely describe a situation. One entry per development:
`{"sentence_id": int, "what": "<= 12 words"}`.

Judge only from the text. Do not browse the web.
