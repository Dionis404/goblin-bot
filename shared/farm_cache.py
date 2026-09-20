"""Кэширующий слой между goblin-api и внешним SFL community API."""
import asyncio
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


async def refresh_farms_batch(
    farm_ids: list[int], pool: asyncpg.Pool, delay_between_chunks_sec: float = 0.0
) -> dict:
    """
    Обновляет кэш ферм из farm_cache через POST /community/getFarms — список
    любого размера сам режется на подпачки по BATCH_MAX_IDS (community API
    троттлит запросы, поэтому между HTTP-вызовами выдерживается пауза
    delay_between_chunks_sec, если подпачек больше одной). Как и refresh_farm,
    не дублирует параллельные обновления и не трогает старые данные при ошибке.

    Возвращает {"succeeded": int, "skipped": int, "failed": int}.
    """
    succeeded = skipped_count = failed = 0

    for i in range(0, len(farm_ids), BATCH_MAX_IDS):
        if i > 0 and delay_between_chunks_sec:
            await asyncio.sleep(delay_between_chunks_sec)

        chunk = farm_ids[i:i + BATCH_MAX_IDS]

        claimed_rows = await pool.fetch(
            """
            UPDATE farm_cache SET is_refreshing = true
            WHERE farm_id = ANY($1::bigint[]) AND is_refreshing = false
            RETURNING farm_id
            """,
            chunk,
        )
        claimed = [r["farm_id"] for r in claimed_rows]
        if not claimed:
            continue

        try:
            farms, api_skipped = await _fetch_batch_from_sfl(claimed)
        except Exception:
            log.warning("Не удалось обновить batch из %s ферм", len(claimed), exc_info=True)
            await pool.execute(
                "UPDATE farm_cache SET is_refreshing = false WHERE farm_id = ANY($1::bigint[])",
                claimed,
            )
            failed += len(claimed)
            continue

        for farm_id in claimed:
            data = farms.get(farm_id)
            if data is None:
                skipped_count += 1
                await pool.execute(
                    "UPDATE farm_cache SET is_refreshing = false WHERE farm_id = $1", farm_id
                )
                continue
            await pool.execute(
                """
                UPDATE farm_cache
                SET data = $2, updated_at = now(), is_refreshing = false
                WHERE farm_id = $1
                """,
                farm_id,
                data,
            )
            succeeded += 1

        if api_skipped:
            log.info("getFarms вернул skipped для %s ферм: %s", len(api_skipped), api_skipped)

    return {"succeeded": succeeded, "skipped": skipped_count, "failed": failed}
