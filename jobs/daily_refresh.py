"""
Ежедневное обновление данных фермеров сообщества (farmers + farm_cache).

Обновляет ВСЕХ привязанных через /start фермеров (таблица farmers, а не
farm_cache.tracked — это разные вещи, см. историю) пачками по 100 через
POST /community/getFarms (deprecated, но кратно дешевле по rate limit, чем
поштучные GET /community/farms/{id}) с паузой между пачками.

Пишет в две таблицы за один и тот же ответ API:
- farmers.xp/balance/coins/game_username — иначе они остаются снимком на
  момент /start и никогда не меняются (то, что видно на странице сообщества);
- farm_cache.data — попутно освежает и кэш для /farm/{id}, /farms.

Крутится раз в сутки прямо в основном цикле бота (bot/main.py,
daily_refresh_loop). Можно запустить и отдельно — вручную или из cron:
python -m jobs.daily_refresh
"""
import asyncio
import logging

from shared import db, farm_cache

log = logging.getLogger(__name__)

DELAY_BETWEEN_BATCHES_SEC = 5.0  # community API троттлит ~1 запрос/5с на IP


async def run_daily_refresh() -> dict:
    """Обновляет статы всех фермеров сообщества. Возвращает {"succeeded", "skipped", "failed"}."""
    pool = await db.get_pool()
    farm_ids = await db.list_farmer_farm_ids()

    succeeded = skipped = failed = 0

    for i in range(0, len(farm_ids), farm_cache.BATCH_MAX_IDS):
        if i > 0:
            await asyncio.sleep(DELAY_BETWEEN_BATCHES_SEC)

        chunk = farm_ids[i:i + farm_cache.BATCH_MAX_IDS]
        try:
            farms, api_skipped = await farm_cache._fetch_batch_from_sfl(chunk)
        except Exception:
            log.warning("Не удалось обновить batch из %s фермеров", len(chunk), exc_info=True)
            failed += len(chunk)
            continue

        for farm_id in chunk:
            farm_entry = farms.get(farm_id)
            if farm_entry is None:
                skipped += 1
                continue

            stats = farm_cache.parse_farmer_stats(farm_entry)
            await db.update_farmer_stats(
                farm_id, stats["game_username"], stats["xp"], stats["balance"], stats["coins"]
            )
            await farm_cache.upsert_farm_data(pool, farm_id, farm_entry)
            succeeded += 1

        if api_skipped:
            log.info("getFarms вернул skipped для %s фермеров: %s", len(api_skipped), api_skipped)

    log.info(
        "Обновление фермеров сообщества завершено: %s успешно, %s пропущено, %s с ошибкой (всего %s)",
        succeeded, skipped, failed, len(farm_ids),
    )
    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_daily_refresh()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
