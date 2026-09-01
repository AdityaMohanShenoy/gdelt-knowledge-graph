import re
from dataclasses import dataclass
from html.parser import HTMLParser

NOISE_TAGS = frozenset(
    {
        "aside",
        "button",
        "footer",
        "form",
        "iframe",
        "nav",
        "noscript",
        "script",
        "style",
        "svg",
        "template",
    }
)
BLOCK_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "pre"})
VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
NOISE_WORDS = re.compile(
    r"(?:^|[-_\s])(ad|ads|advert|advertisement|banner|cookie|consent|footer|login|modal|newsletter|popup|promo|recommend|related|share|social|sponsor|subscribe)(?:$|[-_\s])",
    re.IGNORECASE,
)
PAYWALL_CUES = re.compile(
    r"(?:subscribe to continue|subscribe to read|sign in to read|premium content|"
    r"for subscribers|become a subscriber|membership required|unlock this article|"
    r"this article is for subscribers)",
    re.IGNORECASE,
)
BLOCKED_CUES = re.compile(
    r"(?:access denied|verify you are human|checking your browser|enable javascript|"
    r"bot detection|unusual traffic|temporarily unavailable)",
    re.IGNORECASE,
)
PROMOTIONAL_CUES = re.compile(
    r"(?:subscribe to our newsletter|download our app|follow us on|advertisement|"
    r"sponsored content|read more stories)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    title: str
    text: str
    reason: str | None = None


@dataclass
class _TextBlock:
    tag: str
    context_score: int
    parts: list[str]


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._context_score = 0
        self._context_stack: list[int] = []
        self._block_stack: list[_TextBlock] = []
        self.blocks: list[_TextBlock] = []
        self.title_parts: list[str] = []
        self.heading_parts: list[str] = []
        self.body_parts: list[str] = []
        self._title_depth = 0
        self._heading_depth = 0

    @staticmethod
    def _attrs_text(attrs: list[tuple[str, str | None]]) -> str:
        return " ".join(value or "" for name, value in attrs if name in {"class", "id", "role"})

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_text = self._attrs_text(attrs)
        if self._skip_depth or tag in NOISE_TAGS or NOISE_WORDS.search(attrs_text):
            self._skip_depth += 1
            return

        context_increment = 1 if tag in {"article", "main"} else 0
        if re.search(r"(?:article|content|entry|post|story|text|body)", attrs_text, re.IGNORECASE):
            context_increment += 1
        if tag not in VOID_TAGS:
            self._context_stack.append(context_increment)
            self._context_score += context_increment

        if tag == "title":
            self._title_depth += 1
        if tag == "h1":
            self._heading_depth += 1
        if tag in BLOCK_TAGS:
            self._block_stack.append(_TextBlock(tag, self._context_score, []))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            return

        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag == "h1" and self._heading_depth:
            self._heading_depth -= 1
        if tag in BLOCK_TAGS and self._block_stack:
            block = self._block_stack.pop()
            text = normalize_text(" ".join(block.parts))
            if text:
                self.blocks.append(block)
        if self._context_stack:
            self._context_score -= self._context_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = normalize_text(data)
        if not value:
            return
        self.body_parts.append(value)
        if self._title_depth:
            self.title_parts.append(value)
        if self._heading_depth:
            self.heading_parts.append(value)
        if self._block_stack:
            self._block_stack[-1].parts.append(value)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _deduplicate_blocks(blocks: list[_TextBlock]) -> list[str]:
    contextual_blocks = [block for block in blocks if block.context_score > 0]
    candidates = contextual_blocks or blocks
    seen: set[str] = set()
    selected: list[str] = []
    for block in candidates:
        text = normalize_text(" ".join(block.parts))
        if len(text) < 25 or PROMOTIONAL_CUES.search(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(text)
    return selected


def extract_article(html_text: str) -> ExtractionResult:
    parser = _ArticleParser()
    try:
        parser.feed(html_text)
        parser.close()
    except (ValueError, RecursionError) as error:
        return ExtractionResult("parse_error", "", "", type(error).__name__)

    title = normalize_text(" ".join(parser.heading_parts or parser.title_parts))
    blocks = _deduplicate_blocks(parser.blocks)
    text = "\n\n".join(blocks)
    if not text:
        text = normalize_text(" ".join(parser.body_parts))

    if PAYWALL_CUES.search(text) and len(text) < 1200:
        return ExtractionResult("paywall", title, text, "paywall-cue")
    if BLOCKED_CUES.search(text) and len(text) < 1200:
        return ExtractionResult("blocked", title, text, "blocked-page-cue")
    if len(text) < 200:
        return ExtractionResult("insufficient_text", title, text, "less-than-200-characters")
    return ExtractionResult("extracted", title, text)
