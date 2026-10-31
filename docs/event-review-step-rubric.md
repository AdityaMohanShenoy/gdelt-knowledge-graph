# Event review step — confirm, correct, and complete

An automatic extractor proposed event mentions for each article. You are the review step: your
output becomes the reviewed event set. Judge only from the article text. Do not browse the web.

## What counts as an event

A concrete development the article reports as having happened, being under way, or being
announced/planned, by or to identifiable parties: protest actions (protests, marches, strikes,
bandhs, blockades, sit-ins, fasts, boycotts, gheraos, walkouts, effigy burning); police/security
actions (arrests, detentions, lathi-charges, tear gas, denials of permission, cases/FIRs,
deployments, border sealing, internet shutdowns); violence (attacks, clashes, injuries,
deaths); government/court/institutional decisions and orders; meetings, talks, appeals, demands
and announcements of action.

NOT events: opinions, condemnations, background summaries, descriptions of a situation,
generic or hypothetical statements, prescriptions ("should"), adjectives ("protesting
farmers"), the content of a demand ("demanded the release" — the demand is the event, not the
release), denied events.

## For every proposed mention

- `verdict`: `accept` if it is a real event as defined above, else `reject` (give a short reason).
- For an accepted mention, correct its fields. For each of `actors`, `targets`, `locations`,
  `event_time`: give the field's value as a list of **exact substrings copied character for
  character from that mention's sentence** (for `event_time`, one substring or null). Use []
  / null when the sentence does not state it. A pronoun is not an actor — leave it out.
  Location = where THIS action happened; time = when THIS action happened (not when someone
  spoke, not a duration).
- `event_type`: CAMEO root — 14 protest; 17 coerce (arrest, detain, ban, lathi-charge, tear gas,
  deny permission, case/FIR, sealing, shutdowns); 18 assault (attack, kill, injure); 19 fight
  (clash); 15 force posture (deploy); 02 appeal/demand; 04 consult (meet, talks); 12 reject;
  null when none fits (e.g. court orders, government decisions, adjournments).
- `status`: `asserted` (happened / under way) or `announced` (planned, threatened, called for).

If two proposals are the same event, accept one and reject the other as `duplicate`.

## Then add missed events

Read the whole article and add every event (as defined above) that no accepted mention covers.
For each: `sentence_id`, `action` (exact substring of that sentence naming the action), the
four fields as exact substrings, `event_type`, `status`. One entry per distinct development; if
the same development is reported in several sentences, add it once, from the sentence that
states it most fully.

Exact substrings matter: anything not found verbatim in its sentence is discarded.
