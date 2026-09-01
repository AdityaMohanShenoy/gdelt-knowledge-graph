import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Any

import trafilatura

MIN_ARTICLE_CHARS = 400
MIN_ARTICLE_BLOCKS = 2
MIN_SENTENCE_COUNT = 3
MAX_GATE_CUE_LENGTH = 1200
EXTRACTOR_VERSION = f"trafilatura-{trafilatura.__version__}-precision.v1"

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


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_extracted_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    blocks: list[str] = []
    seen: set[str] = set()
    for block in re.split(r"\n\s*\n|\r?\n", value):
        normalized = normalize_text(block)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        blocks.append(normalized)
    return "\n\n".join(blocks)


def _remove_leading_title(text: str, title: str) -> str:
    if not title:
        return text
    blocks = text.split("\n\n")
    if blocks and blocks[0].casefold() == title.casefold():
        return "\n\n".join(blocks[1:])
    return text


def _source_signal_text(html_content: str | bytes) -> str:
    if isinstance(html_content, bytes):
        value = html_content.decode("utf-8", errors="replace")
    else:
        value = html_content
    value = NON_CONTENT_TAGS.sub(" ", value)
    return normalize_text(unescape(HTML_TAGS.sub(" ", value)))


def _classify_candidate(title: str, text: str, signal_text: str = "") -> ExtractionResult:
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

    blocks = [block for block in text.split("\n\n") if len(block) >= 40]
    sentence_count = len(SENTENCE_ENDINGS.findall(text))
    if len(blocks) < MIN_ARTICLE_BLOCKS and sentence_count < MIN_SENTENCE_COUNT:
        return ExtractionResult("insufficient_text", title, text, "insufficient-article-structure")

    promotional_count = len(PROMOTIONAL_CUES.findall(text))
    if len(text) < 800 and promotional_count >= 2:
        return ExtractionResult("insufficient_text", title, text, "boilerplate-only")
    return ExtractionResult("extracted", title, text)


def _extract_candidate(
    html_content: str | bytes,
    url: str | None,
    favor_recall: bool,
) -> ExtractionResult:
    try:
        extracted = trafilatura.extract(
            html_content,
            url=url,
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
    text = _remove_leading_title(text, title)
    return _classify_candidate(title, text, _source_signal_text(html_content))


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
) -> ExtractionResult:
    if favor_recall:
        return _extract_candidate(html_content, url, favor_recall=True)

    precision_result = _extract_candidate(html_content, url, favor_recall=False)
    if precision_result.status in {"extracted", "paywall", "blocked"}:
        return precision_result

    recall_result = _extract_candidate(html_content, url, favor_recall=True)
    if recall_result.status == "extracted":
        return recall_result
    return max((precision_result, recall_result), key=_result_priority)
