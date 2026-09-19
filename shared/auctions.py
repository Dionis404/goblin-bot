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


async def list_past(
    pool: asyncpg.Pool, limit: int = 20, item_name: str | None = None
) -> list[asyncpg.Record]:
    """
    Прошедшие аукционы (start_at <= now()), от самого недавнего.
    С item_name — история конкретного предмета (регистронезависимо, точное совпадение).
    """
    if item_name is not None:
        return await pool.fetch(
            """
            SELECT auction_id, item_name, item_type, supply,
                   sfl_price, ingredients, start_at, end_at
            FROM auctions
            WHERE start_at <= now() AND item_name ILIKE $2
            ORDER BY start_at DESC
            LIMIT $1
            """,
            limit, item_name,
        )
    return await pool.fetch(
        """
        SELECT auction_id, item_name, item_type, supply,
               sfl_price, ingredients, start_at, end_at
        FROM auctions
        WHERE start_at <= now()
        ORDER BY start_at DESC
        LIMIT $1
        """,
        limit,
    )


async def get_results(pool: asyncpg.Pool, auction_id: str) -> asyncpg.Record | None:
    """Результаты аукциона вместе с item_name/item_type (JOIN на auctions)."""
    return await pool.fetchrow(
        """
        SELECT a.item_name, a.item_type,
               r.my_status, r.participant_count, r.supply, r.leaderboard, r.fetched_at
        FROM auction_results r
        JOIN auctions a ON a.auction_id = r.auction_id
        WHERE r.auction_id = $1
        """,
        auction_id,
    )
