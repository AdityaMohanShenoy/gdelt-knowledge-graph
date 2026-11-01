# Phase 13 — Query and explanation

**Status: built.** The dashboard's Causal Evidence tab now answers "why did this
happen?" from the compiled causal graph. It replaces the demo scorer view.

The pipeline is:

    question → grounding → causal subgraph → path ranking → explanation

It runs with the standard library on the deployed function. There is no model
inference and no paid API at query time.

## How it answers

`causal_query.py` serves `/api/explain` and `/api/explain/topics`.

**Grounding.**
- Each node gets a bag of words:
  - its description, actors, holders and places;
  - the evidence quotes on its incoming links;
  - the words in its articles' URL slugs, which usually carry the headline.
- A question is scored against every node with BM25.
- The graph's weakly connected clusters stand for stories. If the best node in
  a second cluster scores at least 0.8 of the best overall, the API returns
  `clarify` with up to 5 options instead of guessing. Choosing one re-asks with
  `cluster=`.
- Within the chosen cluster, the targets are the nodes scoring at least half of
  the best.
- Choosing a protest from the topic list passes `node=` and skips grounding.

**Subgraph and paths.**
- Every cause chain ending at a target, up to three links, is a candidate.
- A path's score multiplies, for each link: strength, evidence quality
  (explicit 1.0, implicit 0.7) and corroboration (+10% per extra outlet). That
  product is scaled by how well the path's nodes match the question.
- The score only orders the paths. It is not a probability, and its weights are
  fixed and illustrative, as the old Causal Evidence weights were.
- The best chain per root cause is kept, top 5, so one cause doesn't fill every
  slot.

**Coverage**, reported with every answer:
- the share of the target's causal support (summed link strength within three
  levels) that the shown chains carry;
- how many of the direct causes they include;
- **the ancestors nobody searched**: nodes that are `NOT_YET_REVIEWED`,
  `UNVERIFIABLE` or `OUT_OF_SCOPE`. "No causes found" and "never looked" stay
  distinguishable to the reader.

**Explanation.**
- Each sentence is filled from one path's records: node labels, relation,
  strength, quality, outlets, and the edge's own evidence quote.
- The UI shows each link's quote and source-article links.
- Nothing is generated beyond the records, so an explanation cannot state a
  relation the graph does not hold. A test checks every cited relation against
  the graph.
- The display label shortens Phase 8's repeated actor lists ("ED, the ED, the
  Enforcement Directorate (ED) arrested" becomes "ED arrested"). The stored
  record is unchanged.

## Deployment decision

The runtime used to read exactly one file, the GDELT parquet (see `CLAUDE.md`).
It now reads a second one: **`out/causal_graph.json`**, the compiled graph,
published by `pipeline/40_build_graph.py --publish out/causal_graph.json`.
- It is the same bytes as the evidence-volume build, so its SHA-256 is the
  graph version the UI shows.
- It is 360 KB, committed, and loaded lazily, only by `/api/explain*`.
- Nothing else changes. The parquet still serves every other endpoint, and the
  Vercel bundle limit is unaffected.

The alternatives were folding the graph into the parquet, or querying the
Postgres store at runtime. Both were rejected: the graph is a small, versioned,
reproducible artifact, and the deployed app has no database.

The old `/api/causal/{seeds,matrix,score}` endpoints stay, because `test_app.py`
(the deploy gate) exercises them. The UI no longer calls them.

## How well it grounds

- **Headlines (58 protests).** Asking each protest's own article headline
  grounds to the right story 58 / 58 times. This is a favourable test: the
  headline shares words with the URL slug the node indexes.
- **Reworded questions (12, written for this check):** 11 grounded to the
  right story, and 1 asked for clarification with the right story first.

| Question | Grounded to | Top cause shown |
|---|---|---|
| What led to the hunger strike by junior doctors in Bengal? | workplace security (RG Kar cluster) | the RG Kar rape and murder |
| Why were Rajputs angry with Rupala? | Rajputs' protests | Rupala's controversial remarks |
| Why did Haryana government doctors go on strike? | the indefinite strike by 3,000 doctors | "repeated assurances … remain unfulfilled" |
| Why did students protest at Panjab University? | the students' protest | the delay in Senate elections |
| Why did the CAA cause protests in Assam? | protests erupted | a citizenship law criticised as discriminatory |
| Why did Sikh people protest outside BJP offices? | asks: the Sikh community protest (first), 2 others | — |

**Determinism.** The same question gives the same answer every time, with ties
broken by id, as the endpoint golden rule in `CLAUDE.md` requires.

## Limits

- **Lexical grounding.** A question has to share words with the graph's text.
  Synonyms such as "agitation" for "protest" match only if the articles also use
  them. An embedding model would help, but it would not fit the deployed
  function without a hosted model.
- **Ranking weights are illustrative.** They were not fitted. The ranking
  orders evidence and does not estimate likelihood.
- **The labels are AI's.** Every link is AI-annotated. The UI says so, and
  cites the 39 of 40 human spot-check agreement.
- **Layout.** The tab stacks at phone width, but the dashboard's global filter
  sidebar does not collapse. Phone layout of the whole dashboard is outside
  this phase.

## Files

- `causal_query.py`: grounding, retrieval, ranking, coverage and explanation
- `app.py`: `/api/explain`, `/api/explain/topics`
- `frontend/index.html`: the Causal Evidence tab
- `out/causal_graph.json`: graph `7cf84d52e097a387`
  (`7cf84d52e097a387b00fcd2e9eaf2966a1070410a63786aa26b4e6302aa6c10c`)
- `tests/test_causal_query.py`
