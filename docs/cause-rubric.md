# Cause-judgement rubric (Phase 9 retrieval check / Phase 10 pilot)

Each packet is one PROTEST event (the "effect") with its article, and a list of CANDIDATE events
(possible causes) that happened before or during it. Each event comes with the exact sentences that
report it. Judge only from this text. Do not browse the web.

## For each candidate: is it a cause of the protest?

Answer `y` only when the text gives an inspectable causal link — the protest's article (or the
candidate's own sentences) states or plainly shows the candidate led to the protest:
- explicit cause wording: "because of", "over", "against", "in protest against", "after X, …";
- explicit response wording: "in response to", "reacting to";
- policy → reaction: the protest is against the candidate decision/action;
- escalation: the candidate is an earlier stage of the same dispute that the protest continues;
- mobilisation: the candidate is the call, meeting or decision that organised the protest.

Answer `n` when the only link is timing, shared actors, shared topic or similar wording; when the
candidate is the protest itself or part of it (a duplicate report, a detail of the same march);
when the candidate is a consequence of the protest (police response to it, its aftermath); or when
the link runs the wrong way. Be strict: an unsupported `y` is worse than a cautious `n`.

For a `y`, also give:
- `relation`: TRIGGERS | MOTIVATES | MOBILIZES | ENABLES | ESCALATES | PROMPTS_RESPONSE |
  CONTRIBUTES_TO (pick the closest; the taxonomy will be revised from agreement);
- `evidence`: an exact quote (copied character for character) from the provided sentences/article
  that shows the link.

## Then: causes the article names that are NOT among the candidates

List each cause the protest's article explicitly names (by the wording above) that no candidate
represents: `{"what": "<= 12 words", "quote": "exact quote from the article"}`.
