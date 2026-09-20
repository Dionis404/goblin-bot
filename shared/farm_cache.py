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


def _to_float(value) -> float | None:
    """balance/coins приходят строкой или числом — приводим к float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_farmer_stats(farm_entry: dict) -> dict:
    """
    Извлекает {game_username, xp, balance, coins} из объекта фермы в виде,
    который отдаёт и поштучный, и batch-эндпоинт после нормализации
    ({"id", "farm": {...}} — см. _fetch_batch_from_sfl / _fetch_from_sfl).
    """
    farm = farm_entry.get("farm") or {}
    return {
        "game_username": farm.get("username"),
        "xp": _to_float((farm.get("bumpkin") or {}).get("experience")),
        "balance": _to_float(farm.get("balance")),
        "coins": _to_float(farm.get("coins")),
    }


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


async def upsert_farm_data(pool: asyncpg.Pool, farm_id: int, data: dict) -> None:
    """
    Безусловно записывает свежие данные фермы (создаёт строку, если её ещё
    нет). В отличие от refresh_farm/refresh_farms_batch не участвует в
    is_refreshing-локе — предназначена для планового batch-прохода
    (jobs/daily_refresh.py), не для конкурентного ленивого обновления по
    запросу с сайта.
    """
    await pool.execute(
        """
        INSERT INTO farm_cache (farm_id, data, tracked, first_seen, last_requested_at, updated_at)
        VALUES ($1, $2, true, now(), now(), now())
        ON CONFLICT (farm_id) DO UPDATE
            SET data = EXCLUDED.data, updated_at = now()
        """,
        farm_id,
        data,
    )


def _api_headers() -> dict:
    return {"x-api-key": config.SFL_API_KEY} if config.SFL_API_KEY else {}


async def _fetch_from_sfl(farm_id: int) -> dict:
    url = f"{config.SFL_API_BASE}/community/farms/{farm_id}"

    async with httpx.AsyncClient(timeout=SFL_TIMEOUT) as client:
        resp = await client.get(url, headers=_api_headers())
        resp.raise_for_status()
        return resp.json()


BATCH_MAX_IDS = 100


async def _fetch_batch_from_sfl(farm_ids: list[int]) -> tuple[dict[int, dict], list[int]]:
    """
    Батч-запрос через deprecated, но всё ещё рабочий POST /community/getFarms
    (до 100 id за раз) — на порядок дешевле по rate limit, чем поштучные
    GET /community/farms/{id}, для точечного набора tracked-ферм.

    Ответ API — {"farms": {"<id>": <объект фермы без обёртки>}, "skipped": [...]}.
    Нормализуем под тот же вид, что отдаёт поштучный эндпоинт ({"id", "farm"}),
    чтобы farm_cache.data был одинаковым независимо от того, как обновлён.

    Возвращает (farms по id, skipped id) — skipped может значить как
    "фермы не существует", так и "срезано лимитом ответа 5.5MB" (см. доки).
    """
    if len(farm_ids) > BATCH_MAX_IDS:
        raise ValueError(f"getFarms принимает не больше {BATCH_MAX_IDS} id за раз")

    url = f"{config.SFL_API_BASE}/community/getFarms"

    async with httpx.AsyncClient(timeout=SFL_TIMEOUT) as client:
        resp = await client.post(url, json={"ids": farm_ids}, headers=_api_headers())
        resp.raise_for_status()
        data = resp.json()

    farms = {
        int(farm_id): {"id": int(farm_id), "farm": farm}
        for farm_id, farm in data.get("farms", {}).items()
    }
    skipped = [int(x) for x in data.get("skipped", [])]
    return farms, skipped


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
