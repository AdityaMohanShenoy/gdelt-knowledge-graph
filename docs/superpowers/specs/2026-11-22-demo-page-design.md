# Demo page (`/demo`) — design

## Intent
A single page for a live presentation to a general audience that cares about polished UI and
numbers. It tells the project's story (GDELT says *what*, articles say *why*; our algorithm turns
the *why* into a quoted, queryable causal graph) and ends with live querying.

## Goals
- Scrollable story in six sections: hero counters; the GDELT problem; how it works (funnel);
  the graph (relation and depth mix, one story's network); can you trust it (audit, labour);
  ask it anything (live query).
- Live query drawn as a chain of cards joined by labelled arrows, each with its quote and source.
- Works on a projector: large type, high contrast, keyboard navigation between sections.
- Survives bad venue Wi-Fi for the core demo: featured questions have saved answers.

## Non-goals
- No new query logic: answers come only from the existing `/api/explain` and `/api/consequences`.
- No change to the existing dashboard or the published graph.

## Anti-goals
- Any number on the page that is not from the graph or the measurement reports.
- A page that looks like a generic SaaS template.

## Constraints
- Same Vercel deployment; no pandas; deterministic endpoints; runs where `out/causal_graph.json`
  is committed (it is).

## Approaches
- **A. New `/demo` page in the existing site — chosen.** Reuses the production query API, one link,
  deploys with `main`.
- B. Standalone claude.ai page with the graph embedded and the query logic ported to JS: a second
  query engine that could drift.
- C. Separate app/project: new deployment and cross-site setup for no gain.

## Decided
- Look: "Night observatory" (dark navy, amber and green numbers, chain lights up link by link),
  close to the current dashboard.
- Section order as above.

## Builder's calls (stated, open to correction)
- `GET /demo` serves `frontend/demo.html`, one self-contained file (inline CSS/JS).
- A small `GET /api/explain/stats` returns live counts from the loaded graph (links, nodes,
  protests, by relation, depth and evidence type, person-checked), so the counters cannot drift
  from the graph. Measured figures that are not in the graph (GDELT baseline, funnel, audit,
  labour) are constants in the page, each with a one-line source note.
- Story network: the `subgraph` the explain API already returns, drawn with d3 (cdnjs); hidden if
  d3 fails to load.
- Featured questions: 3–4 chips; their API answers are saved into the page and used only if the
  live call fails.
- Keyboard: 1–6 jump to sections, `/` focuses the question box. Counters animate once; honours
  reduced motion.
- Tests: `/demo` returns 200 and `/api/explain/stats` matches the graph, in `test_app.py` /
  pytest.
