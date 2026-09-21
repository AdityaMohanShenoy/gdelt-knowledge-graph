import datetime
import json
import re
from dataclasses import dataclass, replace
from html import unescape
from typing import Any

import trafilatura

MIN_ARTICLE_CHARS = 400
MIN_ARTICLE_BLOCKS = 2
MIN_SENTENCE_COUNT = 3
MAX_GATE_CUE_LENGTH = 1200
# v3 captures the publication date and honours a max_date bound. The bump is
# load bearing: 09_reprocess only promotes rows whose extractor_version
# differs, so without it a backfill would skip every already-extracted row.
EXTRACTOR_VERSION = f"trafilatura-{trafilatura.__version__}-precision.v3"

PAYWALL_CUES = re.compile(
    r"(?:subscribe to continue|subscribe to read|sign in to read|premium content|"
    r"for subscribers|become a subscriber|membership required|unlock this article|"
    r"this article is for subscribers)",
    re.IGNORECASE,
)
BLOCKED_CUES = re.compile(
    r"(?:access denied|verify you are human|checking your browser|enable javascript|"
    r"bot detection|unusual traffic|temporarily unavailable|captcha)",
    re.IGNORECASE,
)
ERROR_PAGE_CUES = re.compile(
    r"(?:\b(?:403|404|410|500)\b|page not found|not found|page doesn['’]?t exist|"
    r"article unavailable|content not available|error loading|server error|"
    r"requested page could not be found)",
    re.IGNORECASE,
)
PROMOTIONAL_CUES = re.compile(
    r"(?:subscribe to our newsletter|download our app|follow us on|advertisement|"
    r"sponsored content|read more stories|sign up for our newsletter)",
    re.IGNORECASE,
)
PRESS_RELEASE_CUES = re.compile(
    r"(?:\bprnewswire\b|\bnewsvoir\b|press release|advertorial disclaimer|"
    r"provided by [a-z0-9 .&-]+(?:\. | )?(?:press release|newsvoir|prnewswire)|"
    r"will not be responsible in any way for the content)",
    re.IGNORECASE,
)
PROMOTION_CUES = re.compile(
    r"(?:\bpromotion\b|\bpromotional\b|at exceptional value|visit your nearest|"
    r"shop now|buy now|special offer|exclusive offer|don't miss this opportunity|"
    r"soft opening|luxurious retreat|guest rooms|welcoming guests|"
    r"scheduled to open its doors|promises a tranquil escape|"
    r"we are delighted to bring)",
    re.IGNORECASE,
)
PRESS_RELEASE_URL_CUES = re.compile(r"/(?:press-release|press_release)(?:/|$)", re.IGNORECASE)
ARTICLE_METADATA_CUES = re.compile(
    r"(?:\b(?:ist|prnewswire|newsvoir)\b|\b(?:january|february|march|april|may|"
    r"june|july|august|september|october|november|december)\b)",
    re.IGNORECASE,
)
LISTING_DATE_CUES = re.compile(
    r"(?:\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2},\s+\d{4}\b|\b\d{1,2}:\d{2}\s*[ap]\.m\.)",
    re.IGNORECASE,
)
NAVIGATION_CUES = re.compile(
    r"(?:^|\b)(?:search|channels|recommended for you|skip to main content|"
    r"latest comments|post your comment|comments not available)(?:\b|$)",
    re.IGNORECASE,
)
COMMENT_SECTION_CUES = re.compile(
    r"\b(?:latest comments|post your comment|comments not available)\b",
    re.IGNORECASE,
)
TRAILING_SECTION_CUES = re.compile(
    r"(?:support our journalism|latest news \(click title to read article\)|"
    r"latest articles \(click title to read\)|most read articles \(click title to read\)|"
    r"important notice|© copyright|subscribe to our newsletter|download our app|"
    r"follow us on|read more stories)",
    re.IGNORECASE,
)
SECTION_CUES = re.compile(
    rf"(?:{COMMENT_SECTION_CUES.pattern}|{TRAILING_SECTION_CUES.pattern})",
    re.IGNORECASE,
)
TITLE_TOKEN = re.compile(r"[a-z][a-z0-9]{3,}", re.IGNORECASE)
STANDALONE_NOISE_CUES = re.compile(
    r"^(?:listen to this article|listen|read more|share this page|newsletters|"
    r"contact us|submit content|advertising)\.?$",
    re.IGNORECASE,
)
TITLE_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "against",
        "among",
        "before",
        "being",
        "between",
        "could",
        "deal",
        "first",
        "from",
        "have",
        "into",
        "latest",
        "more",
        "most",
        "news",
        "over",
        "report",
        "reports",
        "says",
        "said",
        "signs",
        "signed",
        "some",
        "than",
        "that",
        "their",
        "there",
        "these",
        "they",
        "this",
        "through",
        "under",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "would",
        "article",
        "announced",
        "announcement",
        "announces",
        "agreement",
        "equipment",
        "network",
        "networks",
    }
)
BLOCK_EDGE_CHARS = "|" + " \t\n\r\x0b\x0c"
SENTENCE_ENDINGS = re.compile(r"[.!?。！？](?=\s|$)")
NON_CONTENT_TAGS = re.compile(
    r"<(script|style|noscript|template|svg)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
HTML_TAGS = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    title: str
    text: str
    reason: str | None = None
    # A real date, not the ISO string trafilatura hands back: the column is a
    # DATE, and a malformed value should become None rather than fail a batch.
    published_at: datetime.date | None = None


def parse_published_date(value: object) -> datetime.date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_match_text(value: str) -> str:
    return normalize_text(re.sub(r"[^a-z0-9]+", " ", value.casefold()))


def _compact_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _meaningful_title_tokens(value: str) -> set[str]:
    return {
        token
        for token in TITLE_TOKEN.findall(value.casefold())
        if token not in TITLE_STOPWORDS
    }


def _normalize_extracted_block(value: str) -> str:
    value = value.replace(r"\|", " | ")
    # These edges were stripped with `^(?:\s*\|\s*)+` and `(?:\s*\|\s*)+$`, which
    # backtrack exponentially: \s* can match empty, so a whitespace-padded pipe run
    # has exponentially many splits to try before the anchor fails. A nav bar like
    # "Home | News | Sport | ..." took 39s at 18 pipes and hung the fetcher outright,
    # because extraction runs synchronously in the event loop. Stripping the same
    # character set is linear and leaves interior pipes alone, as before.
    value = value.strip(BLOCK_EDGE_CHARS)
    return normalize_text(value)


def _normalize_extracted_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    blocks: list[str] = []
    seen: set[str] = set()
    for block in re.split(r"\n\s*\n|\r?\n", value):
        normalized = _normalize_extracted_block(block)
        section_match = SECTION_CUES.search(normalized)
        if section_match:
            normalized = normalize_text(normalized[: section_match.start()])
        if not normalized:
            if section_match:
                break
            continue
        if STANDALONE_NOISE_CUES.fullmatch(normalized):
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        blocks.append(normalized)
        if section_match:
            break
    return "\n\n".join(blocks)


def _remove_leading_title(text: str, title: str) -> str:
    if not title:
        return text
    blocks = text.split("\n\n")
    if blocks and blocks[0].casefold() == title.casefold():
        return "\n\n".join(blocks[1:])
    return text


def _remove_leading_page_noise(text: str, title: str) -> str:
    blocks = [block for block in text.split("\n\n") if block]
    title_anchor = _compact_match_text(title)[:60]
    if len(blocks) < 2 or len(title_anchor) < 30:
        return text
    for index, block in enumerate(blocks[:8]):
        if _compact_match_text(block).startswith(title_anchor):
            return "\n\n".join(blocks[index:])
    return text


def _has_repeated_prefix(first: str, second: str) -> bool:
    first_match = _normalize_match_text(first)
    second_match = _normalize_match_text(second)
    prefix = second_match[:80]
    return len(prefix) >= 80 and prefix in first_match


def _remove_repeated_leading_wrapper(text: str, title: str) -> str:
    blocks = [block for block in text.split("\n\n") if block]
    if len(blocks) < 2 or not title:
        return text
    starts_with_title = _compact_match_text(blocks[0]).startswith(_compact_match_text(title))
    metadata_wrapper = len(blocks[0]) <= 500 and bool(ARTICLE_METADATA_CUES.search(blocks[0]))
    if starts_with_title and (metadata_wrapper or _has_repeated_prefix(blocks[0], blocks[1])):
        blocks.pop(0)
    return "\n\n".join(blocks)


def _source_signal_text(html_content: str | bytes) -> str:
    if isinstance(html_content, bytes):
        value = html_content.decode("utf-8", errors="replace")
    else:
        value = html_content
    value = NON_CONTENT_TAGS.sub(" ", value)
    return normalize_text(unescape(HTML_TAGS.sub(" ", value)))


def _has_title_body_overlap(title: str, text: str) -> bool:
    title_tokens = _meaningful_title_tokens(title)
    if len(title_tokens) < 2:
        return True
    text_tokens = set(TITLE_TOKEN.findall(text.casefold()))
    return bool(title_tokens & text_tokens)


def _looks_like_navigation(title: str, text: str) -> bool:
    blocks = [block for block in text.split("\n\n") if block]
    navigation_hits = sum(bool(NAVIGATION_CUES.search(block)) for block in blocks)
    sentence_count = len(SENTENCE_ENDINGS.findall(text))
    short_blocks = sum(len(block) < 80 for block in blocks)
    date_blocks = sum(bool(LISTING_DATE_CUES.search(block)) for block in blocks)
    long_blocks = sum(len(block) >= 200 for block in blocks)
    if navigation_hits >= 2 and (
        not _meaningful_title_tokens(title) or not _has_title_body_overlap(title, text)
    ):
        return True
    if len(blocks) >= 20 and long_blocks == 0:
        return True
    if len(blocks) >= 8 and date_blocks >= 3 and long_blocks <= 2:
        return True
    return (
        len(blocks) >= 6
        and short_blocks / len(blocks) >= 0.75
        and sentence_count < MIN_SENTENCE_COUNT
    )


def _classify_candidate(
    title: str,
    text: str,
    signal_text: str = "",
    url: str | None = None,
) -> ExtractionResult:
    probe = f"{title}\n{text}"
    if not text:
        probe = f"{probe}\n{signal_text}"
    if PAYWALL_CUES.search(probe) and len(text) < MAX_GATE_CUE_LENGTH:
        return ExtractionResult("paywall", title, text, "paywall-cue")
    if BLOCKED_CUES.search(probe) and len(text) < MAX_GATE_CUE_LENGTH:
        return ExtractionResult("blocked", title, text, "blocked-page-cue")
    if ERROR_PAGE_CUES.search(probe) and len(text) < MAX_GATE_CUE_LENGTH:
        return ExtractionResult("insufficient_text", title, text, "error-page-cue")
    if not text:
        return ExtractionResult("insufficient_text", title, text, "no-extracted-content")
    if len(text) < MIN_ARTICLE_CHARS:
        return ExtractionResult(
            "insufficient_text",
            title,
            text,
            f"less-than-{MIN_ARTICLE_CHARS}-characters",
        )

    if not _has_title_body_overlap(title, text):
        return ExtractionResult("insufficient_text", title, text, "title-body-mismatch")
    if _looks_like_navigation(title, text):
        return ExtractionResult("insufficient_text", title, text, "navigation-only")

    blocks = [block for block in text.split("\n\n") if len(block) >= 40]
    sentence_count = len(SENTENCE_ENDINGS.findall(text))
    if len(blocks) < MIN_ARTICLE_BLOCKS and sentence_count < MIN_SENTENCE_COUNT:
        return ExtractionResult("insufficient_text", title, text, "insufficient-article-structure")

    promotional_count = len(PROMOTIONAL_CUES.findall(text))
    if len(text) < 800 and promotional_count >= 2:
        return ExtractionResult("insufficient_text", title, text, "boilerplate-only")
    if PRESS_RELEASE_CUES.search(text) or (
        url is not None and PRESS_RELEASE_URL_CUES.search(url)
    ):
        return ExtractionResult("extracted", title, text, "press-release")
    if len(PROMOTION_CUES.findall(f"{title}\n{text}")) >= 2:
        return ExtractionResult("extracted", title, text, "promotional-content")
    return ExtractionResult("extracted", title, text)


def _extract_candidate(
    html_content: str | bytes,
    url: str | None,
    favor_recall: bool,
    max_date: str | None = None,
) -> ExtractionResult:
    try:
        extracted = trafilatura.extract(
            html_content,
            url=url,
            # Unbounded, htmldate falls back to a page's last-modified or render
            # date: measured on stored articles, 11 of 74 dates were the crawl
            # year rather than publication. Bounding the range recovered the
            # real date for 10 of those 11 and dropped the last.
            date_extraction_params={"max_date": max_date} if max_date else None,
            favor_precision=not favor_recall,
            favor_recall=favor_recall,
            include_comments=False,
            include_tables=True,
            include_images=False,
            include_links=False,
            deduplicate=True,
            output_format="json",
            with_metadata=True,
        )
    except Exception as error:
        return ExtractionResult("parse_error", "", "", type(error).__name__)

    if not extracted:
        return ExtractionResult("insufficient_text", "", "", "no-extracted-content")
    try:
        payload = json.loads(extracted)
    except (TypeError, ValueError):
        return ExtractionResult("parse_error", "", "", "invalid-trafilatura-json")
    if not isinstance(payload, dict):
        return ExtractionResult("parse_error", "", "", "unexpected-trafilatura-output")

    title = normalize_text(payload.get("title") or "")
    text = _normalize_extracted_text(payload.get("text") or payload.get("raw_text") or "")
    text = _remove_leading_page_noise(text, title)
    text = _remove_leading_title(text, title)
    text = _remove_repeated_leading_wrapper(text, title)
    result = _classify_candidate(title, text, _source_signal_text(html_content), url)
    # Attached here rather than threaded through _classify_candidate's eight
    # return paths, which care about text quality and not about metadata.
    return replace(result, published_at=parse_published_date(payload.get("date")))


def extract_article_variant(
    html_content: str | bytes,
    url: str | None = None,
    *,
    favor_recall: bool = False,
    max_date: str | None = None,
) -> ExtractionResult:
    return _extract_candidate(html_content, url, favor_recall=favor_recall, max_date=max_date)


def _result_priority(result: ExtractionResult) -> tuple[int, int]:
    status_priority = {
        "extracted": 4,
        "paywall": 3,
        "blocked": 3,
        "insufficient_text": 2,
        "parse_error": 1,
    }
    return status_priority.get(result.status, 0), len(result.text)


def extract_article(
    html_content: str | bytes,
    url: str | None = None,
    *,
    favor_recall: bool = False,
    max_date: str | None = None,
) -> ExtractionResult:
    if favor_recall:
        return _extract_candidate(html_content, url, favor_recall=True, max_date=max_date)

    precision_result = _extract_candidate(
        html_content, url, favor_recall=False, max_date=max_date
    )
    if precision_result.status in {"extracted", "paywall", "blocked"}:
        return precision_result

    recall_result = _extract_candidate(
        html_content, url, favor_recall=True, max_date=max_date
    )
    if recall_result.status == "extracted":
        return recall_result
    return max((precision_result, recall_result), key=_result_priority)
