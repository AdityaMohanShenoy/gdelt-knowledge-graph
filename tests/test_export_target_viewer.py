import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "pipeline" / "03_export_target_viewer.py"


def load_exporter():
    spec = importlib.util.spec_from_file_location("export_target_viewer", SCRIPT_PATH)
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
                20240102,
                "2024-01-02",
                "event-2",
                "190",
                "19",
                -4.0,
                "Group B",
                "IN",
                "Authority",
                "IN",
                "https://example.test/2",
            ),
            (
                20240101,
                "2024-01-01",
                "event-1",
                "141",
                "14",
                1.0,
                "Group A",
                "IN",
                "",
                "",
                "https://example.test/1",
            ),
            (
                20240103,
                "2024-01-03",
                "event-3",
                "171",
                "17",
                -2.0,
                "Context",
                "IN",
                "",
                "",
                "https://example.test/3",
            ),
        ],
    )
    connection.execute(f"COPY events TO '{path.as_posix()}' (FORMAT PARQUET)")
    connection.close()


def test_export_writes_sorted_slim_json(tmp_path):
    exporter = load_exporter()
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "viewer" / "target_events.json"
    write_fixture(input_path)

    summary = exporter.export_dataset(input_path, output_path)
    payload = json.loads(output_path.read_text())

    assert summary["count"] == 2
    assert payload["count"] == 2
    assert [event["id"] for event in payload["events"]] == ["event-1", "event-2"]
    assert [event["root"] for event in payload["events"]] == ["14", "19"]
    assert set(payload["events"][0]) == {
        "day",
        "datetime",
        "id",
        "event_code",
        "root",
        "goldstein",
        "actor1",
        "actor1_country",
        "actor2",
        "actor2_country",
        "url",
    }


def test_cli_accepts_custom_paths(tmp_path):
    input_path = tmp_path / "events.parquet"
    output_path = tmp_path / "cli" / "target_events.json"
    write_fixture(input_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert output_path.exists()
    assert json.loads(result.stdout)["count"] == 2
