"""Хранилище лидерборда LP-провайдеров пула (lp_current, lp_meta)."""
from datetime import datetime, timezone

import asyncpg


async def get_leaderboard(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT * FROM lp_current ORDER BY rank")


async def get_meta(pool: asyncpg.Pool) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM lp_meta LIMIT 1")


async def replace_leaderboard(
    pool: asyncpg.Pool,
    rows: list[dict],
    block: int,
    flower_price_usd: float,
    total_tvl: float,
) -> None:
    """
    Полностью заменяет lp_current новым топом и обновляет lp_meta.
    prev_rank берётся из текущего (старого) ранга того же owner, если он был.
    """
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            old_ranks = {
                r["owner"]: r["rank"]
                for r in await conn.fetch("SELECT owner, rank FROM lp_current")
            }

            await conn.execute("TRUNCATE lp_current")
            await conn.executemany(
                """
                INSERT INTO lp_current
                    (owner, rank, prev_rank, value_usd, positions, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                [
                    (
                        r["owner"],
                        r["rank"],
                        old_ranks.get(r["owner"]),
                        r["value_usd"],
                        r["positions"],
                        now,
                    )
                    for r in rows
                ],
            )

            await conn.execute("TRUNCATE lp_meta")
            await conn.execute(
                """
                INSERT INTO lp_meta
                    (updated_at, block, flower_price_usd, total_tvl, wallets)
                VALUES ($1, $2, $3, $4, $5)
                """,
                now, block, flower_price_usd, total_tvl, len(rows),
            )
