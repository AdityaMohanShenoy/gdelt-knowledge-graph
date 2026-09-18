#!/usr/bin/env bash
# Drive 07_ingest_articles in bounded batches.
#
# A single long run wedged after ~3k rows: aiohttp's connector spun at 100% CPU
# with its DNS executor threads idle and no rows progressing, and a wedged run
# never exits on its own. Bounded batches cap that damage at one batch — the
# process exits at --limit, and rows left in 'fetching' are reclaimed by the
# claim query once their lease expires.
set -uo pipefail
cd "$(dirname "$0")/.."

DB="${ARTICLE_DATABASE_URL:-postgresql://gdelt:gdelt_local@localhost:5433/gdelt}"
CONTAINER="${PG_CONTAINER:-gdelt-knowledge-graph-postgres-1}"
BATCH="${BATCH:-5000}"
BUDGET="${BUDGET:-1800}"   # seconds per batch before it is treated as wedged
# 40 and 80 both wedged: 100% CPU, DNS threads idle, no rows progressing. 20 is stable.
CONCURRENCY="${CONCURRENCY:-20}"
# Most wall-clock goes to hosts that never answer. A host silent for 10s twice
# is not worth a third 20s wait.
FETCH_TIMEOUT="${FETCH_TIMEOUT:-10}"
RETRIES="${RETRIES:-1}"

remaining() {
  docker exec "$CONTAINER" psql -U gdelt -d gdelt -t -A -c \
    "SELECT count(*) FROM article_documents
     WHERE status IN ('pending','retryable_error','fetching');"
}

while :; do
  n=$(remaining)
  echo "[$(date -u +%H:%M:%S)] remaining=${n:-?}"
  [ "${n:-0}" -eq 0 ] && { echo "refetch complete"; break; }

  ./.venv/bin/python pipeline/07_ingest_articles.py \
    --database-url "$DB" --limit "$BATCH" \
    --concurrency "$CONCURRENCY" --db-pool-size "$CONCURRENCY" \
    --per-host-concurrency 4 --timeout "$FETCH_TIMEOUT" --retries "$RETRIES" &
  pid=$!
  ( sleep "$BUDGET"; kill -9 "$pid" 2>/dev/null ) & guard=$!
  wait "$pid" 2>/dev/null
  kill "$guard" 2>/dev/null; wait "$guard" 2>/dev/null
done
