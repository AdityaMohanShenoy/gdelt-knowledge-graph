# Core-sentence rubric

Each article already has its primary development (`focal_event_summary`) and the full set of
sentences that support it (`supporting_sentence_ids`). Pick **exactly one** of those supporting
sentences as the **core sentence**: the single sentence that, read on its own, best states the
primary development.

Choose the supporting sentence that:
1. states **that the development happened** (or is ongoing / announced / called off), not just its
   cause, background, a reaction, or a detail; and
2. carries the most of **who, what action, where, when** — prefer the one a reader could check the
   summary against with nothing else.

Tie-breaks, in order:
- Prefer a full body sentence over a dateline-only, caption-like or fragmentary line.
- Prefer a sentence that states the development over one that only quotes someone about it.
- If still tied, prefer the earlier sentence.

The core sentence must be one of `supporting_sentence_ids`. Judge only from the text. Do not
browse the web.

Output per article: `core_sentence_id` (int), `confidence` (`high` / `low` — low when two
sentences are genuinely equal candidates), `note` (≤ 20 words, required when low, else null).
