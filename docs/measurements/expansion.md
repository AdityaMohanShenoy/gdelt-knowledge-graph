# Phase 11 — Recursive expansion

**Status: the acceptance check is met, with AI annotators.**
- The 63 protest seeds expand to a three-level DAG: 216 nodes and 244 accepted
  edges.
- Branches converge on shared nodes: 49 causes explain more than one effect.
- The cycle check finds no cycle.
- The expansion stops at depth 3. The 5 nodes left unexpanded keep the status
  `NOT_YET_REVIEWED`.

All labels are AI (`Claude (AI) A` / `B`, `ai_assisted`), except the human
spot-check of Phase 10 below.

## Method

`pipeline/causal_expansion.py` and `pipeline/25_expand.py` compute the state
after each level. Retrieval is `pipeline/22_retrieve_causes.py --targets`, and
judging is `pipeline/24_annotate_causes.py` under
`docs/causal-annotation-rubric-v2.md`.

1. **Next targets.**
   - Every accepted cause not yet expanded becomes a target.
   - The node is shared: a cause reached by several branches is expanded once,
     and later edges point at the same canonical event or condition.
2. **Where a branch stops.** No targets are generated past these points.
   - **No supported parent.** All candidates were rejected, or there were none.
   - **Before 2024-01-01.** These nodes get status `OUT_OF_SCOPE`, a fifth
     status added to the plan's four. Folding them into `NOT_YET_REVIEWED`
     would claim someone still means to look.
   - **Unverifiable.** An announced or other unasserted event cannot be shown
     to have happened, so its causes cannot be verified.
   - **Rejected branch.** A rejected claim is never an edge, so it is never
     expanded.
3. **Retrieval for a cause.**
   - An event target uses the same rules as protests (Phase 9b, tightened).
   - A condition target dates from its stated start, or from its first report
     if no start is stated, never from the guessed fallback. Its candidates
     come only from its own articles. This is marked `ponytail:` in the code,
     to widen if conditions turn out to miss stated causes.
   - **A target's own descendants are never its candidates.** An effect cannot
     also be the cause, and proposing it would invite a cycle. This removed 100
     candidates at level 2.
4. **Judging.**
   - Rubric v2 applies Phase 10's taxonomy revision: five types, with
     CONTRIBUTES_TO folded into MOTIVATES, ENABLES dropped, and solidarity
     actions named under ESCALATES.
   - The effect may be any event or condition.
   - Judges were blind to retrieval signals.
   - A quarter of each level was double-annotated, and each judge worked in
     its own folder.
5. **Statuses.**
   - `PARENTS_FOUND`
   - `NO_SUPPORTED_PARENT_FOUND`: judged with nothing accepted, or no
     candidate at all.
   - `NOT_YET_REVIEWED`
   - `UNVERIFIABLE`
   - `OUT_OF_SCOPE`

   The status is recorded for every node reached, with its depth and the
   number of effects it explains.

## Results

| Level | Targets | Candidates | Accepted | Precision | New nodes | Recall (named causes) |
|---|---:|---:|---:|---:|---:|---:|
| 1 (protests, Phase 10) | 63 | 1,101 | 156 | 14% | 131 | 0.83–0.87 |
| 2 | 124 | 1,386 | 71 | 5% | 17 | 0.76 |
| 3 | 12 | 261 | 17 | 7% | 5 | 0.94 |
| **Total** | | **2,748** | **244** | | | |

Recall here is accepted / (accepted + missed), with the missed causes listed by
the judges.

**The graph converges fast.**
- Most level-2 edges point at causes already in the graph. 71 edges added only
  17 new nodes.
- 49 causes explain more than one effect.
- The most shared:
  - the farmers' demand for a legal MSP guarantee: 14 effects
  - the RG Kar rape and murder: 10 effects, plus 6 more through a duplicate
    node (see limits)
  - the farmer unions' Delhi Chalo call: 5 effects
- **The branching factor falls with depth: 2.5, then 0.6, then 1.4.**
  - 2.5 accepted parents per protest.
  - 0.6 per level-1 node.
  - 1.4 per level-2 node, over only 12 targets.

  GATE 11's worry of more than 100k edges at depth 3 does not arise: depth 3
  holds 244 edges.

**Why deeper levels accept less.** Most level-2 targets are grievances. Their
retrieved candidates are mostly the protests against them, which the judges
rejected as `WRONG_DIRECTION` (373 at level 2). The articles state a cause for a
protest far more often than for the grievance behind it. Of 81 conditions
reached, 66 have no supported parent.

**Search status of the 216 nodes reached.**

| Status | Events | Conditions |
|---|---:|---:|
| PARENTS_FOUND | 93 | 8 |
| NO_SUPPORTED_PARENT_FOUND | 32 | 66 |
| NOT_YET_REVIEWED | 4 | 1 |
| UNVERIFIABLE | 7 | 0 |
| OUT_OF_SCOPE | 1 | 4 |

**Example chain (depth 3).** The Punjab–Haryana border sealing
→ TRIGGERS → the farmers' Delhi march
→ TRIGGERS → the SKM (Non-Political) and KMM protest
→ ESCALATES → a United Farmers Front protest.

**Cycle check.** None, over all 244 accepted edges. The descendant exclusion
makes a cycle unlikely, and same-day edges are the only way left to form one.

## Agreement

| Level | Double-annotated | Accept/reject κ | Relation κ | Splits |
|---|---:|---:|---:|---:|
| 1 | 283 | 0.93 | 0.88 | 6 |
| 2 | 350 | 0.78 | 1.00 | 11 |
| 3 | 100 | 0.85 | 0.67 | 2 |

- **Level 2 is the least consistent level.** 9 of its 11 splits are one judge
  accepting where the other said `INSUFFICIENT_EVIDENCE`, `DUPLICATE_EVENT` or
  `TEMPORALLY_INVALID`. Accepts are rare at this level (22 both-accepted), so
  κ falls quickly with each split.
- **Relation agreement holds on the five-type taxonomy.**
  - Level 2 has no relation confusion at all.
  - Level 3's κ 0.67 rests on 6 pairs, with one MOTIVATES/TRIGGERS split.

## Human spot-check (Phase 10 edges)

The repo owner reviewed 40 edges from `edges.v1` on a review page: 20 accepted
and 20 rejected, drawn at random.

| | Agree | Disagree |
|---|---:|---:|
| AI accepted | 20 | 0 |
| AI rejected | 19 | 1 |

- The one disagreement: the AI rejected the Salem doctors' Friday candlelight
  march as a cause of their Saturday work boycott. The human judged it a cause.
- This is the same borderline pattern behind most AI-to-AI splits: an earlier
  action in the same campaign, with no connective in the text. Rubric v2 already
  says that "after"/"following" count as explicit. A same-campaign stage the
  text doesn't link is still left to judgement.
- Edges are append-only, so the verdicts are kept as their own human-labelled
  evidence and not written back over the AI's: `edges.v1.human-spotcheck.jsonl`.

## Known limits

- **Duplicate cause nodes inflate convergence.** The RG Kar killing exists as at
  least two canonical nodes ("rape and murder", "brutally raped and murdered"),
  because Phase 8 merges only judged pairs within kind and window. Its true
  fan-out is about 16, not 10 and 6.
- **Some edges need a second look.** In the farmers' chains, one edge reads "the
  government sealed off the border → TRIGGERS → the farmers began the march". The
  sealing was put up against the announced march, so PROMPTS_RESPONSE in the
  other direction is arguably more accurate. A judge accepted it from text that
  places the two together. AI-only labels at depth 2–3 deserve a human pass
  before anyone relies on these chains.
- **Condition targets look only within their own articles.** That keeps
  precision up but finds few parents: 8 of 81 conditions have one.
- **Stopped at depth 3.** The 5 remaining targets are `NOT_YET_REVIEWED`.
  Continuing is one more round of `22 --targets`, `24 packets/apply` and `25`.

## Files

| File | SHA-256 |
|---|---|
| `…expansion.l1.json` / `.targets.json` | `394c0ca6d167cdd2ca47180dd54a73d9ec810aec167fc2769b5887b88ae22d25` / `300e1e6f7c562d2ddb0ea3425bc5330ef3b86998e7be9d7a5b19d5146387466a` |
| `…claims.l2.jsonl` | `3d377062c81af05388ebef9aba7a39340be45f5aa5649d2315468eec9468c692` |
| `…edges.l2.jsonl` / `.second.jsonl` / `.missed.jsonl` | `30fc40fe903842de20ef57f22a45e0c789e633301a27b227d6b3370f0c944313` / `ad61b97d52bd45ae07106b9473f56e59011b05a06ee75b75e259d27038bb8e41` / `1a01d7c6a882c07d6fe81fb32ccbfe3bb78ce48f22b063b0665627bda2834f9d` |
| `…edges.l2.key.json` / `.judgements.jsonl` / `.second-judgements.jsonl` | `4c8ca094af3634ae3f319e48fc433e8aa31dc7bf0e4ab1805c3c121e1ef29aea` / `3b5c6775c0853a87d4de227a948bd5de8dd18cff9cb697a819d6ca255ec37ea9` / `324200acd0af0bdbe7c3b918f41604f429768785dbc317ed73dbbf93cb98ab01` |
| `…expansion.l2.json` / `.targets.json` | `2c376f265a3ccc6f52802155e5cd72ba5a451228ed8b66f96ffda560d41728b8` / `15329c14f33afce3c89ca1e5f07f90eb73d0016bf2a2ba91300c1f6ad135df20` |
| `…claims.l3.jsonl` | `a48e2f5aa885961d7ccce3d4a092e093021a8c73fa30ba0a9712ab78cc3487c5` |
| `…edges.l3.jsonl` / `.second.jsonl` / `.missed.jsonl` | `6bbf58f8b1718b712026853f21b777ffa460f7efd1068356bf426a1f41ff718b` / `8306a4077c6dbbf11d5e490b9aa57f10c287de343dff3e49a94f37d83607d5df` / `7937cb57ceeb6635c783d15078e17202f20c2f5851cfbeb326cfde3b761cb3b2` |
| `…edges.l3.key.json` / `.judgements.jsonl` / `.second-judgements.jsonl` | `17cb850f31b474e6eba9a8db9c3d34f0192ddd4eaf548e4edc47af6ac2d29577` / `cbfc3a93bd5e4efd255021e69cf982cbe00fc1bfb86c54ade371daf49d75e68d` / `bf71bcc76c8827dd935388184c67ad80244ffca2523a74f89c4c5a09427ebd59` |
| `…expansion.l3.json` (current state) | `a52cd202f4cdc693cdeb9ee14eeea87eca74c079c6bc7b5d8c0fc97751ab8fab` |
| `…expansion.l3.status.jsonl` | `29e9777a85b2f03d6c653978b17f35902de78d7fa28dd31da4b00602272af0d4` |
| `…expansion.l3.targets.json` (5 unexpanded) | `642d3678039e910e9167a8dfe85c2164b23dcc87baab274851fe77919803e631` |
| `…edges.v1.human-spotcheck.jsonl` | `a4c45f0b332ebcdd6db1fd750e5d810893cf073b56bd2fbbd4e88df5f4957478` |
| `docs/causal-annotation-rubric-v2.md` | `c27eff78825d99fbd069db5d22fa955d2cddc5c089cc7403dc796bfd1a8822cb` |

`…` is `data/evidence/events/protest-review-300`.
