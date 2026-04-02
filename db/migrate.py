"""Raw SQL migration runner for livestream-to-agi.

Usage:
    python -m db              # apply all pending migrations
    python -m db up           # apply all pending migrations
    python -m db down         # roll back the most recent migration
    python -m db status       # show applied and pending migrations

Reads DATABASE_URL from environment (with .env fallback).
Tracks applied migrations in a `schema_migrations` table.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Pattern: NNN_name.up.sql  (captures version number and name)
MIGRATION_RE = re.compile(r"^(\d+)_(.+)\.up\.sql$")


async def _get_connection() -> asyncpg.Connection:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)
    return await asyncpg.connect(url, timeout=60)


async def _ensure_schema_migrations(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


def _discover_migrations() -> list[tuple[int, str, Path]]:
    """Return sorted list of (version, name, up_path) from the migrations dir."""
    migrations: list[tuple[int, str, Path]] = []
    for f in sorted(MIGRATIONS_DIR.iterdir()):
        m = MIGRATION_RE.match(f.name)
        if m:
            version = int(m.group(1))
            name = m.group(2)
            migrations.append((version, name, f))
    return migrations


async def _applied_versions(conn: asyncpg.Connection) -> set[int]:
    rows = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
    return {r["version"] for r in rows}


async def up(conn: asyncpg.Connection) -> None:
    await _ensure_schema_migrations(conn)
    applied = await _applied_versions(conn)
    migrations = _discover_migrations()
    pending = [(v, n, p) for v, n, p in migrations if v not in applied]

    if not pending:
        print("No pending migrations.")
        return

    for version, name, up_path in pending:
        sql = up_path.read_text()
        print(f"Applying {version:03d}_{name} ... ", end="", flush=True)
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                version,
                name,
            )
        print("OK")


async def down(conn: asyncpg.Connection) -> None:
    await _ensure_schema_migrations(conn)
    applied = await _applied_versions(conn)

    if not applied:
        print("No migrations to roll back.")
        return

    latest = max(applied)
    # Find the matching up file to derive the down file name
    migrations = _discover_migrations()
    match = next((m for m in migrations if m[0] == latest), None)
    if match is None:
        print(f"ERROR: Migration file for version {latest} not found.", file=sys.stderr)
        sys.exit(1)

    _, name, up_path = match
    down_path = up_path.with_name(f"{latest:03d}_{name}.down.sql")
    if not down_path.exists():
        print(f"ERROR: Down migration not found: {down_path.name}", file=sys.stderr)
        sys.exit(1)

    sql = down_path.read_text()
    print(f"Rolling back {latest:03d}_{name} ... ", end="", flush=True)
    async with conn.transaction():
        await conn.execute(sql)
        await conn.execute("DELETE FROM schema_migrations WHERE version = $1", latest)
    print("OK")


async def status(conn: asyncpg.Connection) -> None:
    await _ensure_schema_migrations(conn)
    applied = await _applied_versions(conn)
    migrations = _discover_migrations()

    print(f"{'Version':<10} {'Name':<30} {'Status'}")
    print("-" * 55)
    for version, name, _ in migrations:
        s = "applied" if version in applied else "pending"
        print(f"{version:<10} {name:<30} {s}")


async def _run(command: str) -> None:
    conn = await _get_connection()
    try:
        if command == "up":
            await up(conn)
        elif command == "down":
            await down(conn)
        elif command == "status":
            await status(conn)
        else:
            print(f"Unknown command: {command}", file=sys.stderr)
            print("Usage: python -m db [up|down|status]", file=sys.stderr)
            sys.exit(1)
    finally:
        await conn.close()


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "up"
    asyncio.run(_run(command))


if __name__ == "__main__":
    main()
