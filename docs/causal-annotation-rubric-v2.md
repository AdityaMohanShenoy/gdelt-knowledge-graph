# Causal annotation rubric v2 (Phase 11)

Changes from v1 (`docs/causal-annotation-rubric.md`), following Phase 10's measured agreement
(`docs/measurements/causal_edges.md`):
- The effect can be any event or condition, not only a protest. Phase 11 asks what caused the
  causes.
- Five relation types instead of seven:
  - CONTRIBUTES_TO merges into MOTIVATES; strength carries the difference.
  - ENABLES is dropped; it was never used.
  - Solidarity actions are named under ESCALATES.

Each packet is one EFFECT, with the article(s) that report it, and a list of CANDIDATE causes.
- The effect is an `event` (something that happened: a protest, an arrest, a decision, a statement)
  or a `condition` (a persistent state or grievance: a water crisis, a policy in force, rising
  violence).
- A candidate is likewise an `event` or a `condition`.
- Each comes with the exact sentences that report it.

Judge only from this text. Do not browse the web.

## For each candidate: accept or reject

**Accept** only on inspectable text, where the effect's article(s) or the candidate's own sentences
state or plainly show that the candidate led to the effect:
- explicit cause wording: "because of", "over", "due to", "after X, ...", "following", "led to";
- explicit response wording: "in response to", "reacting to", "in retaliation";
- opposition wording: "protesting against X", "demanding the withdrawal of X";
- a clear policy–response linkage: the effect opposes, enforces or reacts to the candidate;
- clearly described escalation: the candidate is an earlier stage of the same dispute or case;
- direct mobilisation: the candidate is the call, meeting or decision that organised the effect.

**Never accept** on timing, shared actors, shared topic, similar wording, or because the
candidate seems likely. An unsupported accept is worse than a cautious reject.

### For an accept, give

- `relation`, the closest of:
  - `TRIGGERS`: a discrete event that set off an effect which did not exist before it (a killing
    that sparked protests; a raid that led to an arrest).
  - `MOTIVATES`: a condition, grievance or reason the effect's actors act on or against. Use it
    also for a stated but secondary factor among several, with a lower strength.
  - `MOBILIZES`: the call, meeting, decision or organising act that brought the effect about.
  - `ESCALATES`: an earlier stage of the same, already existing dispute, case or campaign, which
    the effect continues. This includes a solidarity action supporting that same movement
    elsewhere.
  - `PROMPTS_RESPONSE`: the effect is one party's answer to another party's action or statement
    (a counter-protest, a rebuttal, a government reply to a protest).
- `strength`:
  - 3: the text states this link directly.
  - 2: stated, but as one of several causes or with hedging ("partly", "also", "amid").
  - 1: clearly implied by the text, but not stated with causal wording.
- `evidence`: an exact quote, character for character, from the effect article(s) or the
  candidate's sentences, that shows the link. Keep it to the shortest span that shows it.
- `supporting`: optional further exact quotes that confirm the same link. `[]` if none.
- `evidence_quality`: `explicit` (causal or response wording names the link) or `implicit` (the
  linkage is clear but no connective states it). `implicit` goes with strength 1. Words such as
  "after" or "following" that tie the two count as explicit.

### For a reject, give `reject_reason`

- `NO_CAUSAL_EVIDENCE`: unrelated, or nothing in the text links them.
- `CORRELATED_ONLY`: same topic, actors, place or time, but no stated link.
- `INSUFFICIENT_EVIDENCE`: a link is plausible and hinted at, but too weak to accept.
- `DUPLICATE_EVENT`: the candidate is the effect itself, or part of it, or the same real-world
  thing described as a different node.
- `WRONG_DIRECTION`: the candidate is a consequence of the effect, not a cause. A protest held
  against a grievance does not cause that grievance.
- `TEMPORALLY_INVALID`: the candidate happens after the effect, so it cannot cause it.
- `WRONG_EVENT_MATCH`: the candidate's sentences do not describe what its fields suggest (a
  mis-extracted or mis-merged node).
- `OTHER`: none of the above; explain in `why`.

Every judgement also gets a `why` of 15 words or fewer.

## Then: causes the article names that are NOT among the candidates

List each cause of the effect that its article(s) state with the accept wording above, and that no
candidate represents: `{"what": "<= 12 words", "quote": "exact quote from the article"}`. `[]` if
none. Demands and opinions are not causes.
