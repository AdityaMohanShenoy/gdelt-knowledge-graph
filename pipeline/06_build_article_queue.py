import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as parquet
from url_utils import normalize_url

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = ROOT / "data" / "working" / "india-2024" / "events.parquet"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "working" / "india-2024" / "article_urls.parquet"
DEFAULT_MANIFEST_PATH = ROOT / "data" / "working" / "india-2024" / "article_urls_manifest.json"


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parquet_relation(input_path: str | Path) -> str:
    return f"read_parquet({sql_string(Path(input_path).as_posix())}, hive_partitioning=true)"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_url_set(
    input_path: str | Path,
    output_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        rows = connection.execute(
            f"""
            SELECT SOURCEURL
            FROM {parquet_relation(input_path)}
            WHERE SOURCEURL IS NOT NULL AND SOURCEURL <> ''
            GROUP BY SOURCEURL
            ORDER BY SOURCEURL
            """
        ).fetchall()
    finally:
        connection.close()

    unique_urls: dict[str, str] = {}
    invalid_urls = 0
    normalization_collisions = 0
    for row in rows:
        source_url = str(row[0]).strip()
        url_key = normalize_url(source_url)
        if not url_key:
            invalid_urls += 1
            continue
        if url_key in unique_urls:
            normalization_collisions += 1
            continue
        unique_urls[url_key] = source_url

    records = [
        {"url_key": url_key, "source_url": source_url}
        for url_key, source_url in sorted(unique_urls.items())
    ]
    table = pa.Table.from_pylist(
        records,
        schema=pa.schema([("url_key", pa.string()), ("source_url", pa.string())]),
    )
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    parquet.write_table(table, output_path, compression="zstd")

    manifest = {
        "manifest_version": "india-article-url-set.v1",
        "source_path": display_path(Path(input_path)),
        "output_path": display_path(output_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "source_url_rows": len(rows),
        "unique_url_keys": len(records),
        "invalid_urls": invalid_urls,
        "normalization_collisions": normalization_collisions,
        "columns": ["url_key", "source_url"],
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
    manifest = build_url_set(args.input, Path(args.output), Path(args.manifest))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
