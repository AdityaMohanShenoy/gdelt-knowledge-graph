# Documented-chain matching rubric

Each packet is one 2024 event. `documented_causes` are causes that published accounts give for it
(found independently, without seeing the graph). `graph_ancestors` are the causes a causal graph
records for the same event, up to three links back, each with its label, date, and the quote on
the link. `all_nodes.json` lists every node in the graph.

For each documented cause, decide:
- `in_chain`: one of `graph_ancestors` is the same cause (the same event, decision, statement or
  standing grievance), however worded. Give its `node_id`.
- `partial`: an ancestor covers part of it or a closely related narrower/broader version (e.g. the
  documented cause is "assurances unfulfilled since 2023" and the graph has "July 18 assurance not
  kept"). Give its `node_id` and say what differs.
- `elsewhere`: no ancestor matches, but some node in `all_nodes.json` is that cause (the graph knows
  it but does not link it to this event). Give its `node_id`.
- `absent`: the graph has no node for it.

Be strict: topic overlap is not a match. Same movement but a different specific event is not
`in_chain`. Judge from the text given; do not browse.
