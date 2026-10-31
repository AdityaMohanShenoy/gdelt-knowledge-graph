# Same-condition rubric

Each item is a PAIR of conditions (persistent states or grievances) from two different news
articles. Decide whether they are **the same condition** — the same problem, policy, shortage,
pattern or grievance, borne by the same parties in the same place — so they should be one node.

`same`: the same named grievance or state described differently ("a legal guarantee for MSP" and
"legal minimum support price guarantee" as the farmers' grievance; "Delhi's water crisis" in two
reports of the same summer). Different wording or detail does not matter.

`different`: related but distinct states (a shortage vs the policy that caused it; "violence
against doctors" in general vs one hospital's security failures); the same kind of grievance held
by different parties or in different places (two states' fee hikes); or one side too vague to tell.

Be strict: a wrong merge corrupts the graph more than a missed one.
For each pair give `decision` (`same` / `different`) and `why` (≤ 15 words).
