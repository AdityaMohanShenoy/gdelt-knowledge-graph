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
