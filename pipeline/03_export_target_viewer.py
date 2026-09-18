import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = ROOT / "data" / "working" / "india-2024" / "target_events.parquet"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "working" / "india-2024" / "target_events.json"
TARGET_ROOT_CODES = ("14", "18", "19", "20")


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_relation(input_path: str | Path) -> str:
    return f"read_parquet({sql_string(Path(input_path).as_posix())}, hive_partitioning=true)"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def export_dataset(input_path: str | Path, output_path: Path) -> dict:
    connection = duckdb.connect()
    input_relation = parquet_relation(input_path)
    target_codes = ", ".join(sql_string(code) for code in TARGET_ROOT_CODES)
    query = f"""
        SELECT
            day,
            datetime,
            GlobalEventID,
            EventCode,
            EventRootCode,
            GoldsteinScale,
            Actor1Name,
            Actor1CountryCode,
            Actor2Name,
            Actor2CountryCode,
            SOURCEURL
        FROM {input_relation}
        WHERE EventRootCode IN ({target_codes})
        ORDER BY day, GlobalEventID
    """

    try:
        rows = connection.execute(query).fetchall()
    finally:
        connection.close()

    events = [
        {
            "day": str(row[0]) if row[0] is not None else None,
            "datetime": str(row[1]) if row[1] is not None else None,
            "id": row[2],
            "event_code": row[3],
            "root": row[4],
            "goldstein": row[5],
            "actor1": row[6],
            "actor1_country": row[7],
            "actor2": row[8],
            "actor2_country": row[9],
            "url": row[10],
        }
        for row in rows
    ]
    payload = {
        "schema_version": "india-target-viewer.v1",
        "source_path": display_path(Path(input_path)),
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(events),
        "events": events,
    }

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    return {
        "schema_version": payload["schema_version"],
        "generated_at": payload["generated_at"],
        "count": payload["count"],
        "output_path": display_path(output_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(export_dataset(args.input, Path(args.output)), indent=2))


if __name__ == "__main__":
    main()
