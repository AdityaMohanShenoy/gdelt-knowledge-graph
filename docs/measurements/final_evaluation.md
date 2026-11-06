# Phase 14 — Final evaluation

**Verdict.** The system works end to end and holds up against controls it never
saw. It is **not complete by the plan's own definition**:
- **No causal edge is human-verified.** Every edge is AI-annotated; one human
  spot check of 40 edges agreed on 39.
- **The NER benchmark was never built.**

Recovery of independently documented causes is modest: **25% strict, 43%
including partial matches**. The graph is precise but thin, because it is built
from 139 articles.

## Completion checklist (BUILD_PLAN, Phase 14)

| Criterion | Status | Evidence |
|---|---|---|
| All final screening records are reviewed | **Met, by AI** | 300/300 `REVIEWED`, all by `Claude (AI)` (`screening.md`) |
| Every accepted focal event has exact evidence | **Met, by AI** | 139/139 have a summary and valid supporting sentences; audit passes (`focal_review.md`, `freeze.md`) |
| Every excluded record has a reason | **Met** | 161/161 `UNSUITABLE` records have an exclusion reason |
| All benchmark NER records are confirmed against the whole article | **Not met** | 0/300 have `gold_entities`. Phase 3 was never run. It is the plan's first cut line |
| The test set was never used for tuning | **Met** | Test was scored once, with the final ranker (`focal_baseline.md`) |
| Every causal edge is human-verified, with source evidence | **Met** (2026-11-01) | Every edge has a verbatim evidence span, and the repo owner reviewed all 207 edges of graph `8744efdb`: 176 accepted and 31 rejected and removed. All 176 edges in graph `85204eba` are human-verified |
| Rejected candidates are preserved | **Met** | 2,504 rejected claims with reasons, in `text_graph.claims` and `annotations` (`graph_build.md`) |
| The graph builds reproducibly from versioned inputs | **Met** | Byte-identical rebuilds; a threshold change gives a new version (`graph_build.md`) |
| Evaluation reports are saved with hashes | **Met** | Every measurement doc lists its artifacts' SHA-256; this report lists them all below |
| Queries return evidence-backed explanations | **Met** | `/api/explain` cites edges, dates, relations, strengths, quotes and URLs, and only graph records (`query.md`) |
| The demo traces a path from question to source article and sentence | **Met** | The live Causal Evidence tab shows each link's quoted sentence and its article link |

**Read every "by AI" as "agreement with an independent AI reading".** The human
work still to do is labelling: the plan's *Responsibilities* table assigns
final edge acceptance and causal direction to a human reviewer. The machinery
is not what's missing.

## External check 1 — documented-chain recovery

**Method** (`docs/documented-chain-rubric.md`):
- **Events.** 17 graph events were chosen for the depth of their outside
  coverage:
  - the farmers' rail roko
  - Wangchuk's fast
  - the CAA-rules protests
  - AAP's fast after Kejriwal's arrest
  - the Rupala protests
  - Atishi's water fast
  - the Haryana doctors' strike
  - the IMA shutdown
  - Nabanna Abhijan
  - the WBJDF fast
  - the 21 August Bharat Bandh
  - the Dharavi mosque protest
  - the Chinmoy Das rallies
  - Jarange's march
  - the "Khalistani" remark protests
  - the Wayanad MPs' protest
  - the Tamil Nadu doctors' strike
- **Reference.** Two research agents, who never saw the graph, used web search
  to collect the causes that published accounts give: Wikipedia, explainers and
  later reporting. That came to **103 documented causes from 67 sources. None of
  the sources is an article the graph was built from.** The researchers flagged
  thin or disputed sourcing per event. Most events have news coverage rather
  than true retrospectives.
- **Matching.** Two judges compared each documented cause with the event's
  causes in the graph, up to three links back.
  - `in_chain`: a graph cause is the same thing.
  - `partial`: a graph cause covers part of it, or a narrower or broader version.
  - `elsewhere`: the graph holds the cause but doesn't link it to this event.
  - `absent`: the graph doesn't have it.

| Verdict | n | Share |
|---|---:|---:|
| in_chain | 26 | 25% |
| partial | 18 | 17% |
| elsewhere | 8 | 8% |
| absent | 51 | 50% |

- **Recall:** 0.25 strict, 0.43 including partial. The graph holds 50% of the
  documented causes somewhere.
- **Direct causes**, the ones a source ties straight to the event: 33 / 75 in
  chain or partial (0.44).
- **The query layer loses little:** of the 44 matched causes, 39 appear in the
  dashboard's top-5 answer for that event.

| Kind of documented cause | in_chain or partial |
|---|---:|
| Specific trigger events | 14 / 28 |
| Conditions and grievances | 19 / 39 |
| Earlier stages of the same dispute | 6 / 18 |
| Mobilising calls and decisions | 5 / 18 |

**Where the misses come from:**
- **The corpus.** 139 articles, mostly one per protest, often report the protest
  and its headline grievance but not the call that organised it, the deadline
  that lapsed, or the incident before. The Kolkata doctors' fast is an example:
  the 27 September Sagore Dutta assault and the 4 October ultimatum are
  documented elsewhere but absent here.
- **Calls are the weakest category.** Extraction rarely produces a node for a
  bandh call, which echoes the Phase 9 miss list.
- **`elsewhere` (8) is a linking gap, not a corpus gap.** The graph knows the
  cause but retrieval or judging didn't connect it.
- **Best events:** Atishi's water fast (4/4 in chain) and the IMA shutdown
  (3/6 plus 2 elsewhere).
- **Worst events:** the Chinmoy Das rallies (1/7) and Jarange's march (1/6
  partial). For both, the documented chains run through events outside the
  corpus: Bangladesh court steps, and 2023 deadlines.

## External check 2 — negative controls on the final retrieval and judging

`pipeline/31_negative_controls.py` tests the GDELT fusion scorer, which the
final system no longer uses. A literal rerun would measure the wrong thing.
Instead, the final text pipeline was given pairs that cannot be causal and
judged blind:
- **Packets.** 20 protests drawn at random. Two fresh judges using rubric v2
  did not know which candidates were controls.
- **Mix.** Each protest's real candidates were shuffled together with:
  - **shuffled controls:** events from unrelated stories, plausibly timed (up
    to 180 days before), with no shared article, actor or place;
  - **future controls:** later events from the same story, hard negatives with
    the same topic and actors but the wrong direction.

| Arm | n | Accepted | Rate |
|---|---:|---:|---:|
| Shuffled (unrelated) | 60 | 0 | **0%** (95% upper bound ≈ 5%) |
| Future (same story, after) | 36 | 1 | 2.8% |
| Previously rejected (consistency) | 37 | 1 | 2.7% |
| Previously accepted (positives) | 32 | 27 | 84% |

- **The one "future" accept was a construction error, not a judge error.** The
  Congress "Chombu" campaign node carries a low-confidence fallback date (its
  report date, 21 April). It was launched before the 20 April protest the judge
  linked it to. Corrected, the result is **0 / 35 valid future controls
  accepted**.
- **Positives.** 5 of the 32 earlier accepts were rejected on re-judging. That
  fits the level-1/2 AI-to-AI agreement (κ 0.78–0.93), and these are the
  borderline `INSUFFICIENT_EVIDENCE` cases the agreement tables already show.

**Reading.** The pipeline does not invent links between unrelated events, and it
does not reverse time. Its errors are on the strict/lenient boundary for real,
related candidates, not on noise. This is the property that GATE 3.5 found the
old fusion scorer lacked.

## What the system is, as released

- **Corpus.** 300 GDELT-sourced 2024 India articles, screened to 139 protest
  articles.
- **Extraction.** 911 reviewed event mentions plus 213 remarks (1,124 event
  mentions in all), and 244 condition mentions. These are merged into 1,073
  canonical events and 200 conditions.
- **Graph `7cf84d52e097a387`.** 2,748 judged candidate claims give 244 accepted
  edges over 216 nodes in three levels. After 17 judged duplicate merges, the
  graph has 207 edges and 195 nodes.
  - No cycles.
  - Each edge carries a verbatim quote, its URL and its full review history.
  - The 2,504 rejections are kept as hard negatives.
- **Query.** Live on the dashboard's Causal Evidence tab. It clarifies
  ambiguous questions, reports coverage, and lists unsearched ancestors.

## Human edge review (2026-11-01)

**Blind AI re-check.** Three fresh judges re-judged all 207 edges of graph
`8744efdb` without seeing earlier votes, relations, strengths or chosen quotes.
203 earlier rejects were mixed in.
- **Graph edges:** 148 accepted again, 59 rejected.
- **Earlier rejects:** 18 accepted.
- **Rejection rate by link type:** 40% of edges joined by a node merge against
  25% of plain edges; 24% at depth 1, 31% at depth 2 and 62% at depth 3.
- **A wrong merge.** The pass exposed one: the MSP grievance had been merged
  with a single demand event. It was superseded (`graph_build.md`).

**Triage.**

| Tier | Edges | What put an edge there |
|---|---:|---|
| Needs you | 64 | The blind judge rejected it, the AI judges disagreed, or the cause is dated after the effect |
| Quick check | 60 | It exists only through a node merge, or it is a weak or implied link |
| Low risk | 83 | Every AI pass agrees and no date problem |

**The repo owner's review** covered all 124 "needs you" and "quick check" edges
on the review page.

| | Accepted | Rejected | Unsure |
|---|---:|---:|---:|
| Needs you (64) | 32 | 31 | 1 |
| Quick check (60) | 60 | 0 | 0 |

- **Every human rejection was an edge the blind judge had also rejected.** The
  person never rejected a blind-accepted edge, and overrode 27 of the blind
  judge's rejections.
- **Agreement with the blind judge:** 96 / 123 decided edges.
- **Against the original AI judge,** which had accepted all of them: 31 / 123
  (25%) of reviewed edges were wrong. In the "needs you" tier it was about half.

**Applied.**
- **Storage:** the verdicts are stored as `human-review` annotations (153; the
  one "unsure" leaves the AI's call). Rejects carry `OTHER`, "no reason given",
  because the page recorded none.
- **Precedence:** a human verdict outranks every AI judgement in the build.
- **Each edge records** whether a person checked it (`human_verified`). A
  `require_human` config builds only verified edges.

**Graph `0676f082dd4a2c4b`:**
- 176 edges over 187 nodes, no cycles, byte-identical rebuild.
- 92 human-verified edges, including 7 of the 8 at depth 3.
- 57 protests keep at least one cause.

The dashboard marks each link "Checked by a person" or "AI-annotated", and its
footer gives the counts.

**Low-risk tier, reviewed afterwards.** The owner accepted all 83. The one
"unsure" edge was accepted in conversation: Wangchuk's fast, motivated by
Chinese encroachment, with the article's quote "to protest what locals call
encroachment by China". The blind judge's rejection of it had confused it with
a later march. It is recorded as its own human verdict
(`human-edge-review.v3.jsonl`).

**Final: graph `85204eba8c8d6053`.** 176 edges over 187 nodes, **176 / 176
human-verified**, 31 human-rejected claims kept as hard negatives. No cycles,
and rebuilding gives identical bytes.

**What the review says about the AI.**
- The original AI judges accepted 207 edges, and a person rejected 31: 15% of
  the AI's accepted edges were wrong.
- All 31 were among the 59 edges a blind AI re-check rejected, and none among
  the 148 it accepted.

## What it would take to meet the plan

1. **Human edge review.** Done (2026-11-01). Every edge is human-verified. The review history already stores a human
   verdict as its own annotation, so this adds rows without rewriting anything.
2. **NER benchmark on the test split.** 48 articles at about 13 entities each.
   It is needed only to measure an NER model; nothing in the causal graph
   depends on it.
3. **A larger corpus.** Recall is bounded by the 139 articles. Most absent
   causes are reported, just not in them.

## Artifacts

Hashes of every measurement report and the main artifacts, at this release:

| File | SHA-256 |
|---|---|
| `data/evidence/final/documented-causes.json` (the external reference) | `2804c8cd509a63cfeae3697c6c7fec7abe2cf0e934ea7de672203ea1b71f27e1` |
| `data/evidence/final/documented-chain-matches.json` | `91b1d3c1ce91a6dba34604ebc6763408d8946b58f0c6a0c38e6ceb046232bb05` |
| `data/evidence/final/documented-chain-packets.1.json` | `e7a9e8f2e5d1e0b12e1a32c726342716fbb2234c71691da3a8ed5a301de690c3` |
| `data/evidence/final/documented-chain-packets.2.json` | `a547e7e22d5da9f2c0668e63cb44cbf8dde34ed5699233f1002e393409ebe2fa` |
| `data/evidence/final/negative-controls.packets.jsonl` | `2febb9f9d5477adbf9258edcdfbda57477a4c35941835d63b0b7d73c517e5ce3` |
| `data/evidence/final/negative-controls.key.json` | `f5a8a8bb6fcab4027f3beb9141efd25727a9278b2ca1a7bae4df539aac002665` |
| `data/evidence/final/negative-controls.judgements.jsonl` | `3ab97110ff8ec7b8037da40de41adf16d017dbd0840ecee3b6165484931a8f12` |
| `docs/documented-chain-rubric.md` | `23870875534cf269cc5418e0564b1da096cd7a6308e8f860bc9311500bbb4a78` |
| `docs/measurements/branching.md` | `0c8536d6ffc0d53a84fd43af1714363196879b6fff4351b042fbc74030f3fb6c` |
| `docs/measurements/canonical_events.md` | `723be2b81022e00e71e3c8f2b9d6f05f611bde18336d56f2c9c29cc6f7f518c1` |
| `docs/measurements/causal_candidates.md` | `cdbedcf3329764600e61c2828c6bf28b5bd57fd68318a6a27dac5af85af1fc65` |
| `docs/measurements/causal_edges.md` | `afabd240761493ae58baa7d79a4329002fb51e73fbe57b0ceefd26a5eecfbfe4` |
| `docs/measurements/conditions.md` | `e328759923207659b46bf9d38eba633c29aed490dee69013f42b38a797a4981e` |
| `docs/measurements/event_mentions.md` | `a86269edff03adf41dfe892ccd1e9e97332c8ed14180115f4696d22afb644089` |
| `docs/measurements/expansion.md` | `56d4bbeb92cfb810ad2994aa69a42b238d5528a460f989ee42999b2c11746708` |
| `docs/measurements/fetchability.md` | `f3545116314f4b2dfb7cf7ed027715cfc4bc2ab6cbc9c48612f5594e647f3fed` |
| `docs/measurements/focal_baseline.md` | `e8dfee2fd69fe6912e41a0eaa60d476d293bc0a0e3619da251135d801aa4df2e` |
| `docs/measurements/focal_review.md` | `d4e241f26f2c716290a644fc5ea3511794c374e0ea0d5bc452cb23326f2d7346` |
| `docs/measurements/freeze.md` | `29fd2d6bb7dcd3a97048aa68146ccfd3ee770cef1887ca57acb010caff04bb9b` |
| `docs/measurements/graph_build.md` | `2004cf4bf720b360c5ef5ce4c96c6b5ade10cca6e27e2b1c4632b577e8fe5c0c` |
| `docs/measurements/negative_controls.md` | `34cc30b33d199e9d99ef432c020328a5e9b13b8ef5a8be472129d3636b130171` |
| `docs/measurements/query.md` | `ca0e1c108af41d3427939df4491f97fcb039966a24e002bdd5fc46a31a9fd858` |
| `docs/measurements/screening.md` | `e0da612cb069ab7c5e900d67dcad5d42e9fae53e07fcd14afd8db7aeed0f134c` |
| `docs/measurements/splits.md` | `dbe7fac211124659b3612017f2ab70b48e61dbf477360af2e7a350e613b14ffa` |
| `docs/causal-annotation-rubric-v2.md` | `c27eff78825d99fbd069db5d22fa955d2cddc5c089cc7403dc796bfd1a8822cb` |
| `docs/causal-annotation-rubric.md` | `10dcc8b21eeba8f1d29e2d067a65ff988cfc724200f3051d996c543dddea6728` |
| `docs/causal-candidate-rubric.md` | `da4f8b332bb9271b4f848e6d99dc07487103224e2c5137ad7d0891c6b623f6bb` |
| `docs/cause-rubric.md` | `41964fa324171c8a4a95c2294bc8ead050d8d32cab72961d09827c80649edc11` |
| `docs/condition-audit-rubric.md` | `245d7b9d52b87f0b652cc6ce8298e878c869124f481712da52129fedc9785746` |
| `docs/condition-remark-rubric.md` | `ed96df0ef3ddf25470fbcfb84b823fbbd90ef06d15f7f20f6514de6487fa216b` |
| `docs/core-sentence-rubric.md` | `de2b72587d5594da2f52c2d90596ee434ca4b4441a2985987dd7e8b7124eeb46` |
| `docs/documented-chain-rubric.md` | `23870875534cf269cc5418e0564b1da096cd7a6308e8f860bc9311500bbb4a78` |
| `docs/event-mention-review-rubric.md` | `355adc439b299b6459d9bd20cd483895d7a0dfaf4b894329b29cdb1ffd95f63a` |
| `docs/event-review-step-rubric.md` | `4e9ce1981f0bb7886af0638c9d149400ce5ced4bf13b2a31b8795edaa5600b38` |
| `docs/focal-event-rubric.md` | `41e10500eafd8fa68927bf9840a9b34647e72a33d889bb22993c3183654f6618` |
| `docs/recall-rubric.md` | `d66b253265c8a0ab12a4a4b03dee9b64a60f07c28c162fe0e3e52711826e64f7` |
| `docs/same-condition-rubric.md` | `8ddf9fe1710a3ba58e9c132a01e483a133153a3068364176e679964ab8ca95a2` |
| `docs/same-event-rubric.md` | `19b7d24d57802c8bae0a0dfb90e61261863c3544b6aee341e1a776244b01faad` |
| `docs/same-node-rubric.md` | `1c494f5ed950fb51861b7e8690f409f1f5c4046bb4d7400d157b384295a0fd9a` |
| `docs/screening-rubric.md` | `87c4340be3d77f3aa97560a14587d3bad9642a4c138152cd11ceca21286ec054` |
| `out/causal_graph.json` | `7cf84d52e097a387b00fcd2e9eaf2966a1070410a63786aa26b4e6302aa6c10c` |
| `data/evidence/graph/node-merges.v1.jsonl` | `5124510d937a6371a1d93d0cb7a9413fc9f061c6d1cec7633040306973731b32` |
| `data/evidence/events/protest-review-300.edges.v1.jsonl` | `e08fd9c7463a40cee015e04d5b7cd29d7e5a091896df3d1e8fd6118f44c0897a` |
| `data/evidence/events/protest-review-300.edges.l2.jsonl` | `30fc40fe903842de20ef57f22a45e0c789e633301a27b227d6b3370f0c944313` |
| `data/evidence/events/protest-review-300.edges.l3.jsonl` | `6bbf58f8b1718b712026853f21b777ffa460f7efd1068356bf426a1f41ff718b` |
| `data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl` | `100cbfa34758c90cdcb1f5bcce3a555329d8fc8d8c668deee1d653bded3da079` |
| `data/evidence/events/protest-review-300.edges.v1.human-spotcheck.jsonl` | `a4c45f0b332ebcdd6db1fd750e5d810893cf073b56bd2fbbd4e88df5f4957478` |
| `data/evidence/graph/human-edge-review.v1.jsonl` (owner's verdicts, 154 claims) | `4297deb4c16780ef9c92b3801c00e0c9d8d24995bdc46f549a8767e1b83f16ed` |
| `out/causal_graph.json` (graph `0676f082`, after human review) | `0676f082dd4a2c4b713eaec23db33bdc4d81f939452e9e3211963e34213d5fcf` |
| `data/evidence/graph/human-edge-review.v3.jsonl` (all 207 edges reviewed, 238 claims) | `0d28bd08d260848e1a3ad7ab0f95b0b5a1f747718d09163f55c0c263c3015315` |
| `out/causal_graph.json` (graph `85204eba`, every edge human-verified) | `85204eba8c8d6053b93eee9c93b9add3573e8250bb6925d83227870e9ecad064` |
