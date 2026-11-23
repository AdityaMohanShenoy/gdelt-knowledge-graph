# Demo Journey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace `/demo`'s middle sections with a key-driven, animated ten-stage journey from GDELT to live querying.

**Architecture:** `pipeline/41_demo_snapshots.py` also writes `frontend/demo-journey.json` (story data + compact graph). `frontend/demo.html` gets a `#journey` stage player that renders each stage from that file and hands off to `#ask`.

**Spec:** `docs/superpowers/specs/2026-11-23-demo-journey-design.md`

## Global Constraints
- No new dependencies; no pandas; deterministic output (`sort_keys=True`).
- Every number from the graph, the measurement reports or the GDELT universe manifest.
- Reduced motion respected; body text ≥ 18px on the stage; projector-legible.

## Review Focus
- Back (←) after a half-finished animation leaves a clean end state, never a half-drawn scene.
- Rapid key presses: animations of a skipped stage are cancelled, not stacked.
- `demo-journey.json` fails to load: the journey shows a plain message and the Ask section still works.
- d3 fails to load: the graph stage shows counts without the network.

### Task 1: Journey data
- [ ] Test `test_journey_snapshot_is_grounded` (tests/test_causal_query.py): file's `graph_version` = SHA-256 of `out/causal_graph.json`; every `article.spans[].text` occurs in `article.text` at its `start`; `graph.nodes` length = 1,188 and `graph.edges` length = 1,416; the three `story.causes` edges exist in the graph.
- [ ] Run → FAIL. Extend `41_demo_snapshots.py` (`write_journey()`), run it, test → PASS. Commit.

### Task 2: Stage player and stages 1–10
- [ ] Test `test_demo_journey_is_key_driven` (tests/test_frontend.py): `id="journey"`, `fetch("/static/demo-journey.json"`, `"PageDown"`, `"ArrowRight"`, ten `data-stage` entries, `prefers-reduced-motion`; story sections `id="problem"`, `id="how"`, `id="trust"` gone. Update the old story-sections test.
- [ ] Run → FAIL. Build (frontend-design skill first). Test → PASS. Visual check every stage at 1440×900 and 390 wide. Commit.

### Task 3: Ship
- [ ] Full suite, `test_app.py`; push; PR; check the Vercel preview; update the demo-script doc's demo section.
