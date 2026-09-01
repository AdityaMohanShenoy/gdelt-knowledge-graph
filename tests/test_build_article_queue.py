import importlib.util
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))
SCRIPT_PATH = ROOT / "pipeline" / "06_build_article_queue.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_article_queue", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fixture(path: Path) -> None:
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE events (SOURCEURL VARCHAR)
        """
    )
    connection.executemany(
        "INSERT INTO events VALUES (?)",
        [
            ("https://Example.test/article#top",),
            ("https://example.test/article",),
            ("http://example.test:80/article",),
            ("https://example.test/other",),
        ],
    )
    connection.execute(f"COPY events TO '{path.as_posix()}' (FORMAT PARQUET)")
    connection.close()


def test_build_url_set_normalizes_and_deduplicates_source_urls(tmp_path):
    builder = load_builder()
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "article_urls.parquet"
    manifest_path = tmp_path / "article_urls_manifest.json"
    write_fixture(input_path)

    manifest = builder.build_url_set(input_path, output_path, manifest_path)

    rows = duckdb.sql(
        f"SELECT * FROM read_parquet('{output_path.as_posix()}') ORDER BY url_key"
    ).fetchall()
    assert manifest["source_url_rows"] == 4
    assert manifest["unique_url_keys"] == 3
    assert manifest["normalization_collisions"] == 1
    assert [row[0] for row in rows] == [
        "http://example.test/article",
        "https://example.test/article",
        "https://example.test/other",
    ]


def test_normalize_url_rejects_invalid_ports_and_formats_ipv6_hosts():
    builder = load_builder()

    assert builder.normalize_url("https://example.test:invalid/article") == ""
    assert builder.normalize_url("https://[2001:DB8::1]/article") == "https://[2001:db8::1]/article"
