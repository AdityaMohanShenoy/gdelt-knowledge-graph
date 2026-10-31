# Same-event rubric (canonicalization)

Each item is a PAIR of event records from two different news articles. Decide whether they
describe **the same real-world event** — the same development, by the same parties, at the same
place and time — so they should become one node in an event graph.

Each record shows: the article headline, the article's report date, the sentence the event comes
from, the extracted action, actors, targets, locations, time expression, event type (CAMEO root)
and status (asserted = happened; announced = planned).

## `same`

- the same incident reported by two outlets ("Kejriwal arrested by ED on March 21" in both);
- the same ongoing protest at the same site described on the same day;
- the same announcement, decision, order or meeting.

Different wording, detail level or partial fields do not matter if the development is the same.

## `different`

- related but distinct developments: a call for a bandh vs the bandh itself; an arrest vs the
  protest against it; a court hearing vs the court's later order;
- the same kind of event by different parties or at different places (two different protests);
- the same campaign on different days (daily sit-ins, successive marches) — each day is its own event
  unless both sentences clearly describe the same day's action;
- one record is too vague to tell which event it is — choose `different` and say so.

Be strict: a wrong merge corrupts the graph more than a missed one.

For each pair give `decision` (`same` / `different`) and `why` (≤ 15 words).
