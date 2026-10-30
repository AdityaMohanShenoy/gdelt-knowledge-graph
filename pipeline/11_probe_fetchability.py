"""P0.1 — article fetchability probe.

Samples SOURCEURLs stratified by domain, fetches each through the production
fetcher, and reports what fraction of the 2024 corpus is still retrievable.
Everything text-dependent in Phase 2 rests on this number. See docs/BUILD_PLAN.md.
"""

import argparse
import asyncio
import collections
import json
import re
import sys
from pathlib import Path

import aiohttp
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from article_fetch import MAX_RESPONSE_BYTES, TIMEOUT_SECONDS, USER_AGENT, Job, fetch_once
from url_utils import normalize_url

DEFAULT_PARQUET = ROOT / "data/working/india-2024/target_events_url_validated.parquet"
CACHE_PATH = ROOT / "out/fetch_probe_cache.json"
RESULT_PATH = ROOT / "out/fetch_probe.json"
REPORT_PATH = ROOT / "docs/measurements/fetchability.md"

GATE_THRESHOLD = 0.40
TOP_DOMAIN_COUNT = 10

# Language without a new dependency: the native <html lang> attribute first,
# then Unicode script ranges for the Indian-language press.
HTML_LANG = re.compile(rb"<html[^>]*\blang\s*=\s*[\"']?([a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)?)", re.I)
NOARCHIVE = re.compile(rb"<meta[^>]+robots[^>]+noarchive", re.I)
SUBSCRIBE_FORM = re.compile(r"(?:subscribe|sign in|log in|register) to (?:continue|read)", re.I)
SCRIPT_RANGES = {
    "hi/mr/ne (devanagari)": (0x0900, 0x097F),
    "bn": (0x0980, 0x09FF),
    "pa": (0x0A00, 0x0A7F),
    "gu": (0x0A80, 0x0AFF),
    "or": (0x0B00, 0x0B7F),
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
    "ur/ar": (0x0600, 0x06FF),
}


def host_of(url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def detect_language(body: bytes, text: str) -> str:
    match = HTML_LANG.search(body[:8192])
    if match:
        return match.group(1).decode("ascii", "replace").lower()
    sample = text[:4000]
    if sample:
        counts = collections.Counter()
        for char in sample:
            point = ord(char)
            for name, (low, high) in SCRIPT_RANGES.items():
                if low <= point <= high:
                    counts[name] += 1
                    break
        if counts:
            name, hits = counts.most_common(1)[0]
            if hits / len(sample) > 0.20:
                return name
    return "en" if sample else "unknown"


def load_urls(parquet: Path) -> list[str]:
    frame = pl.read_parquet(parquet, columns=["SOURCEURL"])
    seen: dict[str, None] = {}
    for raw in frame["SOURCEURL"].drop_nulls().to_list():
        url = normalize_url(raw)
        if url:
            seen.setdefault(url, None)
    return list(seen)


def stratify(urls: list[str], sample_size: int) -> tuple[list[str], dict[str, int]]:
    """Round-robin across domains so one prolific outlet cannot dominate."""
    by_host: dict[str, list[str]] = collections.defaultdict(list)
    for url in urls:
        host = host_of(url)
        if host:
            by_host[host].append(url)
    corpus_counts = {host: len(items) for host, items in by_host.items()}

    queues = {host: iter(items) for host, items in by_host.items()}
    chosen: list[str] = []
    while len(chosen) < sample_size and queues:
        for host in list(queues):
            try:
                chosen.append(next(queues[host]))
            except StopIteration:
                del queues[host]
                continue
            if len(chosen) >= sample_size:
                break
    return chosen, corpus_counts


async def probe_one(session, url: str, host_locks, global_sem) -> dict:
    lock = host_locks.setdefault(host_of(url), asyncio.Semaphore(2))
    async with global_sem, lock:
        result = await fetch_once(session, Job(0, url, url, 0), MAX_RESPONSE_BYTES)
    body = result.body or b""
    text = result.extraction.text if result.extraction else ""
    paywalled = bool(
        result.status == "paywall"
        or NOARCHIVE.search(body[:16384])
        or (text and len(text.split()) < 500 and SUBSCRIBE_FORM.search(text))
    )
    return {
        "url": url,
        "host": host_of(url),
        "status": result.status,
        "http_status": result.http_status,
        "final_url": result.final_url,
        "bytes": len(body),
        "complete_html": b"</html>" in body[-3000:].lower(),
        "language": detect_language(body, text),
        "paywalled": paywalled,
        "text_length": len(text),
        "reason": result.extraction.reason if result.extraction else result.error,
    }


async def run(sample: list[str], cache: dict) -> dict:
    todo = [u for u in sample if u not in cache]
    print(f"{len(sample)} sampled, {len(sample) - len(todo)} cached, {len(todo)} to fetch")
    if not todo:
        return cache

    host_locks: dict[str, asyncio.Semaphore] = {}
    global_sem = asyncio.Semaphore(20)
    connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300, ssl=False)
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    done = 0
    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout, headers={"User-Agent": USER_AGENT}
    ) as session:
        tasks = [asyncio.create_task(probe_one(session, u, host_locks, global_sem)) for u in todo]
        for coro in asyncio.as_completed(tasks):
            try:
                record = await coro
            except Exception as error:  # a probe must never lose the whole run
                record = {"url": "?", "status": "probe_error", "reason": type(error).__name__}
            cache[record["url"]] = record
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(todo)}")
                CACHE_PATH.write_text(json.dumps(cache))
    CACHE_PATH.write_text(json.dumps(cache))
    return cache


def summarize(records: list[dict], corpus_counts: dict[str, int]) -> dict:
    total = len(records)
    extracted = [r for r in records if r["status"] == "extracted"]
    top_hosts = {
        h for h, _ in sorted(corpus_counts.items(), key=lambda kv: -kv[1])[:TOP_DOMAIN_COUNT]
    }

    def rate(rows):
        return round(len([r for r in rows if r["status"] == "extracted"]) / len(rows), 4) if rows else None

    tiers = {
        "top_10_domains": rate([r for r in records if r["host"] in top_hosts]),
        "long_tail": rate([r for r in records if r["host"] not in top_hosts]),
    }
    return {
        "sample_size": total,
        "success_rate": round(len(extracted) / total, 4) if total else 0.0,
        "gate_threshold": GATE_THRESHOLD,
        "gate_passed": (len(extracted) / total if total else 0) >= GATE_THRESHOLD,
        "by_tier": tiers,
        "paywall_share": round(len([r for r in records if r.get("paywalled")]) / total, 4) if total else 0,
        "complete_html_share": round(
            len([r for r in records if r.get("complete_html")]) / total, 4
        ) if total else 0,
        "status_counts": dict(collections.Counter(r["status"] for r in records).most_common()),
        "language_counts": dict(
            collections.Counter(r.get("language", "unknown") for r in extracted).most_common(8)
        ),
        "median_text_length": sorted(r["text_length"] for r in extracted)[len(extracted) // 2]
        if extracted
        else 0,
    }


def write_report(summary: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pct = lambda v: "n/a" if v is None else f"{100 * v:.1f}%"
    verdict = "PASSED" if summary["gate_passed"] else "FAILED"
    lines = [
        "# P0.1 — Article fetchability",
        "",
        f"Sample: **{summary['sample_size']} URLs**, stratified round-robin by domain.",
        f"Fetched with the production fetcher (`pipeline/article_fetch.py`).",
        "",
        f"## GATE 0.1 — {verdict}",
        "",
        f"Usable extraction rate: **{pct(summary['success_rate'])}** "
        f"(threshold {pct(summary['gate_threshold'])}).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Success rate (extracted) | {pct(summary['success_rate'])} |",
        f"| Top-{TOP_DOMAIN_COUNT} domains | {pct(summary['by_tier']['top_10_domains'])} |",
        f"| Long tail | {pct(summary['by_tier']['long_tail'])} |",
        f"| Paywalled | {pct(summary['paywall_share'])} |",
        f"| Complete HTML received | {pct(summary['complete_html_share'])} |",
        f"| Median extracted length | {summary['median_text_length']} chars |",
        "",
        "## Outcome by status",
        "",
        "| Status | Count |",
        "|---|---|",
    ]
    lines += [f"| `{k}` | {v} |" for k, v in summary["status_counts"].items()]
    lines += ["", "## Language of extracted articles", "", "| Language | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary["language_counts"].items()]
    lines += ["", "## Decision", ""]
    if summary["gate_passed"]:
        lines += [
            "Gate clears. Phase 1 proceeds at full scope — the text channels have "
            "enough article body to work with.",
            "",
            "Note the gap against the ingest database, which reports a far lower "
            "extraction rate. That number predates the fix to `article_fetch.py`, "
            "where `StreamReader.read(n)` truncated every response to its first "
            "buffered chunk. Stored HTML from before that fix is incomplete on disk "
            "and has to be refetched to reach the rate measured here.",
        ]
    else:
        lines += [
            "Gate fails. Do not proceed to P1.2 at full scope. Re-scope to either a "
            "narrower seed set concentrated on fetchable domains, or a metadata-only "
            "Stage 2 over whatever Stage 1 can read.",
        ]
    lines += ["", f"Raw per-URL records: `{RESULT_PATH.relative_to(ROOT)}`.", ""]
    REPORT_PATH.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument("--sample-size", type=int, default=1000)
    args = parser.parse_args()

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    urls = load_urls(args.parquet)
    sample, corpus_counts = stratify(urls, args.sample_size)
    print(f"corpus: {len(urls)} unique URLs across {len(corpus_counts)} domains")

    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    cache = asyncio.run(run(sample, cache))

    records = [cache[u] for u in sample if u in cache]
    summary = summarize(records, corpus_counts)
    RESULT_PATH.write_text(json.dumps({"summary": summary, "records": records}, indent=2))
    write_report(summary)

    print(json.dumps(summary, indent=2))
    print(f"\nGATE 0.1 {'PASSED' if summary['gate_passed'] else 'FAILED'} -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
