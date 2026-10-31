# Causal-candidate rubric (branching factor, GATE 11)

Each packet is one TARGET event (a GDELT-coded event in India, 2024) and up to 14 CANDIDATE
causes found by an automatic scorer. Each candidate is a group of GDELT events of one type on one
day, shown through one representative event. You decide, for each candidate, whether it is a
**real cause** of the target.

Evidence you have: the target event's metadata and the text of its source article (if it could be
fetched); each candidate's metadata, the scorer's reasons, and the opening of its own source article
(if fetched). Judge only from this. Do not browse the web.

## Answer `y` only when the text gives an inspectable causal link

Accept when the target article (or the candidate's article) states or plainly shows that the
candidate's development led to the target's, e.g.:
- explicit cause wording: "because of", "over", "after X, they protested", "in protest against X";
- explicit response wording: "in response to", "reacting to", "following X, police…";
- a policy → reaction link: the target protests or responds to the candidate decision/action;
- escalation of the same dispute: the candidate is an earlier stage that the target continues;
- mobilisation: the candidate is a call, meeting or decision that organised the target.

The candidate must be the same development the text names (same parties/issue/place), not merely
the same event type.

## Answer `n` when

- the only link is timing, shared actors, shared topic, or the scorer's numbers;
- the candidate is a generic group (e.g. many unrelated "Diplomatic Cooperation" events) with no
  text tying it to the target;
- neither article's text is available and the metadata alone cannot show the link;
- the candidate is the same event as the target (duplicate report), not a prior cause;
- the link runs the wrong way (the target caused the candidate).

Be strict: an unsupported `y` is worse than a cautious `n`. The point is to measure how many
*evidenced* parents an event has.

For each candidate give `accept` (`y`/`n`) and `why` (≤ 20 words: the link you saw, or why none).
