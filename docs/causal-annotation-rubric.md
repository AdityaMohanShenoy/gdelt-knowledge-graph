# Causal annotation rubric (Phase 10)

Each packet is one PROTEST (the "effect") with the article(s) that report it, and a list of
CANDIDATE causes. A candidate is an `event` (something that happened, including statements,
remarks and decisions) or a `condition` (a persistent state or grievance: a water crisis, a policy
in force, rising violence). Each candidate comes with the exact sentences that report it. Judge
only from this text. Do not browse the web.

## For each candidate: accept or reject

**Accept** only on inspectable text, where the protest's article or the candidate's own sentences
state or plainly show that the candidate led to the protest:
- explicit cause wording: "because of", "over", "after X, ...", "following";
- explicit response wording: "in response to", "reacting to", "in retaliation";
- protest-against wording: "protesting against X", "demanding the withdrawal of X";
- a clear policy–response linkage: the protest opposes the candidate decision or policy;
- clearly described escalation: the candidate is an earlier stage of the same dispute;
- direct mobilisation: the candidate is the call, meeting or decision that organised the protest.

**Never accept** on timing, shared actors, shared topic, similar wording, or because the
candidate seems likely. An unsupported accept is worse than a cautious reject.

### For an accept, give

- `relation`, the closest of:
  - `TRIGGERS`: a discrete event that set off a protest which did not exist before it.
  - `MOTIVATES`: a grievance or condition the protesters act against (the reason, not the spark).
  - `MOBILIZES`: the call, meeting, decision or organising act that brought people out.
  - `ENABLES`: made the protest possible without motivating it (a permission, a lifted ban).
  - `ESCALATES`: an earlier stage of the same, already existing dispute that the protest continues.
  - `PROMPTS_RESPONSE`: the protest answers another party's protest or statement (a counter-protest).
  - `CONTRIBUTES_TO`: a stated but secondary factor among several.
- `strength`: 3 = the text states this link directly as the protest's cause; 2 = stated, but as
  one of several causes or with hedging ("partly", "also"); 1 = clearly implied by the text but not
  stated with causal wording.
- `evidence`: an exact quote, character for character, from the effect article(s) or the
  candidate's sentences, that shows the link. Keep it to the shortest span that shows it.
- `supporting`: optional further exact quotes (another article, the candidate's sentences) that
  confirm the same link. `[]` if none.
- `evidence_quality`: `explicit` (causal or response wording names the link) or `implicit` (the
  linkage is clear from the text but no connective states it). `implicit` goes with strength 1.

### For a reject, give `reject_reason`

- `NO_CAUSAL_EVIDENCE`: unrelated, or nothing in the text links them.
- `CORRELATED_ONLY`: same topic, actors, place or time, but no stated link.
- `INSUFFICIENT_EVIDENCE`: a link is plausible and hinted at, but too weak to accept.
- `DUPLICATE_EVENT`: the candidate is the protest itself, or part of it (a duplicate report, a
  detail of the same march, a speech made at it).
- `WRONG_DIRECTION`: the candidate is a consequence of the protest (police response, aftermath).
- `TEMPORALLY_INVALID`: the candidate happens after the protest, so it cannot cause it.
- `WRONG_EVENT_MATCH`: the candidate's sentences do not describe what its fields suggest (a
  mis-extracted or mis-merged node).
- `OTHER`: none of the above; explain in `why`.

Every judgement also gets a `why` of 15 words or fewer.

## Then: causes the article names that are NOT among the candidates

List each cause the protest's article states with the accept wording above that no candidate
represents: `{"what": "<= 12 words", "quote": "exact quote from the article"}`. `[]` if none.
