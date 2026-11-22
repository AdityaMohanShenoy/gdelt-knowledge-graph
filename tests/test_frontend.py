import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "frontend" / "viewer.html"


def read_html() -> str:
    return HTML_PATH.read_text()


def inline_script(source: str) -> str:
    match = re.search(r"<script>(.*?)</script>", source, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_frontend_exposes_both_view_modes_and_data_fallback():
    source = read_html()

    assert 'data-mode="cards"' in source
    assert 'data-mode="list"' in source
    assert 'id="root-filter"' in source
    assert 'id="search"' in source
    assert 'id="file-input"' in source
    assert 'const DATA_URL = "../data/working/india-2024/annotation_units.json";' in source
    assert "Annotation JSON not found." in source
    assert "EVENT ID /" in source
    assert "/api/articles/by-url?url=" in source
    assert "/api/articles/fetch" in source
    assert 'method: "POST"' in source
    assert "Fetch article text" in source
    assert "Queued" in source
    assert "memberCount" not in source


def test_inline_javascript_parses():
    result = subprocess.run(
        ["node", "--check"],
        input=inline_script(read_html()),
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stderr == ""


DEMO_PATH = ROOT / "frontend" / "demo.html"


def test_demo_tells_the_story_with_measured_figures():
    source = DEMO_PATH.read_text()
    for section in ("hero", "problem", "how", "graph", "trust", "ask"):
        assert f'id="{section}"' in source
    assert 'fetch("/api/explain/stats' in source
    for figure in ("3.8", "4.0", "20,129", "69 / 69", "1.18", "0.07"):
        assert figure in source, figure


def test_demo_query_handles_every_answer_and_works_offline():
    source = DEMO_PATH.read_text()
    assert "/static/demo-featured.json" in source
    assert "status === 'clarify'" in source and "status === 'no_match'" in source
    assert "implied=true" in source
    assert '<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"' in source
    assert "saved answer" in source
    assert 'e.key === "/"' in source and '"123456".includes(e.key)' in source


def test_demo_review_fixes():
    source = DEMO_PATH.read_text()
    # sources named for every fixed figure
    assert "branching.md" in source and "paper/iccids2027.tex" in source
    # the GDELT baseline compares candidates, not confirmed causal pairs
    assert "Real cause-and-effect pairs" not in source
    # implied links: the default view's hidden count is shown, and the claim stays honest
    assert "hidden_implied" in source
    assert "hidden until a person checks them" not in source
    # a 200 with {"error": ...} falls back like a failed fetch; stale answers are dropped
    assert "if (d.error) throw" in source and "reqId" in source
    # only http(s) source links are rendered as links
    assert 'p === "https:" || p === "http:"' in source and "webUrl(e.source_urls[0])" in source


def test_demo_survives_a_stalled_network():
    import json
    source = DEMO_PATH.read_text()
    # a hung request gives up and falls back instead of "Searching…" forever
    assert "AbortSignal.timeout(" in source
    # chips are in the markup, so they show even if the saved answers never load
    featured = json.loads((ROOT / "frontend" / "demo-featured.json").read_text())["questions"]
    for f in featured:
        assert f'data-q="{f["q"]}" data-dir="{f["direction"]}"' in source, f["q"]


def test_demo_network_panel_really_hides():
    # `hidden` is an HTML property; on an <svg> assigning it is a no-op, so the panel
    # kept showing the previous answer's network. Use the attribute plus a CSS rule.
    source = DEMO_PATH.read_text()
    assert "net.hidden =" not in source
    assert "#net[hidden] { display: none; }" in source


def test_demo_browse_every_protest_and_follow_any_event():
    source = DEMO_PATH.read_text()
    # browse: the full topic list for the current direction and view, filterable
    assert "/api/explain/topics?direction=" in source
    assert 'id="browse"' in source and 'id="browse-filter"' in source
    # follow: every event card asks about that exact event
    assert 'data-node="${esc(n.id)}"' in source and 'qs.set("node"' in source
    # an event with nothing recorded before/after it offers the other direction
    assert "See what it led to" in source and "See what caused it" in source
