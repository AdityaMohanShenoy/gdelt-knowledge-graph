import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = (
    ROOT / "data" / "working" / "india-2024" / "target_events_url_validated.parquet"
)
DEFAULT_OUTPUT_PATH = ROOT / "data" / "working" / "india-2024" / "annotation_units.json"
DEFAULT_MANIFEST_PATH = ROOT / "data" / "working" / "india-2024" / "annotation_manifest.json"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_relation(input_path: str | Path) -> str:
    return f"read_parquet({sql_string(Path(input_path).as_posix())}, hive_partitioning=true)"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def value_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def unit_id(event_id: str) -> str:
    return "event-" + event_id


def build_units(
    input_path: str | Path,
    output_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            SELECT
                SOURCEURL,
                EventCode,
                EventRootCode,
                day,
                datetime,
                GlobalEventID,
                GoldsteinScale,
                Actor1Name,
                Actor1CountryCode,
                Actor2Name,
                Actor2CountryCode
            FROM {parquet_relation(input_path)}
            WHERE SOURCEURL IS NOT NULL AND SOURCEURL <> ''
            ORDER BY day, GlobalEventID
            """
        ).fetchall()
    finally:
        connection.close()

    units: list[dict[str, Any]] = []
    for row in rows:
        source_url = str(row[0])
        event_code = value_text(row[1]) or "unknown"
        event_id = value_text(row[5]) or "unknown"
        units.append(
            {
                "unit_id": unit_id(event_id),
                "event_id": event_id,
                "source_url": source_url,
                "event_code": event_code,
                "root": value_text(row[2]),
                "day": value_text(row[3]),
                "datetime": value_text(row[4]),
                "goldstein": row[6],
                "actor1": row[7],
                "actor1_country": row[8],
                "actor2": row[9],
                "actor2_country": row[10],
            }
        )

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    payload = {
        "schema_version": "india-annotation-events.v2",
        "source_path": display_path(Path(input_path)),
        "generated_at": datetime.now(UTC).isoformat(),
        "record_type": "event_observation",
        "count": len(units),
        "units": units,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    root_counts: dict[str, int] = {}
    for unit in units:
        root = unit["root"] or "unknown"
        root_counts[root] = root_counts.get(root, 0) + 1
    manifest = {
        "manifest_version": "india-annotation-events.v2",
        "source_path": display_path(Path(input_path)),
        "output_path": display_path(output_path),
        "generated_at": payload["generated_at"],
        "record_type": "event_observation",
        "event_count": len(units),
        "unique_source_urls": len({unit["source_url"] for unit in units}),
        "units_by_root": root_counts,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_units(
        args.input,
        Path(args.output),
        Path(args.manifest),
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
