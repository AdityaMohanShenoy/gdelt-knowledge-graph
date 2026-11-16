# Same-campaign rubric

Each item is a PAIR of protest events from news reports of 2024 events in India. Each comes with
its label, date (and how confident that date is), any range its text states ("since February 13",
"18th day"), actors, places, and the exact sentences that report it.

Decide whether the two are **the same continuing protest action**, reported at different moments,
so they should be one campaign node:

`same_campaign`: one ongoing action seen on different days or described differently. Examples:
- a sit-in on its first day and the same sit-in "continuing" on its tenth day;
- "the farmers have been camping at Shambhu since February 13" and "farmers protesting at the two
  border points" when both are that camp;
- a hunger strike's launch and the same hunger strike on its 18th day;
- the junior doctors' fast-unto-death started on a date and "continued" days later.

`different`: separate actions, even within one movement or by the same people. Examples:
- a march vs the camp that formed after it was stopped (one led to the other);
- a sit-in vs a one-day rail roko or bandh called during it;
- a clash, a tear-gas incident, an arrest or a court hearing vs the protest itself;
- a solidarity protest elsewhere vs the protest it supports;
- two separate protests by the same group at different places or on unconnected days;
- a strike vs a different strike by other groups.

Be strict: joining two separate actions erases the cause-and-effect link between them, which is
worse than leaving one campaign split. Dates may be a report's publication day rather than the
event's, so read the sentences, not just the dates. Judge only from the text given; do not browse.
For each pair give `decision` (`same_campaign` / `different`) and `why` (<= 20 words).
