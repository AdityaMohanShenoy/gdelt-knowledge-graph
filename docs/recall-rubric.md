# Recall rubric: new candidate causes (events and conditions)

Each packet is one PROTEST (the "effect") with its article, a list of NEW candidate causes, and
`missed_causes`: causes the protest's article names that an earlier retrieval did not find.
Candidates are either `event` (something that happened, including remarks and statements) or
`condition` (a persistent state or grievance: a water crisis, a policy in force, rising violence).
Each comes with the exact sentences that report it. Judge only from this text. Do not browse.

## Part A: is each new candidate a cause of the protest?

Answer `y` only when the text gives an inspectable causal link: the protest's article (or the
candidate's own sentences) states or plainly shows the candidate led to the protest:
- explicit cause wording: "because of", "over", "against", "in protest against", "after X, ...";
- explicit response wording: "in response to", "reacting to";
- policy or condition -> reaction: the protest is against or over the candidate state/decision;
- escalation: the candidate is an earlier stage of the same dispute that the protest continues;
- mobilisation: the candidate is the call, meeting or decision that organised the protest.

Answer `n` when the only link is timing, shared actors, shared topic or similar wording; when the
candidate is the protest itself or part of it; when it is a consequence of the protest; or when
the link runs the wrong way. A condition on the same broad topic is `n` unless the text ties THIS
protest to it. Be strict: an unsupported `y` is worse than a cautious `n`.

For a `y` give `relation` (TRIGGERS | MOTIVATES | MOBILIZES | ENABLES | ESCALATES |
PROMPTS_RESPONSE | CONTRIBUTES_TO) and `evidence`: an exact quote, character for character, from
the provided sentences or article that shows the link.

## Part B: are the missed causes now found?

For each entry of `missed_causes`, list the candidate_ids that represent that same cause (the same
event, remark or state, not merely the same topic), or [] if none does. A candidate can only
represent a missed cause if you answered `y` for it in Part A.
