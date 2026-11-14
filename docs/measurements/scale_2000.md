# Scale-up to 2,000 articles

**Status:** graph `406c4d71` has 1,379 edges over 1,171 nodes. 144 edges carry
a person's accept, carried over from v1.0 (all 206 person-accepted claims are on
an edge; merges joined some of v1.0's 149 edges). Every other edge is AI-judged.
No cycles; rebuilding gives identical bytes.

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
| Claims judged, three levels | 18,736 |
| Protest seeds | 373 |
| Protests with at least one cause in the graph | 358 |
| Edges / nodes in the graph | 1,379 / 1,171 |

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
- Most missed causes still had nothing to match in the target's pool. The two
  steps below fix that.

**Third rescue: search the whole corpus** (`scale/rescue_global.py`).
- Each missed cause no graph edge already covers became a query against every
  canonical event and condition dated before its target (180 days; a condition
  in effect), not only the target's retrieval pool.
- 1,233 distinct missed causes; 877 already covered; 316 had candidates
  (similarity ≥ 0.5, top 3 unjudged); 691 claims below level 4 were judged.
- First judges accepted 39 (κ 0.75). Blind re-check kept 36 and accepted 1 of
  39 decoys.
- Yield was low, 6%. The candidates were mostly protests *about* the stated
  cause, not the cause itself: the cause had never been extracted.

**Stated causes become nodes** (`scale/stated_causes.py`, `scale/extract/`).
- The causes still uncovered (307, deduplicated to 234 items below level 3)
  went to extraction agents. Each item shows the article, the judge's
  description and quote. The agent writes an event (as a review-added
  mention) or a condition, every field verbatim from one sentence, or skips it.
- 190 records (44 skipped, as the effect itself or an opinion), 0 dropped as
  not verbatim: 123 new events and 42 new conditions, each its own node.
  Duplicates among them are left to the node pass below.
- An undated new event gets the article's report date, often after the effect
  it is stated to cause. 47 were capped at their effect's date
  (`time_rule` in the canonical record).
- 177 claims, judged like every other claim: 145 accepted (κ 0.74). Blind
  re-check kept 138 and accepted 3 of 145 decoys (earlier rejects for the
  same effects).
- New files: `events/protest-2000.{mentions,conditions,canonical,canonical-conditions}.final.jsonl`,
  the originals plus the new rows.

**What is left.** Of the 1,020 distinct causes the judges of the earlier rounds
reported missing, 92 are still not covered by any graph edge (same lenient
embedding test as above), against about 300 before these two steps. The new
rounds' own judges reported more (277), mostly deeper causes of the new nodes.
`stated_causes.py residual` lists them; another round would start there.

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

**The first four cycles** each lost one edge:
- Police highhandedness → the cease-work withdrawal: the quote is about the
  later sit-in.
- Lathicharge → the Nabanna rally: the quote is about the bandh.
- "50th day of protests" → the RG Kar killing: this edge was judged against a
  muddled node, described as the killing but extracted from the Sep 27 protest
  call.
- The governor's refusal → "MLAs not sworn in": they were unsworn before the
  refusal.

**Three more cycles** came with the rescues and the second node pass, adjudicated
the same way (`cycles/cuts2.jsonl`, `cuts3.jsonl`). Four edges were cut, all
judged against a node that a merge later changed:
- "BJP leaders holding meetings" → the RG Kar killing: the meetings organised
  the gherao; the target was a muddled node later merged into the killing.
- The Delhi Chalo march → the Feb 12 talks, and → the Feb 10 barricades: both
  judged from the *planned* march, which merged into the march itself.
- Venugopal's protest call → the stone-pelting on the Nyay Yatra: the quote is
  the call to protest against it.

## Duplicate nodes

This uses the method of `graph_build.md`. The first pass ran on the 1,132 nodes
left after the gate; the second, after the rescues, on 1,300, skipping every
pair already decided.

| Pass | Band | same / judged |
|---|---|---:|
| 1 | ≥ 0.7 (closest evidence sentence or description) | 74 / 3,645 |
| 1 | 0.6–0.7 (seeded sample) | 2 / 200 |
| 2 | ≥ 0.7, new pairs | 35 / 549 |
| 2 | 0.6–0.7, every pair | 42 / 12,086 |

- **The full band** found 42 duplicates where the sample predicted about 100.
  Most are repeat extractions of a few big events: the Delhi Chalo march, the
  Shivaji statue collapse, Kejriwal's arrest, the RG Kar killing.
- **Recheck.** All 77 pass-2 "same" calls were read again; 4 were reversed
  (`…#recheck` rows): a Sep 27 report vs the Aug 9 protests, a call vs the
  protest it announced, a fast's launch vs a report 12 days in, an arrest vs a
  threat to arrest.
- **Blocked.** Five merges would have joined the unions' announcement of the
  Delhi Chalo march with the march, which a person kept apart; the rule below
  blocked them.
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
  unjudged 0.25–0.4 band of event pairs. Graph nodes below 0.6 similarity were
  never paired.
- **Depth.** Expansion stops after three levels, as in the 300-run. 122 nodes
  are `NOT_YET_REVIEWED`: mostly the rescued and stated causes, whose own
  causes were never searched.

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
| `events/protest-2000.claims.rescue3.L123.jsonl`, `…edges.r3.jsonl`, `…edges.blind-r3.jsonl` | third rescue |
| `events/protest-2000.stated.residual.jsonl`, `…claims.stated.jsonl`, `…edges.stated.jsonl`, `…edges.blind-stated.jsonl` | stated causes |
| `events/protest-2000.*.final.jsonl` | mentions, conditions and nodes including the stated causes |
| `events/protest-2000.status.jsonl` | search status |
| `graph/node-merges.2000.jsonl` | 197 earlier + 3,845 pass-1 + 12,635 pass-2 decisions, 5 superseding |
| `scale/` | briefs, packets, judgements, `cycles.py`, `node_pairs.py`, `aliases.py`, `rescue_missed.py`, `rescue_global.py`, `stated_causes.py`, `add_rescue.py` |

Store schema: `text_graph_2000`. Graph: `out/causal_graph.json`, version
`406c4d71643fef995a1d72f8c20bbbb48bd13d296a54b82943acc6adfede8cfd`.
