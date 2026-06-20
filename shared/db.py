"""Общий слой доступа к БД (asyncpg pool)."""
import asyncpg
from shared import config

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Ленивая инициализация пула соединений."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=config.DB_HOST,
            port=config.DB_PORT,
            database=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            min_size=1,
            max_size=5,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# --- Операции с farmers ---

async def get_farmer_by_telegram(telegram_id: int) -> asyncpg.Record | None:
    pool = await get_pool()
    return await pool.fetchrow(
        "SELECT * FROM farmers WHERE telegram_id = $1", telegram_id
    )


async def get_farmer_by_farm(farm_id: int) -> asyncpg.Record | None:
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM farmers WHERE farm_id = $1", farm_id)


async def insert_farmer(
    telegram_id: int,
    telegram_username: str | None,
    farm_id: int,
    game_username: str | None,
    xp: float | None,
    balance: float | None,
    coins: float | None,
    farm_url: str | None,
) -> str:
    """
    Пытается записать фермера.
    Возвращает статус: 'ok' | 'telegram_taken' | 'farm_taken'.
    ON CONFLICT защищает от гонки и повторной привязки.
    """
    pool = await get_pool()

    # Проверяем оба ограничения заранее для понятных сообщений
    if await get_farmer_by_telegram(telegram_id):
        return "telegram_taken"
    if await get_farmer_by_farm(farm_id):
        return "farm_taken"

    try:
        await pool.execute(
            """
            INSERT INTO farmers
              (telegram_id, telegram_username, farm_id, game_username,
               xp, balance, coins, farm_url)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            telegram_id, telegram_username, farm_id, game_username,
            xp, balance, coins, farm_url,
        )
        return "ok"
    except asyncpg.UniqueViolationError as e:
        # На случай гонки между проверкой и вставкой
        if "telegram_id" in str(e):
            return "telegram_taken"
        return "farm_taken"


async def list_farmers() -> list[asyncpg.Record]:
    """Все фермеры для страницы сообщества, отсортированы по XP."""
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM farmers ORDER BY xp DESC NULLS LAST"
    )
