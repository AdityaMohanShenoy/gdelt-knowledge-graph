import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "pipeline" / "01_build_india_universe.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_india_universe", SCRIPT_PATH)
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
            QuadClass VARCHAR,
            GoldsteinScale DOUBLE,
            Actor1Name VARCHAR,
            Actor1CountryCode VARCHAR,
            Actor2Name VARCHAR,
            Actor2CountryCode VARCHAR,
            ActionGeo_CountryCode VARCHAR,
            SOURCEURL VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                20240101,
                "2024-01-01",
                "event-in-1",
                "141",
                "14",
                "4",
                1.0,
                "ACTOR A",
                "IN",
                "",
                "",
                "IN",
                "https://example.test/in-1",
            ),
            (
                20240102,
                "2024-01-02",
                "event-us-1",
                "141",
                "14",
                "4",
                1.0,
                "ACTOR B",
                "US",
                "",
                "",
                "US",
                "https://example.test/us-1",
            ),
            (
                20240103,
                "2024-01-03",
                "event-in-2",
                "171",
                "17",
                "4",
                -2.0,
                "ACTOR C",
                "IN",
                "",
                "",
                "IN",
                "https://example.test/in-2",
            ),
        ],
    )
    connection.execute(f"COPY events TO '{path.as_posix()}' (FORMAT PARQUET)")
    connection.close()


def test_build_filters_action_location_and_preserves_schema(tmp_path):
    builder = load_builder()
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "working" / "events.parquet"
    manifest_path = tmp_path / "working" / "manifest.json"
    write_fixture(input_path)

    manifest = builder.build_dataset(input_path, output_path, manifest_path)

    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        SELECT GlobalEventID, ActionGeo_CountryCode
        FROM read_parquet('{output_path.as_posix()}')
        ORDER BY GlobalEventID
        """
    ).fetchall()
    columns = [
        row[0]
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{input_path.as_posix()}')"
        ).fetchall()
    ]
    connection.close()

    assert rows == [("event-in-1", "IN"), ("event-in-2", "IN")]
    assert manifest["input_rows"] == 3
    assert manifest["output_rows"] == 2
    assert manifest["columns_preserved"] is True
    assert manifest["columns"] == columns
    assert json.loads(manifest_path.read_text()) == manifest


def test_build_is_rerunnable(tmp_path):
    builder = load_builder()
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "events.parquet.out"
    manifest_path = tmp_path / "manifest.json"
    write_fixture(input_path)

    first = builder.build_dataset(input_path, output_path, manifest_path)
    second = builder.build_dataset(input_path, output_path, manifest_path)

    for key in ("input_rows", "output_rows", "columns", "columns_preserved"):
        assert first[key] == second[key]
    assert output_path.exists()
    assert manifest_path.exists()


def test_cli_accepts_custom_paths(tmp_path):
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "cli" / "events.parquet"
    manifest_path = tmp_path / "cli" / "manifest.json"
    write_fixture(input_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input-glob",
            str(input_path),
            "--output",
            str(output_path),
            "--manifest",
            str(manifest_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert output_path.exists()
    assert json.loads(result.stdout)["output_rows"] == 2
