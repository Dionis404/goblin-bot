"""Только чтение auctions / auction_results — таблицы принадлежат сервису auctioneer-bot.

Ни одна функция здесь не пишет в эти таблицы — заполнение их данными
происходит в auctioneer-bot, а не в goblin-bot/goblin-api.
"""
import asyncpg


async def list_upcoming(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT auction_id, item_name, item_type, supply,
               sfl_price, ingredients, start_at, end_at
        FROM auctions
        WHERE start_at > now()
        ORDER BY start_at ASC
        """
    )


async def get_results(pool: asyncpg.Pool, auction_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT my_status, participant_count, supply, leaderboard
        FROM auction_results
        WHERE auction_id = $1
        """,
        auction_id,
    )
