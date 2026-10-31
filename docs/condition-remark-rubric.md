# Conditions and remarks — extraction rubric

You read one news article at a time (numbered sentences) and extract two things that an
event-only graph misses. Judge only from the text. Do not browse the web.
**Every value you give must be an EXACT substring of the named sentence, copied character for
character.** Anything not found verbatim is discarded.

## 1. Conditions

A condition is a **persistent state or grievance** that the article presents as a background
cause, motive or context of a protest or dispute — something that holds over a period rather than
happening at a moment. Examples: "the water crisis in Delhi", "rising violence against doctors",
"the Rs 1 crore surety bond for PG courses", "alleged irregularities in NEET", "non-payment of
salaries", "the shortage of fertiliser", "the abolition of reservation for border students",
"exploitation by microfinance companies", "the delay in MSP legislation".

Include a condition only if it is specific enough to identify (a named problem, policy, shortage,
pattern, or grievance — not "various issues" or "pressing issues"). One entry per distinct
condition per article; if the same condition is stated in several sentences, use the sentence that
states it most fully.

For each condition give:
- `sentence_id` (int)
- `condition`: exact substring naming the condition (as short as identifies it)
- `holders`: exact substrings naming who bears it or whose grievance it is ([] if not stated)
- `locations`: exact substrings for where it holds ([] if not stated)
- `since`: exact substring stating when it began, or null; `until`: exact substring for when it
  ended, or null
- `status`: `ongoing` | `ended` | `unclear`
- `kind`: `policy` (a rule, scheme, law, fee, bond, reservation) | `shortage` (water, power,
  fertiliser, staff) | `violence` (a pattern of attacks/insecurity) | `economic` (prices, wages,
  dues, exploitation) | `governance` (corruption, irregularities, delays, neglect) | `other`
- `role`: `protest_cause` if the article presents it as a reason for a protest, demand or dispute;
  else `context`

## 2. Remarks

A remark is a **specific statement by an identifiable party, made at a particular time**, that the
article reports because it matters — especially one that provoked a reaction: an insult or slur, an
offensive remark, a threat, an accusation, a public announcement or declaration. NOT ordinary quoted
commentary, opinions explaining a position, or the article's own description.

For each remark give:
- `sentence_id` (int)
- `action`: exact substring naming the act of speaking (e.g. "called him a Khalistani", "allegedly
  used an offensive word", "threatened to")
- `actors`: exact substrings for the speaker ([] if unnamed)
- `targets`: exact substrings for who or what it was about ([])
- `event_time`: exact substring for when, or null
- `event_type`: `01` (public statement/announcement) | `11` (disapprove/criticise/insult/accuse) |
  `12` (reject) | `13` (threaten)
- `provoked_reaction`: true if the article says it led to a protest or response, else false

Be selective: precision matters more than coverage. If an article has none, return empty lists.
