# P3.5 — Negative controls

60 target events, a 7-day window per arm. Every arm is scored by the same code path as `/api/causal/score`.

| Arm | Pairs | Kept (confirmed+reported+pattern) | Mean confidence |
|---|---|---|---|
| `real` | 1,147 | 5.4% | 0.3221 |
| `shuffled` | 557 | 4.0% | 0.3182 |
| `future` | 1,058 | 3.1% | 0.3148 |

## Grade distribution

| Grade | `real` | `shuffled` | `future` |
|---|---|---|---|
| confirmed | 1.6% | 0.0% | 0.0% |
| reported | 0.1% | 0.0% | 0.0% |
| pattern | 3.8% | 4.0% | 3.1% |
| weak | 94.6% | 96.0% | 96.9% |
| dropped | 0.0% | 0.0% | 0.0% |

## Discrimination per grade

How much more often a grade fires on real pairs than on shuffled ones. **1.0 means the grade cannot tell them apart.**

| Grade | real / shuffled |
|---|---|
| confirmed | ∞ (never fires on shuffled) |
| reported | ∞ (never fires on shuffled) |
| pattern | 0.95× |
| weak | 0.98× |
| dropped | ∞ (never fires on shuffled) |

## GATE 3.5

False-positive rate, shuffled: **4.0%**. Future window: **3.1%**.

**The gate fails.** `pattern` fires at 0.95× on real pairs versus shuffled — which is to say, not at all. That grade exists to catch links Stage 1 never saw, and it is finding them just as readily in randomness. It is measuring corpus structure: `prior` and `contrastive` are country-level type-pair statistics that know nothing about the specific pair being scored.

The separation visible in `confirmed` and `reported` is not evidence against this. Those two are carried by the `documented` channel, which is empty by construction in both control arms, so their gap is guaranteed rather than measured.

Per the plan: do not proceed to Phase 4 on a scorer that finds causes in randomness. The fix belongs in P3.2 and P3.4 — a textual channel that reads the specific pair, and weights fitted on labelled decisions instead of the illustrative ones in use now.

Raw per-pair records: `out/negative_controls.json`.
