"""Evidence store schema management — BUILD_PLAN P1.1.

    python -m store.db --init     # idempotent
    python -m store.db --check    # report what exists

Postgres rather than SQLite; see the header of store/schema.sql for why.
"""

import argparse
import asyncio
import os
import re
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
# sources references article_documents, so the store is only self-contained
# if that table exists in the same schema. Without it the foreign key
# silently resolves to public, which does not exist on a hosted database.
ARTICLE_SCHEMA_PATH = ROOT / "pipeline" / "article_schema.sql"
DEFAULT_DATABASE_URL = os.environ.get(
    "EVIDENCE_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql://gdelt:gdelt_local@localhost:5433/gdelt"),
)

TABLES = (
    "sources", "entities", "events", "mentions", "conditions",
    "claims", "claim_channels", "annotations", "build_versions",
)
APPEND_ONLY = ("sources", "mentions", "annotations")
DEFAULT_SCHEMA = os.environ.get("EVIDENCE_SCHEMA", "public")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def check_schema(name: str) -> str:
    """Schema names are interpolated, never parameterised — Postgres has no
    placeholder for an identifier. So they are validated rather than trusted."""
    if not _IDENT.match(name or ""):
        raise ValueError(f"not a usable schema name: {name!r}")
    return name


def search_path_setup(schema: str):
    """asyncpg pool `setup`, so every connection lands in the right schema.
    `public` stays on the path for extensions."""
    schema = check_schema(schema)

    async def setup(connection):
        await connection.execute(f'SET search_path TO "{schema}", public')

    return setup


async def ensure_schema(connection, schema: str) -> None:
    schema = check_schema(schema)
    if schema != "public":
        await connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    await connection.execute(f'SET search_path TO "{schema}", public')


async def init(connection: asyncpg.Connection, schema: str = "public") -> None:
    await ensure_schema(connection, schema)
    await connection.execute(ARTICLE_SCHEMA_PATH.read_text())
    await connection.execute(SCHEMA_PATH.read_text())


async def describe(connection: asyncpg.Connection, schema: str = "public") -> dict[str, int | None]:
    """Row count per table, or None where the table is absent."""
    schema = check_schema(schema)
    state: dict[str, int | None] = {}
    for table in TABLES:
        exists = await connection.fetchval(
            "SELECT to_regclass($1) IS NOT NULL", f"{schema}.{table}"
        )
        state[table] = (
            await connection.fetchval(f"SELECT count(*) FROM {table}") if exists else None
        )
    return state


async def main_async(args: argparse.Namespace) -> int:
    connection = await asyncpg.connect(args.database_url, statement_cache_size=0)
    try:
        await ensure_schema(connection, args.schema)
        if args.init:
            await init(connection, args.schema)
            print(f"schema applied from {SCHEMA_PATH.relative_to(ROOT)} into \"{args.schema}\"")
        state = await describe(connection, args.schema)
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
    parser.add_argument("--schema", default=DEFAULT_SCHEMA,
                        help="keeps the store out of public, which Supabase's "
                             "REST API exposes by default")
    args = parser.parse_args()
    if not args.init and not args.check:
        parser.error("pass --init or --check")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
