# Demo journey: an animated, key-driven walk from GDELT to "Ask it why"

## Intent
For the Review 3 demo, the presenter wants the `/demo` page to tell the project as one flow, start to
end, top to bottom, with striking animation, finishing on the end goal: live causal querying. The
presenter controls it with key presses, like slides.

## Decided (with the user)
- Driven by key presses: each press plays the next stage's animation. (User's choice over scroll.)
- One real story followed through every stage (the farmers' "Delhi Chalo" protest, Feb 2024), with
  the corpus-wide counts beside each step. The flow replaces the page's middle sections (problem,
  funnel, graph mix, audit); the opening screen and "Ask it why" stay.

## Stages (one key press each)
1. **GDELT** — 26,740,052 records in 2024 → 2,220,760 in India → 43,410 protest records; then the five
   real records (13 Feb 2024) that cite the India Post article. They say who/where/when, never why.
2. **Read** — the article opens from the record's URL: its first two paragraphs. 2,000 articles
   fetched, 915 kept.
3. **Extract** — the real extracted spans highlight word for word (actors, action, place, time) and
   lift off as event chips. 7,083 mentions.
4. **Merge** — 7 event records of the same march collapse into one node. 6,152 events + 810 grievances.
5. **Link** — candidate causes fan in to the march; three are accepted, each arrow drawn with its
   quote (organised by / motivated by / set off by). 20,129 claims judged.
6. **Blind check** — a stream of real links and decoys passes the gate: decoys are stopped. 143 links
   removed; 44 of 1,352 decoys passed.
7. **Repair** — duplicates merge, a loop is cut. 151 / 5 / 11.
8. **The graph** — the full published graph assembles (1,188 nodes, 1,416 links), the farmers' story
   lit up. 358 protests explained.
9. **Checked by hand** — 89 of 99 correct; 69 of 69 stated links.
10. **Ask** — the page moves to "Ask it why" and asks the farmers' question.

## Builder's calls
- Data comes from a generated file `frontend/demo-journey.json` (written by
  `pipeline/41_demo_snapshots.py` from the graph, the local GDELT universe, the article store and the
  extraction records), carrying the graph version; a test ties it to the published graph and checks
  every highlighted span is a substring of the article text. Counts not in the graph come from the
  measurement reports or the GDELT universe manifest.
- Keys: → / Space / PageDown next, ← / PageUp back (presenter clickers send PageDown/PageUp),
  R replays the current stage. Going back shows the previous stage's finished state.
- Animation: Web Animations API, CSS transforms and SVG stroke drawing; the full graph is drawn on a
  canvas with d3-force for smoothness. Reduced motion shows each stage's end state.
- No new dependencies; d3 7.9.0 is already loaded.

## Non-goals
- No change to the query engine, API or published graph.
- No scroll-jacking: the page still scrolls normally; keys drive the stage.
