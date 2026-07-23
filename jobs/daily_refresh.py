"""
Ежедневный батч-прогрев кэша ферм (farm_cache).

Обновляет все отслеживаемые фермы (tracked = true) с небольшой паузой между
запросами, чтобы не бить внешний SFL API залпом. Можно запускать:
- вручную / из cron:            python -m jobs.daily_refresh
- из n8n HTTP-запроса к обёртке (см. run_daily_refresh)
- из APScheduler:                await run_daily_refresh()
"""
import asyncio
import logging

from shared import db, farm_cache

log = logging.getLogger(__name__)

DELAY_BETWEEN_FARMS_SEC = 0.5


async def run_daily_refresh() -> dict:
    """Обновляет все tracked-фермы. Возвращает {"succeeded": int, "failed": int}."""
    pool = await db.get_pool()
    rows = await pool.fetch("SELECT farm_id FROM farm_cache WHERE tracked = true")
    farm_ids = [r["farm_id"] for r in rows]

    succeeded = 0
    failed = 0

    for farm_id in farm_ids:
        before = await farm_cache.get_farm(pool, farm_id)
        await farm_cache.refresh_farm(farm_id, pool)
        after = await farm_cache.get_farm(pool, farm_id)

        if after is not None and before is not None and after["updated_at"] > before["updated_at"]:
            succeeded += 1
        else:
            failed += 1

        await asyncio.sleep(DELAY_BETWEEN_FARMS_SEC)

    log.info(
        "Батч-прогрев farm_cache завершён: %s успешно, %s с ошибкой (всего %s)",
        succeeded, failed, len(farm_ids),
    )
    return {"succeeded": succeeded, "failed": failed}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_daily_refresh()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
