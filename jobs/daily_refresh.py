"""
Ежедневный батч-прогрев кэша ферм (farm_cache).

Обновляет все отслеживаемые фермы (tracked = true) пачками по 100 через
POST /community/getFarms (deprecated, но кратно дешевле по rate limit, чем
поштучные GET /community/farms/{id} — см. shared/farm_cache.refresh_farms_batch)
с паузой между пачками. Крутится раз в сутки прямо в основном цикле бота
(bot/main.py, daily_refresh_loop). Можно запустить и отдельно — вручную
или из cron: python -m jobs.daily_refresh
"""
import logging

from shared import db, farm_cache

log = logging.getLogger(__name__)

DELAY_BETWEEN_BATCHES_SEC = 5.0  # community API троттлит ~1 запрос/5с на IP


async def run_daily_refresh() -> dict:
    """Обновляет все tracked-фермы пачками. Возвращает {"succeeded", "skipped", "failed"}."""
    pool = await db.get_pool()
    rows = await pool.fetch("SELECT farm_id FROM farm_cache WHERE tracked = true")
    farm_ids = [r["farm_id"] for r in rows]

    result = await farm_cache.refresh_farms_batch(
        farm_ids, pool, delay_between_chunks_sec=DELAY_BETWEEN_BATCHES_SEC
    )

    log.info(
        "Батч-прогрев farm_cache завершён: %s успешно, %s пропущено, %s с ошибкой (всего %s)",
        result["succeeded"], result["skipped"], result["failed"], len(farm_ids),
    )
    return result


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_daily_refresh()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
