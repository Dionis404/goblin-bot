"""Кэширующий слой между goblin-api и внешним SFL community API."""
import logging
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx

from shared import config

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=6)
SFL_TIMEOUT = 8.0


def is_stale(updated_at: datetime) -> bool:
    return datetime.now(timezone.utc) - updated_at > STALE_AFTER


async def get_farm(pool: asyncpg.Pool, farm_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM farm_cache WHERE farm_id = $1", farm_id)


async def get_farms(pool: asyncpg.Pool, farm_ids: list[int]) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM farm_cache WHERE farm_id = ANY($1::bigint[])", farm_ids
    )


async def touch_last_requested(pool: asyncpg.Pool, farm_id: int) -> None:
    await pool.execute(
        "UPDATE farm_cache SET last_requested_at = now() WHERE farm_id = $1",
        farm_id,
    )


async def ensure_placeholder(pool: asyncpg.Pool, farm_id: int) -> None:
    """Создаёт пустую отслеживаемую запись, если её ещё нет (не трогает существующую)."""
    await pool.execute(
        """
        INSERT INTO farm_cache (farm_id, data, tracked, first_seen, last_requested_at)
        VALUES ($1, $2, true, now(), now())
        ON CONFLICT (farm_id) DO NOTHING
        """,
        farm_id,
        None,
    )


async def _fetch_from_sfl(farm_id: int) -> dict:
    url = f"{config.SFL_API_BASE}/community/farms/{farm_id}"
    headers = {}
    if config.SFL_API_KEY:
        headers["x-api-key"] = config.SFL_API_KEY

    async with httpx.AsyncClient(timeout=SFL_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def refresh_farm(farm_id: int, pool: asyncpg.Pool) -> None:
    """
    Обновляет кэш одной фермы из внешнего SFL API.
    Не дублирует параллельные обновления одной и той же фермы.
    При ошибке внешнего API старые данные в `data` не трогает.
    """
    claimed = await pool.fetchval(
        """
        INSERT INTO farm_cache (farm_id, data, is_refreshing, tracked, first_seen, last_requested_at)
        VALUES ($1, $2, true, true, now(), now())
        ON CONFLICT (farm_id) DO UPDATE
            SET is_refreshing = true
            WHERE farm_cache.is_refreshing = false
        RETURNING farm_id
        """,
        farm_id,
        None,
    )
    if claimed is None:
        # Уже идёт обновление этой фермы — не дублируем.
        return

    try:
        data = await _fetch_from_sfl(farm_id)
    except Exception:
        log.warning("Не удалось обновить ферму %s", farm_id, exc_info=True)
        await pool.execute(
            "UPDATE farm_cache SET is_refreshing = false WHERE farm_id = $1",
            farm_id,
        )
        return

    await pool.execute(
        """
        UPDATE farm_cache
        SET data = $2, updated_at = now(), is_refreshing = false
        WHERE farm_id = $1
        """,
        farm_id,
        data,
    )
