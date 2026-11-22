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
