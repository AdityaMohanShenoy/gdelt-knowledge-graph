import importlib.util
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "pipeline" / "04_validate_target_urls.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_target_urls", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fixture(path: Path) -> None:
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE events (
            day INTEGER,
            datetime VARCHAR,
            GlobalEventID VARCHAR,
            EventCode VARCHAR,
            EventRootCode VARCHAR,
            GoldsteinScale DOUBLE,
            Actor1Name VARCHAR,
            Actor1CountryCode VARCHAR,
            Actor2Name VARCHAR,
            Actor2CountryCode VARCHAR,
            SOURCEURL VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                20240101,
                "2024-01-01",
                "live",
                "141",
                "14",
                1.0,
                "Actor",
                "IN",
                "",
                "",
                "https://example.test/live",
            ),
            (
                20240102,
                "2024-01-02",
                "dead",
                "191",
                "19",
                -4.0,
                "Actor",
                "IN",
                "",
                "",
                "https://example.test/dead",
            ),
            (
                20240103,
                "2024-01-03",
                "missing",
                "181",
                "18",
                -3.0,
                "Actor",
                "IN",
                "",
                "",
                "",
            ),
        ],
    )
    connection.execute(f"COPY events TO '{path.as_posix()}' (FORMAT PARQUET)")
    connection.close()


def test_status_policy_keeps_accessible_and_unverified_urls():
    validator = load_validator()

    assert validator.status_result(200, "http-200")["alive"] is True
    assert validator.status_result(403, "http-403")["alive"] is True
    assert validator.status_result(404, "http-404")["alive"] is False
    assert validator.status_result(None, "TimeoutError")["alive"] is False


def test_filter_dataset_drops_dead_and_missing_source_rows(tmp_path):
    validator = load_validator()
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "validated.parquet"
    write_fixture(input_path)
    cache = {
        "https://example.test/live": validator.status_result(200, "http-200"),
        "https://example.test/dead": validator.status_result(404, "http-404"),
    }

    counts = validator.filter_dataset(input_path, output_path, cache)
    connection = duckdb.connect()
    rows = connection.execute(
        f"SELECT GlobalEventID FROM read_parquet('{output_path.as_posix()}')"
    ).fetchall()
    connection.close()

    assert counts == {"input_rows": 3, "output_rows": 1}
    assert rows == [("live",)]


def test_cache_loader_normalizes_legacy_boolean_entries(tmp_path):
    validator = load_validator()
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"https://example.test/old": True}))

    cache = validator.load_cache(cache_path)

    assert cache["https://example.test/old"]["alive"] is True
