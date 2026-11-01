"""Phase 12: compile the causal graph from the evidence store and a config.

    .venv/bin/python pipeline/40_build_graph.py --schema text_graph \\
      --config pipeline/graph_config.v1.json [--register]

Writes data/evidence/graph/causal-graph.<version>.json, where the version is the
SHA-256 of the file's bytes. The build only reads the store, so the same store
and config always give the same bytes: an existing file for a version is checked
byte for byte, never overwritten. `--register` records the build in
`build_versions`, the one table it writes.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph_store import canonical_json, compile_graph, snapshot, version  # noqa: E402

from store.db import DEFAULT_DATABASE_URL, search_path_setup  # noqa: E402

OUT = ROOT / "data" / "evidence" / "graph"


async def main_async(args: argparse.Namespace) -> dict:
    config = json.loads(args.config.read_text())
    connection = await asyncpg.connect(args.database_url, statement_cache_size=0)
    try:
        await search_path_setup(args.schema)(connection)
        graph = compile_graph(await snapshot(connection), config)
        graph_version = version(graph)
        path = args.out_dir / f"causal-graph.{graph_version[:16]}.json"
        args.out_dir.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != graph:
                raise RuntimeError(f"{path} exists with different bytes: the build is not "
                                   "deterministic")
        else:
            path.write_bytes(graph)
        built = json.loads(graph)
        if args.register:
            # The config hash covers the store too: one config over a changed store
            # is a different build.
            key = hashlib.sha256(canonical_json(
                {"config": config, "store": built["store_fingerprint"]})).hexdigest()
            await connection.execute(
                "INSERT INTO build_versions (config_hash, config, graph_version) "
                "VALUES ($1, $2::jsonb, $3) ON CONFLICT (config_hash) DO NOTHING",
                key, json.dumps(config), graph_version)
        return {"graph": str(path), "version": graph_version, **built["counts"],
                "store_fingerprint": built["store_fingerprint"]}
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="text_graph")
    parser.add_argument("--config", type=Path, default=ROOT / "pipeline/graph_config.v1.json")
    parser.add_argument("--out-dir", type=Path, default=OUT)
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main_async(args)), indent=2))


if __name__ == "__main__":
    main()
