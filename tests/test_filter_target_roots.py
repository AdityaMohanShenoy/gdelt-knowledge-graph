import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "pipeline" / "02_filter_target_roots.py"


def load_filter():
    spec = importlib.util.spec_from_file_location("filter_target_roots", SCRIPT_PATH)
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
            (20240101, "2024-01-01", "root-14", "141", "14", "4", 1.0, "A", "IN", "", "", "IN", "https://example.test/14"),
            (20240102, "2024-01-02", "root-17", "171", "17", "4", -2.0, "B", "IN", "", "", "IN", "https://example.test/17"),
            (20240103, "2024-01-03", "root-18", "181", "18", "4", -3.0, "C", "IN", "", "", "IN", "https://example.test/18"),
            (20240104, "2024-01-04", "root-19", "191", "19", "4", -4.0, "D", "IN", "", "", "IN", "https://example.test/19"),
            (20240105, "2024-01-05", "root-20", "201", "20", "4", -5.0, "E", "IN", "", "", "IN", "https://example.test/20"),
        ],
    )
    connection.execute(f"COPY events TO '{path.as_posix()}' (FORMAT PARQUET)")
    connection.close()


def test_filter_keeps_only_target_roots_and_preserves_schema(tmp_path):
    target_filter = load_filter()
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "working" / "target_events.parquet"
    manifest_path = tmp_path / "working" / "target_manifest.json"
    write_fixture(input_path)

    manifest = target_filter.build_dataset(input_path, output_path, manifest_path)

    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        SELECT GlobalEventID, EventRootCode
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

    assert rows == [("root-14", "14"), ("root-18", "18"), ("root-19", "19"), ("root-20", "20")]
    assert manifest["input_rows"] == 5
    assert manifest["output_rows"] == 4
    assert manifest["output_root_counts"] == {"14": 1, "18": 1, "19": 1, "20": 1}
    assert manifest["columns_preserved"] is True
    assert manifest["columns"] == columns
    assert json.loads(manifest_path.read_text()) == manifest


def test_cli_accepts_custom_paths(tmp_path):
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "cli" / "target_events.parquet"
    manifest_path = tmp_path / "cli" / "target_manifest.json"
    write_fixture(input_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
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
    assert json.loads(result.stdout)["output_rows"] == 4
