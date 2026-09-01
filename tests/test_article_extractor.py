import importlib.util
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
