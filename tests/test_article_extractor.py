import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "pipeline" / "article_extractor.py"


def load_extractor():
    spec = importlib.util.spec_from_file_location("article_extractor", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_article_keeps_article_text_and_drops_page_noise():
    extractor = load_extractor()
    html = """
    <html>
      <head><title>City protest report</title></head>
      <body>
        <nav>Home Politics Subscribe</nav>
        <main class="article-content">
          <h1>City protest report</h1>
          <p>Workers gathered in the city on Monday to protest the new policy.</p>
          <p>Organizers said the demonstration would continue until officials opened
          negotiations.</p>
          <p>Police reported that the crowd remained peaceful through the evening.</p>
          <p>Residents described the protest as the largest public gathering in the district
          this year, while local officials promised to publish a response after the meeting.
          The report also recorded statements from several independent observers who attended
          the event and confirmed the sequence of negotiations.</p>
        </main>
        <aside class="related">Read more stories from our partners.</aside>
        <footer>Subscribe to our newsletter. Follow us on social media.</footer>
      </body>
    </html>
    """

    result = extractor.extract_article(html)

    assert result.status == "extracted"
    assert result.title == "City protest report"
    assert "Workers gathered" in result.text
    assert "Read more stories" not in result.text
    assert "Subscribe to our newsletter" not in result.text


def test_extract_article_classifies_paywall_and_blocked_pages():
    extractor = load_extractor()

    paywall = extractor.extract_article(
        "<html><body><main><h1>Premium report</h1>"
        "<p>Subscribe to continue reading this article.</p></main></body></html>"
    )
    blocked = extractor.extract_article(
        "<html><body><p>Checking your browser before accessing this page.</p></body></html>"
    )

    assert paywall.status == "paywall"
    assert blocked.status == "blocked"


def test_extract_article_classifies_paywall_when_body_extraction_is_empty():
    extractor = load_extractor()

    result = extractor.extract_article(
        "<html><head><title>Subscriber access</title></head><body>"
        "<div class='paywall'>Subscribe to continue reading this article.</div>"
        "</body></html>"
    )

    assert result.status == "paywall"
    assert result.reason == "paywall-cue"


def test_extract_article_marks_short_pages_as_insufficient():
    extractor = load_extractor()

    result = extractor.extract_article("<html><body><p>Short page.</p></body></html>")

    assert result.status == "insufficient_text"


def test_extract_article_rejects_not_found_pages():
    extractor = load_extractor()

    result = extractor.extract_article(
        "<html><head><title>404 - Not Found</title></head>"
        "<body><main><h1>Not Found!</h1><p>The requested page could not be found.</p>"
        "</main></body></html>",
        url="https://example.test/missing",
    )

    assert result.status == "insufficient_text"
    assert result.reason == "error-page-cue"


def test_extract_article_does_not_use_unrelated_source_signals_for_nonempty_text():
    extractor = load_extractor()

    result = extractor.extract_article(
        "<html><body><nav>404 page navigation</nav><article>"
        "<p>This is a short but legitimate report with a few sentences that should remain"
        " classified as insufficient because the article is not long enough.</p>"
        "</article></body></html>"
    )

    assert result.status == "insufficient_text"
    assert result.reason == "less-than-400-characters"


def test_extract_article_accepts_bytes_and_uses_recall_for_sparse_pages():
    extractor = load_extractor()
    html = b"""
    <html><head><title>District report</title></head><body>
      <div class="shell"><p>Navigation Home Search Login</p></div>
      <div class="story"><p>Officials met residents after the demonstration on Tuesday.
      The meeting produced a written commitment to review the policy and publish a timeline.
      Organizers said the process would be monitored publicly through the next quarter.</p>
      <p>The district office confirmed that a follow-up meeting would occur next week.</p>
      <p>Both sides agreed to release meeting notes and invite additional community groups.
      The next session will review the published timetable and any outstanding requests.</p></div>
    </body></html>
    """

    result = extractor.extract_article(html, url="https://example.test/report")

    assert result.status == "extracted"
    assert result.title == "District report"
    assert "Officials met residents" in result.text
    assert "Navigation Home" not in result.text


def test_extract_article_cleans_syndication_wrappers_and_flags_press_release(monkeypatch):
    extractor = load_extractor()
    lead = (
        "The organization announced a new programme to support communities across the region."
    )
    body = (
        f"{lead} Officials said the programme would fund local services and publish regular "
        "results. "
        "The organizers described the initiative as a long-term commitment to public welfare. "
        "The above press release has been provided by PRNewswire. "
        "The announcement included details about the schedule, participating groups, and "
        "expected outcomes."
    )
    payload = {
        "title": "Community programme announced across the region",
        "text": (
            "| |\n\n"
            "| Community programme announced across the region \\| November 27, 2024 "
            f"PRNewswire {lead} |\n\n"
            f"| {body} |\n\n"
            "| LATEST COMMENTS () \\| POST YOUR COMMENT |\n\n"
            "| Comments Not Available |"
        ),
    }
    monkeypatch.setattr(
        extractor.trafilatura,
        "extract",
        lambda *args, **kwargs: json.dumps(payload),
    )

    result = extractor.extract_article("<html><body>article</body></html>")

    assert result.status == "extracted"
    assert result.reason == "press-release"
    assert not result.text.startswith("|")
    assert "LATEST COMMENTS" not in result.text
    assert result.text.count(lead) == 1


def test_extract_article_rejects_current_navigation_for_stale_article_title(monkeypatch):
    extractor = load_extractor()
    payload = {
        "title": "Vodafone Idea signs network equipment deal with Nokia and Ericsson",
        "text": (
            "Search\n\nChannels\n\nRecommended for you...\n\n27 Aug 2026\n\n"
            "Anthropic signs a compute capacity agreement with Nscale - report\n\n"
            "Energy and Sustainability\n\nWater efficiency and renewable power\n\n"
            "Media\n\nWhere workloads live and why\n\n"
            "Investment and Markets\n\nFinancing the data center build-out\n\n"
            "Management and Operations\n\nDay-to-day operations, workforce and skills\n\n"
            "Cloud and Hybrid\n\nWhere workloads live and why they matter\n\n"
            "Construction\n\nSite selection, building, and expansion"
        ),
    }
    monkeypatch.setattr(
        extractor.trafilatura,
        "extract",
        lambda *args, **kwargs: json.dumps(payload),
    )

    result = extractor.extract_article("<html><body>current page</body></html>")

    assert result.status == "insufficient_text"
    assert result.reason == "title-body-mismatch"


def test_extract_article_rejects_navigation_only_candidate_without_title(monkeypatch):
    extractor = load_extractor()
    navigation_block = "Navigation menu with current site links and section options"
    payload = {
        "title": "",
        "text": "\n\n".join(
            [
                "Search",
                "Channels",
                "Recommended for you",
                "Media",
                "Home",
                "Login",
                "Topics",
                "Latest News",
                "More site navigation options",
                "Related stories and links",
                "Popular sections and topics",
                "Newsletter signup and updates",
                "Explore more site content",
                "User account and access settings",
                "Read the latest stories and updates",
                "Browse the full list of site categories",
                "Account preferences and notification settings",
                "Discover popular articles and features",
                navigation_block,
                navigation_block.replace("current", "available"),
            ]
        ),
    }
    monkeypatch.setattr(
        extractor.trafilatura,
        "extract",
        lambda *args, **kwargs: json.dumps(payload),
    )

    result = extractor.extract_article("<html><body>navigation</body></html>")

    assert result.status == "insufficient_text"
    assert result.reason == "navigation-only"


def test_extract_article_rejects_dated_recommendation_listing(monkeypatch):
    extractor = load_extractor()
    payload = {
        "title": "BNN Bloomberg - Canada Business News and Market Updates",
        "text": "\n\n".join(
            f"Story {index} about current markets and business developments "
            "August 31, 2026 at 9:40p.m. EDT"
            for index in range(10)
        ),
    }
    monkeypatch.setattr(
        extractor.trafilatura,
        "extract",
        lambda *args, **kwargs: json.dumps(payload),
    )

    result = extractor.extract_article("<html><body>listing</body></html>")

    assert result.status == "insufficient_text"
    assert result.reason == "navigation-only"


def test_extract_article_flags_promotional_hotel_copy(monkeypatch):
    extractor = load_extractor()
    payload = {
        "title": "Hotel returns to India with a soft opening",
        "text": (
            "Videos\n\nSHARE THIS PAGE\n\nNEWSLETTERS\n\nCONTACT US\n\n"
            "Listen to This Article\n\n"
            "Hotel returns to India with a soft opening\n\n"
            "The hotel returns to India with a soft opening in December 2024. "
            "This luxurious retreat offers 80 guest rooms, wellness facilities, and dining "
            "options. "
            "The company said it looks forward to welcoming guests at the new property. "
            "The hotel described the destination as a tranquil escape for visitors. "
            "Marketing material highlights its location, amenities, meeting spaces, and views "
            "of the surrounding hills."
        ),
    }
    monkeypatch.setattr(
        extractor.trafilatura,
        "extract",
        lambda *args, **kwargs: json.dumps(payload),
    )

    result = extractor.extract_article("<html><body>promotion</body></html>")

    assert result.status == "extracted"
    assert result.reason == "promotional-content"
    assert "Videos" not in result.text
    assert "SHARE THIS PAGE" not in result.text
    assert "Listen to This Article" not in result.text


def test_normalize_block_stays_linear_on_pipe_heavy_tables():
    """trafilatura runs with include_tables=True, so a wide table arrives as one
    pipe-delimited block. The old `(?:\\s*\\|\\s*)+$` backtracked exponentially on
    these and hung the whole fetcher, since extraction runs in the event loop."""
    import time

    extractor = load_extractor()
    # No leading pipe, so the leading strip cannot consume the run first.
    row = "Breadcrumb" + " | " * 40 + "tail"

    start = time.perf_counter()
    result = extractor._normalize_extracted_block(row)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"pipe-heavy block took {elapsed:.1f}s — backtracking regression"
    assert result.startswith("Breadcrumb") and result.endswith("tail")


def test_normalize_block_still_trims_pipes_and_whitespace():
    extractor = load_extractor()

    assert extractor._normalize_extracted_block("  |  Home | News  |  ") == "Home | News"
    assert extractor._normalize_extracted_block("| | |") == ""
    assert extractor._normalize_extracted_block("  plain text  ") == "plain text"
    assert extractor._normalize_extracted_block("a  b\n c") == "a b c"
