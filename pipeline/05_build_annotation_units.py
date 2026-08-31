import argparse
import hashlib
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
DEFAULT_MANIFEST_PATH = (
    ROOT / "data" / "working" / "india-2024" / "annotation_manifest.json"
)


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


def unit_id(source_url: str, event_code: str) -> str:
    key = f"{source_url}\x1f{event_code}".encode()
    return "unit-" + hashlib.sha1(key).hexdigest()[:16]


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
            ORDER BY SOURCEURL, EventCode, day, GlobalEventID
            """
        ).fetchall()
    finally:
        connection.close()

    units_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    variant_keys: dict[tuple[str, str], set[tuple[str | None, ...]]] = {}
    for row in rows:
        source_url = str(row[0])
        event_code = value_text(row[1]) or "unknown"
        key = (source_url, event_code)
        if key not in units_by_key:
            units_by_key[key] = {
                "unit_id": unit_id(source_url, event_code),
                "source_url": source_url,
                "event_code": event_code,
                "root": value_text(row[2]),
                "event_count": 0,
                "dates": [],
                "goldstein_values": [],
                "actor_variants": [],
                "members": [],
            }
            variant_keys[key] = set()

        unit = units_by_key[key]
        member = {
            "id": value_text(row[5]),
            "day": value_text(row[3]),
            "datetime": value_text(row[4]),
            "goldstein": row[6],
            "actor1": row[7],
            "actor1_country": row[8],
            "actor2": row[9],
            "actor2_country": row[10],
        }
        unit["members"].append(member)
        unit["event_count"] += 1
        if member["day"] is not None and member["day"] not in unit["dates"]:
            unit["dates"].append(member["day"])
        if row[6] is not None and row[6] not in unit["goldstein_values"]:
            unit["goldstein_values"].append(row[6])

        actor_variant = {
            "actor1": row[7],
            "actor1_country": row[8],
            "actor2": row[9],
            "actor2_country": row[10],
        }
        actor_key = tuple(value_text(actor_variant[field]) for field in actor_variant)
        if actor_key not in variant_keys[key]:
            variant_keys[key].add(actor_key)
            unit["actor_variants"].append(actor_variant)

    units = sorted(
        units_by_key.values(),
        key=lambda item: (item["dates"][0] if item["dates"] else "", item["unit_id"]),
    )
    for unit in units:
        unit["dates"].sort()

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    payload = {
        "schema_version": "india-annotation-units.v1",
        "source_path": display_path(Path(input_path)),
        "generated_at": datetime.now(UTC).isoformat(),
        "group_key": ["SOURCEURL", "EventCode"],
        "count": len(units),
        "member_count": sum(unit["event_count"] for unit in units),
        "units": units,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )

    root_counts: dict[str, int] = {}
    for unit in units:
        root = unit["root"] or "unknown"
        root_counts[root] = root_counts.get(root, 0) + 1
    manifest = {
        "manifest_version": "india-annotation-units.v1",
        "source_path": display_path(Path(input_path)),
        "output_path": display_path(output_path),
        "generated_at": payload["generated_at"],
        "group_key": ["SOURCEURL", "EventCode"],
        "unit_count": len(units),
        "member_event_count": payload["member_count"],
        "unique_source_urls": len({unit["source_url"] for unit in units}),
        "multi_member_units": sum(unit["event_count"] > 1 for unit in units),
        "max_members_in_unit": max(
            (unit["event_count"] for unit in units),
            default=0,
        ),
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
