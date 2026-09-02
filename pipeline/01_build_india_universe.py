import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_GLOB = ROOT / "out_parquet" / "events" / "year=2024" / "**" / "*.parquet"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "working" / "india-2024" / "events.parquet"
DEFAULT_MANIFEST_PATH = ROOT / "data" / "working" / "india-2024" / "manifest.json"
FILTER_COUNTRY_CODE = "IN"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_relation(input_glob: str | Path) -> str:
    return f"read_parquet({sql_string(Path(input_glob).as_posix())}, hive_partitioning=true)"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def summarize_relation(connection: duckdb.DuckDBPyConnection, relation: str) -> dict:
    summary = connection.execute(
        f"SELECT COUNT(*)::BIGINT, MIN(day), MAX(day) FROM {relation}"
    ).fetchone()
    if summary is None:
        raise RuntimeError("Unable to summarize Parquet relation")
    columns = [
        row[0]
        for row in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    ]
    return {
        "rows": summary[0],
        "day_min": summary[1],
        "day_max": summary[2],
        "columns": columns,
    }


def build_dataset(
    input_glob: str | Path,
    output_path: Path,
    manifest_path: Path,
) -> dict:
    connection = duckdb.connect()
    input_relation = parquet_relation(input_glob)
    output_path = output_path.resolve()
    manifest_path = manifest_path.resolve()

    try:
        input_summary = summarize_relation(connection, input_relation)
        output_query = (
            f"SELECT * FROM {input_relation} "
            f"WHERE ActionGeo_CountryCode = {sql_string(FILTER_COUNTRY_CODE)}"
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
        connection.execute(
            f"COPY ({output_query}) TO {sql_string(output_path.as_posix())} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

        output_summary = summarize_relation(connection, parquet_relation(output_path))
    finally:
        connection.close()

    manifest = {
        "manifest_version": "india-event-universe.v1",
        "source_snapshot": "GDELT 2024 Events",
        "input_path": display_path(Path(input_glob)),
        "output_path": display_path(output_path),
        "filter": {
            "field": "ActionGeo_CountryCode",
            "operator": "=",
            "value": FILTER_COUNTRY_CODE,
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "input_rows": input_summary["rows"],
        "output_rows": output_summary["rows"],
        "input_day_min": input_summary["day_min"],
        "input_day_max": input_summary["day_max"],
        "output_day_min": output_summary["day_min"],
        "output_day_max": output_summary["day_max"],
        "columns_preserved": input_summary["columns"] == output_summary["columns"],
        "columns": output_summary["columns"],
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-glob", default=str(DEFAULT_INPUT_GLOB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_dataset(args.input_glob, Path(args.output), Path(args.manifest))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
