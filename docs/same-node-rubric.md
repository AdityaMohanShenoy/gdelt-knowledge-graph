# Same-node rubric

Each item is a PAIR of nodes from a causal graph of 2024 events in India. A node is an `event`
(something that happened on a date) or a `condition` (a persistent state or grievance). Each comes
with the exact sentences that report it. Decide whether the two nodes are **the same real-world
thing** and should be one node in the graph.

`same`: both nodes refer to the same occurrence or state, however worded, even when one was
extracted as an event and the other as a condition. Examples: "the rape and murder of a doctor at
RG Kar" extracted twice; the arrest of Arvind Kejriwal reported by two outlets; "MSP legal
guarantee" and "legal guarantee for minimum support price" as the farmers' grievance.

`different`: related but distinct. Examples:
- a killing vs the protests over it; a policy vs the protests against it;
- a grievance vs the demand to fix it; a cause vs its consequence;
- two separate protests by the same group on different days or in different places;
- an ongoing campaign vs one specific action within it (a sit-in vs one march during it);
- a general state vs one instance of it ("violence against doctors" vs one assault);
- one side too vague to tell.

Be strict: a wrong merge corrupts the graph more than a missed one, because merging joins every
cause and effect of both nodes. Judge only from the text given. Do not browse.
For each pair give `decision` (`same` / `different`) and `why` (<= 15 words).
