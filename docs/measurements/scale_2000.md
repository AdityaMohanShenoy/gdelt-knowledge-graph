# Scale-up to 2,000 articles

**Status:** graph `bf3d9811` has 1,259 edges over 1,065 nodes. 149 edges are
human-verified, carried over from v1.0; every other edge is AI-judged. No
cycles; rebuilding gives identical bytes.

The run applies the methods of the 300-article run to 1,700 more articles with
no human review step. The owner's instruction was: *"whatever method we have
used apply the same for everything, i cant review every event it has to be
self sustained."* Where the 300-run had a person, this run uses a calibrated AI
check, described below. Nothing was paid for: every judge is a Claude subagent
and every model is local.

## What changed in the method

1. **Extension sample.**
   - The next 1,700 articles in the same seeded md5 order, skipping the 300
     already screened (`10_extract_focal_events.py screen --exclude`).
   - New articles get split `extension`, reviewer `Claude (AI)`, label source
     `ai_assisted` (`12_apply_ai_labels.py`).
2. **Stable ids.** A grown cluster keeps the smallest earlier id it contains
   (`21_canonicalize.py` / `23_extract_conditions.py build --previous`).
   - Ids absorbed by a merge are remapped through an alias map, so the
     300-run's claims and human verdicts stay attached.
   - Every earlier decision is reused by content key; only new items were
     judged.
3. **Sampled bands.**
   - Same-event pairs: all pairs scoring ≥ 0.4, plus 300 sampled from 0.25–0.4.
   - Condition pairs: all ≥ 0.65, plus 100 sampled from 0.55–0.65.
   - The 300-run judged its whole band, which at this size is about 260,000
     event pairs.
4. **Retrieval cap.**
   - `22_retrieve_causes.py --cross-article-cap 8` keeps every same-article
     candidate, plus the top 8 from other articles per target.
   - On the 300-run this would have kept 151/156 level-1 and 68/71 level-2
     accepts.
   - Level 1 also judged ranks 9–15 (`l1x`) and a *missed-cause rescue*
     (`l1r`): each cause a judge said was missing, matched by embedding
     (≥ 0.5) to an unjudged candidate.
5. **Blind re-check replaces human review** (`graph_store.compile_graph`).
   Without a person, an AI-accepted edge needs a second, blind AI accept.
6. **Cycles are adjudicated, not cut by rule** (see below).
7. **Merges never override a person** (`graph_store.representatives`, below).

## Funnel

| Stage | Count |
|---|---:|
| Articles screened (300 + 1,700) | 2,000 |
| Kept as protest stories (139 + 776) | 915 |
| Event mentions | 7,083 |
| Distinct events / merged across articles | 6,152 / 468 |
| Grievance and condition mentions / distinct conditions | 1,146 / 810 |
| Same-event pairs judged / judged same | 8,913 / 1,970 |
| Same-condition pairs judged / judged same | 2,661 / 1,440 |
| Claims judged, three levels | 17,868 |
| Protest seeds | 373 |
| Protests with at least one cause in the graph | 343 |
| Edges / nodes in the graph | 1,259 / 1,065 |

## Causal judging

Rubric v2, 25% of seeds double-annotated, as in the 300-run.

| Level | Claims judged | Accepted | κ | Recall of stated causes |
|---|---:|---:|---:|---:|
| 1 (cap 8) | 5,002 | 639 | 0.89 | 0.82 |
| 1, ranks 9–15 | 2,239 | 79 | 0.81 | — |
| 1, missed-cause rescue | 220 | 36 | 0.95 | — |
| 2 | 5,822 | 464 | 0.82 | 0.74 |
| 3 | 1,726 | 127 | 0.88 | 0.78 |

- **Recall** is the share of causes the judges said an article states that
  some candidate represented.
- The two supplementary sets were small and targeted, so their recall is not
  comparable.

**Recall is understated.**
- **Why.** A packet shows only the candidates still to be judged. A cause already
  linked to the same effect is invisible to the judge, who then reports it as
  "missed".
- **Measured.** A missed cause counts as covered when an accepted edge into the
  same graph node matches it: the cause's description or quotes, by local
  embedding, similarity ≥ 0.5. This is lenient, so read it as an estimate.

| Level | Reported missed | Already covered | Recall, reported → estimated |
|---|---:|---:|---|
| 1 | 145 | 95 | 0.82 → ~0.93 |
| 2 | 161 | 56 | 0.74 → ~0.82 |
| 3 | 36 | 9 | 0.78 → ~0.82 |

About one stated cause in eight to ten never reached a judge.

**Second rescue.** This repeats the level-1 rescue for levels 2 and 3, and for
the causes the blind judges reported missed.
- 402 missed causes were matched by embedding (≥ 0.5) against the uncapped
  retrieval pools, which are retrieval without the cap of 8.
- 265 had an unjudged pool to search; 114 candidates were found.
- The first judges accepted 27 (25% double-annotated, κ 1.0).
- The blind re-check kept 25 and accepted none of the 87 rejected ones.
- 111 were added one level below their target. 3 would have been level-4
  edges and are left out.
- Net effect on the graph: +20 edges, +1 protest with a cause.
- Most missed causes still have nothing to match. Typically the stated cause,
  often the RG Kar killing or a union's march call, was never extracted as an
  event in that article. Fixing that is an extraction change, not a judging
  one.

## Blind re-check (the gate that replaced the person)

**Calibration.** On the 300-run, a person reviewed every edge:
- They rejected 31 of the 59 edges a blind AI re-check had rejected.
- They rejected none of the 148 it accepted.

So a blind accept was strong evidence, and a blind reject was a coin flip.

**This run.** 19 fresh judges re-judged all 1,352 AI-accepted edges without a
human verdict. They did not see earlier votes, relations or quotes. The packets
also held 1,352 earlier rejects from the same effects, at a 1:1 ratio.

| | Blind accept | Blind reject |
|---|---:|---:|
| AI-accepted edges | 1,209 (89%) | 143 |
| Earlier rejects (decoys) | 44 (3%) | 1,308 |

- **Decoys.** The judges accepted 3% of decoys, against 9% for the 300-run's
  blind pass. They were not simply accepting what they were shown.
- **Rejections.** They rejected 11% of AI accepts, against 28% on the 300-run.
  Either the first judges are more precise under rubric v2 and the tightened
  quote checks, or this blind pass is more lenient on the hardest cases. The
  decoy rate argues for the first, but no person has checked it.
- **Dropped edges.** The 143 blind-rejected edges are out of the graph.
  On the 300-run's evidence, about half of those were right.

## Cycles

A cause cannot be its own effect, so every cycle holds a wrong edge.

**The rule failed.** A fixed rule — reject the weakest edge, with ties to a
condition, then to the latest cause — picked the right edge in some cycles
and the wrong one in others:
- In the Dallewal cycle, it cut "his 17-day fast caused his worsening health".
  It kept "worsening health motivated the fast", whose quote is about the
  Supreme Court's concern.
- In the Nabanna cycle, it would have cut "the march prompted the
  lathicharge". The wrong edge was "lathicharge triggered the march", whose
  quote is about the BJP bandh.

**Order of operations.**
1. Run the blind gate first. It removed three of the first four cycles by
   rejecting their wrong edge.
2. Find cycles on the merged graph, as the build sees it.
3. A fresh judge reads each cycle's edges, evidence and node descriptions
   (`data/evidence/scale/cycles.py --packet`), and names the edge whose evidence
   does not support it.

**The four cycles** each lost one edge:
- Police highhandedness → the cease-work withdrawal: the quote is about the
  later sit-in.
- Lathicharge → the Nabanna rally: the quote is about the bandh.
- "50th day of protests" → the RG Kar killing: this edge was judged against a
  muddled node, described as the killing but extracted from the Sep 27 protest
  call.
- The governor's refusal → "MLAs not sworn in": they were unsworn before the
  refusal.

## Duplicate nodes

This uses the method of `graph_build.md`, on the 1,132 nodes left after the gate.

| Band | same / judged |
|---|---:|
| ≥ 0.7 (closest evidence sentence or description) | 74 / 3,645 |
| 0.6–0.7 (seeded sample of 200 out of 10,359) | 2 / 200 |

- **Misses.** At the sampled rate, about 100 duplicates remain in the unjudged
  lower band.
- **Ongoing campaigns.** The brief keeps reports of an ongoing campaign on
  different dates apart, for example the Shambhu camp or a hunger strike on
  day 6 and day 10. So the same campaign can stay as several nodes. Judges were
  strict, and sometimes inconsistent between equal-date and different-date
  reports of one campaign.

**New build rule: a merge never joins what a person kept apart.**
- **The case.** A person accepted "the unions called the Delhi Chalo march" →
  "the march". Two AI "same" calls then joined call → campaign → march.
- **The rule.** `representatives` skips a merge that would put both ends of a
  person-accepted edge in one node, and lists it in
  `counts.merges_blocked_by_human`. One merge was blocked.
- **No effect on v1.0.** The count appears only when non-empty, so graph
  `85204eba` still rebuilds to the same bytes.

**Fix: `node-merges.v2.jsonl` drops the MSP correction on a fresh load.**
- Its superseding "different" row for the MSP merge has the same `key` as the
  original "same" row. The store loads with `ON CONFLICT DO NOTHING`, so the
  correction is silently dropped.
- The old store holds it under `…#2`, which is why v1.0 was right.
- `node-merges.2000.jsonl` uses the `#2` key. The v2 file is left as is,
  because its hash is published.

## Other fixes found on the way

- **Same-event judges and ongoing campaigns.**
  - The brief's example ("same JPC demand on Adani, reported days apart")
    pushed judges toward merging.
  - The example now reads "different", and the brief has an explicit
    campaign rule.
  - 139 early cross-day "same" calls were re-judged, and 21 flipped.
- **Quote checks.** `24_annotate_causes.py apply` now looks for quotes in the
  seed's shown effect articles too. Claims of the same effect can carry
  different effect evidence once levels are merged.
- **Focal seeds.** `event_mentions.apply_review` now accepts a review that
  judged the focal seed. Dropping those verdicts lost 265 of 776 focal events.
- **Orphaned nodes.**
  - 23 graph nodes are no longer reachable from any protest, because the gate
    removed the edge above them.
  - Their edges passed both judges and stay.
  - Their search status falls back to the pre-gate expansion
    (`protest-2000.status.jsonl`).

## Not done

- **No person reviewed any new edge.** The precision of blind-accepted edges
  rests on the 300-run calibration, not on a check of this run.
- **Missed merges.** About 800 same-event merges are estimated missed in the
  unjudged 0.25–0.4 band. Some duplicate events therefore remain as separate
  nodes, beyond the about 100 duplicate nodes estimated above.
- **Depth.** Expansion stops after three levels, as in the 300-run. 20 nodes
  remain `NOT_YET_REVIEWED`.

## Artifacts

All evidence lives under `data/evidence/`, which is gitignored like every
earlier run's.

| File | What |
|---|---|
| `focal_events/protest-2000.weak.v1.annotations.jsonl` | 2,000 articles, 915 kept |
| `events/protest-2000.canonical.jsonl`, `…canonical-conditions.jsonl` | 6,152 events, 810 conditions |
| `events/protest-2000.L{1,2,3}.{claims,edges,edges.second}.jsonl` | per level, aliases remapped |
| `events/protest-2000.edges.blind.jsonl`, `…blind-r2.jsonl` | blind re-checks |
| `events/protest-2000.claims.rescue2.jsonl`, `…edges.r2.jsonl` | second rescue |
| `events/protest-2000.status.jsonl` | search status |
| `graph/node-merges.2000.jsonl` | 197 earlier + 3,845 new + 1 superseding decision |
| `scale/` | briefs, packets, judgements, `cycles.py`, `node_pairs.py`, `aliases.py`, `rescue_missed.py`, `add_rescue.py` |

Store schema: `text_graph_2000`. Graph: `out/causal_graph.json`, version
`bf3d98116105de7c32d70a73886c2eca3e199c6a2060774064d8f3a1c850f53b`.
