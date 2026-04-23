from __future__ import annotations

import json
import os

import asyncpg


_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    dsn = os.environ["DATABASE_URL"]
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=10,
        command_timeout=10,
    )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        return await init_pool()
    return _pool


async def insert_batch(
    pool: asyncpg.Pool,
    ip_hash: str,
    rows: list[tuple[str, int, str]],
) -> None:
    """rows: [(axor_version, schema_version, payload_json), ...]"""
    await pool.executemany(
        "INSERT INTO records(client_ip_hash, axor_version, schema_version, payload) "
        "VALUES ($1, $2, $3, $4::jsonb)",
        [(ip_hash, v, s, p) for v, s, p in rows],
    )
