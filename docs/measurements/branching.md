# P0.2 — Real branching factor

Judged candidate rows: **323**

## GATE 0.2 (now GATE 11) — passes on paper; the measurement is not valid for its purpose

Mean branching factor: **0** (± 0.0), against a threshold of 4.0.

Projected for a 500-seed run at depth 3: **0 parent-group edges**.

## By depth

| Depth | Targets | Mean retrieved | Mean accepted | Median | Min | Max |
|---|---|---|---|---|---|---|
| 1 | 8 | 14 | 0 | 0.0 | 0 | 0 |
| 2 | 8 | 14 | 0 | 0.0 | 0 | 0 |
| 3 | 8 | 12.25 | 0 | 0.0 | 0 | 0 |

## Decision

*This section was rewritten by hand after `probe_branching.py summarize`
generated it (2026-10-31). The generated text read "branching is within
budget; hand annotation at depth 3 is feasible". That does not follow from
these data, as explained below.*

**What was judged.** Fresh AI judges decided every one of the 322 candidates
under `docs/causal-candidate-rubric.md`.
- They saw the target's article (up to 1,200 words, available for 14 of 23
  targets), each candidate's metadata, the scorer's reasons, and the opening of
  the candidate's article (210 of 322).
- They accepted only on an inspectable textual causal link, never on timing,
  shared actors, topic or score.
- The verdicts and reasons are in `out/branching_verdicts.jsonl`, and the
  judged worksheet is `out/branching_worksheet.csv`.

**What the zero means.** No candidate had a textual link to its target. The
zero reflects the **retrieval**, not how many causes protest events actually
have:
1. **Real causes exist in the text but are never retrieved.** For example:
   - AAP members detained (target 1165323317): the article names Kejriwal's
     arrest by the ED. No candidate is that arrest.
   - India's protest to Canada (1207717685): it names a Canadian official's
     29 October testimony. No candidate is that testimony.
   - Jamia's Gaza protest (1180205756): it names the Rafah attack and an
     earlier Jantar Mantar demonstration. The closest candidate is an unrelated
     Bengaluru detention.
2. **Candidates are (day, root-code) groups, mostly about unrelated news.**
   Examples include car launches, cocoa prices, anime and foreign politics.
   They share a date window and an event type with the target, and nothing
   else. The few the scorer graded "confirmed" or "reported", via the
   `documented` channel, have unrelated or missing text.
3. **Many targets are not protest events.** Depth 2 and 3 targets are whatever
   the scorer returned, such as a monsoon forecast, a Hyundai IPO or US gas
   prices. Some seeds are GDELT mis-codings, like a hymn slideshow or a
   missing-person reunion.

**Consequences.**
- **The gate cannot size Phases 9–11.** The branching factor of *evidenced*
  causes is still unmeasured, so this result does not show that hand
  annotation is affordable.
- **The GDELT-group scorer (`/api/causal/score`) should not be the Phase 9
  retriever.** Its candidates had no textually supported cause in 322 tries.
  This agrees with GATE 3.5, where its `pattern` grade could not tell real
  pairs from shuffled ones.
- **Phase 9 should retrieve from the text pipeline instead,** using the
  reviewed event mentions (Phase 7) and their canonical events (Phase 8),
  where causes such as "Kejriwal's arrest" are already extracted events.
- **Re-measure the branching factor there,** before sizing the Phase 10–11
  review.

| File | SHA-256 |
|---|---|
| `out/branching_worksheet.csv` (judged) | `b1d159221aaf5c93304fea5639fa6d4ad3c3e7c9db6885b7767f22aa973ac079` |
| `out/branching_verdicts.jsonl` | `b76bf5a7b00d78d6d359c6d2c37b34ca36b3bba3ad4a90c8ef1037580bc1bebf` |
| `docs/causal-candidate-rubric.md` | `da4f8b332bb9271b4f848e6d99dc07487103224e2c5137ad7d0891c6b623f6bb` |

## Caveats

- `/api/causal/score` caps its candidate list at 14, so *retrieved* is censored at that value. *Accepted* is what the gate turns on and is unaffected unless a target genuinely has more than 14 real parents.
- Candidates are (day, root code) groups, not individual events.
- Expansion follows only the strongest few candidates per level; see `out/branching_expansion.json` for the exact parameters.
