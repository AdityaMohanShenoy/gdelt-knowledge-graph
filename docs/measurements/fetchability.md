# P0.1 — Article fetchability

Sample: **1000 URLs**, stratified round-robin by domain.
Fetched with the production fetcher (`pipeline/article_fetch.py`).

## GATE 0.1 — PASSED

Usable extraction rate: **71.1%** (threshold 40.0%).

| Metric | Value |
|---|---|
| Success rate (extracted) | 71.1% |
| Top-10 domains | 100.0% |
| Long tail | 70.8% |
| Paywalled | 4.6% |
| Complete HTML received | 79.0% |
| Median extracted length | 3688 chars |

## Outcome by status

| Status | Count |
|---|---|
| `extracted` | 711 |
| `blocked` | 153 |
| `insufficient_text` | 87 |
| `retryable_error` | 40 |
| `dead` | 4 |
| `http_error` | 4 |
| `paywall` | 1 |

## Language of extracted articles

| Language | Count |
|---|---|
| en | 431 |
| en-us | 224 |
| en-gb | 20 |
| en-ca | 10 |
| en-au | 9 |
| en-za | 4 |
| en-nz | 2 |
| gu | 1 |

## Decision

Gate clears. Phase 1 proceeds at full scope — the text channels have enough article body to work with.

Note the gap against the ingest database, which reports a far lower extraction rate. That number predates the fix to `article_fetch.py`, where `StreamReader.read(n)` truncated every response to its first buffered chunk. Stored HTML from before that fix is incomplete on disk and has to be refetched to reach the rate measured here.

Raw per-URL records: `out/fetch_probe.json`.
