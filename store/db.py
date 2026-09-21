"""Evidence store schema management — BUILD_PLAN P1.1.

    python -m store.db --init     # idempotent
    python -m store.db --check    # report what exists

Postgres rather than SQLite; see the header of store/schema.sql for why.
"""

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DATABASE_URL = os.environ.get(
    "EVIDENCE_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5433/gdelt"),
)

TABLES = (
    "sources", "entities", "events", "mentions", "conditions",
    "claims", "claim_channels", "annotations", "build_versions",
)
APPEND_ONLY = ("sources", "mentions", "annotations")


async def init(connection: asyncpg.Connection) -> None:
    await connection.execute(SCHEMA_PATH.read_text())


async def describe(connection: asyncpg.Connection) -> dict[str, int | None]:
    """Row count per table, or None where the table is absent."""
    state: dict[str, int | None] = {}
    for table in TABLES:
        exists = await connection.fetchval(
            "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
        )
        state[table] = (
            await connection.fetchval(f"SELECT count(*) FROM {table}") if exists else None
        )
    return state


async def main_async(args: argparse.Namespace) -> int:
    connection = await asyncpg.connect(args.database_url)
    try:
        if args.init:
            await init(connection)
            print(f"schema applied from {SCHEMA_PATH.relative_to(ROOT)}")
        state = await describe(connection)
        missing = [t for t, n in state.items() if n is None]
        for table, count in state.items():
            mark = "absent" if count is None else f"{count:>9,} rows"
            flag = "  (append-only)" if table in APPEND_ONLY else ""
            print(f"  {table:<16} {mark}{flag}")
        if missing:
            print(f"\nmissing: {', '.join(missing)} — run with --init")
            return 1
        return 0
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="create the schema (idempotent)")
    parser.add_argument("--check", action="store_true", help="report existing tables")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    args = parser.parse_args()
    if not args.init and not args.check:
        parser.error("pass --init or --check")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
