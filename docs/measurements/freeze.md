# P4.1 — Frozen dataset v1

`protest-review-300.weak.v1.annotations.jsonl`, frozen 2026-10-31 with
`10_extract_focal_events.py freeze`.

**`dataset_kind: ai-assisted`.** Every screening and focal-event label is
`Claude (AI)`. `freeze` refuses a `gold` name for it, and that refusal was
checked on this data. The file is named `weak` per the plan.

| File (`data/evidence/focal_events/`) | SHA-256 |
|---|---|
| `protest-review-300.focal.v1.packet.jsonl` (annotations in) | `92ca07ead2756e4dc96b65c73175dbeb299b5820041a4fe7d477eeb9c43f3e43` |
| `protest-review-300.jsonl` (predictions) | `b727bb4ce302a3dbc1fe217acd605bdd7b5d3a2231a7776aeba6253048e23781` |
| `protest-review-300.splits.packet.manifest.json` | `6d0c0debae3b4bd757f186aa75d601635a60a06802ffe26a5df5b4a6172f2ada` |
| `protest-review-300.weak.v1.annotations.jsonl` (frozen) | `285dd20c87a41fa7a787035d337273aece4ee19763a668c8268ba4f79de36f61` |
| `protest-review-300.weak.v1.annotations.manifest.json` | `42eb7580e6ea49534810b3f4650991b0e06e777605bfa5484368b7c732cd76a5` |

| Split | Reviewed | Unsuitable |
|---|---:|---:|
| pilot | 35 | 27 |
| train | 59 | 83 |
| dev | 24 | 24 |
| test | 21 | 27 |
| **total** | **139** | **161** |

**Exclusions:** `UNRELATED` 117, `INSUFFICIENT_TEXT` 26, `OUT_OF_SCOPE` 14,
`NO_FOCAL_EVENT` 4.

Of the excluded records, 21 are screening-only: they were rejected by the
extractor and have no prediction. Entity labels: none yet (Phase 3).

## Acceptance

- **Reproducible.** Two `freeze` runs, to different paths, produced
  byte-identical output.
- **Self-contained.** The frozen file re-validates on its own, and its manifest
  hash matches the file.
- **Validated per split.** `evaluate --split pilot|train|dev|test` exits 0 on
  it. Only the exit code was checked; no score was read. Test is scored once,
  in Phase 6.
- **No scores in the manifest.** It holds validation results only, no Top-k or
  NER scores.

A human review of the test records would produce a v2 freeze whose test records
carry `label_source = human`.
