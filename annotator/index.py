"""Vercel entry point.

A serverless function gets one connection per cold start and many of them, so
the pool is small and prepared statements are off: Supabase's transaction
pooler cannot carry them.
"""

import os
from contextlib import asynccontextmanager

import asyncpg

# Vercel loads this file as a top-level module with its directory on the path,
# so the package-relative import that works locally fails there.
try:
    from app import DEFAULT_SCHEMA, build_app, search_path_setup
except ImportError:  # imported as annotator.index
    from .app import DEFAULT_SCHEMA, build_app, search_path_setup

DATABASE_URL = os.environ["EVIDENCE_DATABASE_URL"]
SCHEMA = os.environ.get("EVIDENCE_SCHEMA", DEFAULT_SCHEMA)

_holder: dict = {}


@asynccontextmanager
async def lifespan(_app):
    _holder["pool"] = await asyncpg.create_pool(
        DATABASE_URL, min_size=0, max_size=2,
        setup=search_path_setup(SCHEMA), statement_cache_size=0)
    try:
        yield
    finally:
        await _holder["pool"].close()


app = build_app(_holder, lifespan)
