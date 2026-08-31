import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "pipeline" / "05_build_annotation_units.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_annotation_units", SCRIPT_PATH)
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
                "event-1",
                "190",
                "19",
                -4.0,
                "A",
                "IN",
                "B",
                "IN",
                "https://example.test/article",
            ),
            (
                20240101,
                "2024-01-01",
                "event-2",
                "190",
                "19",
                -4.0,
                "A",
                "IN",
                "C",
                "IN",
                "https://example.test/article",
            ),
            (
                20240102,
                "2024-01-02",
                "event-3",
                "141",
                "14",
                1.0,
                "D",
                "IN",
                "",
                "",
                "https://example.test/article",
            ),
            (
                20240103,
                "2024-01-03",
                "event-4",
                "190",
                "19",
                -4.0,
                "E",
                "IN",
                "F",
                "IN",
                "https://example.test/other",
            ),
        ],
    )
    connection.execute(f"COPY events TO '{path.as_posix()}' (FORMAT PARQUET)")
    connection.close()


def test_build_units_groups_by_source_and_event_code(tmp_path):
    builder = load_builder()
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "annotation_units.json"
    manifest_path = tmp_path / "annotation_manifest.json"
    write_fixture(input_path)

    manifest = builder.build_units(input_path, output_path, manifest_path)
    payload = json.loads(output_path.read_text())
    grouped = next(unit for unit in payload["units"] if unit["event_code"] == "190")

    assert manifest["unit_count"] == 3
    assert manifest["member_event_count"] == 4
    assert manifest["multi_member_units"] == 1
    assert grouped["event_count"] == 2
    assert [member["id"] for member in grouped["members"]] == ["event-1", "event-2"]
    assert len(grouped["actor_variants"]) == 2
    assert json.loads(manifest_path.read_text()) == manifest


def test_cli_accepts_custom_paths(tmp_path):
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "cli" / "annotation_units.json"
    manifest_path = tmp_path / "cli" / "annotation_manifest.json"
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
    assert json.loads(result.stdout)["unit_count"] == 3
