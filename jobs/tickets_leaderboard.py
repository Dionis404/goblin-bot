"""
Почасовой сбор места отслеживаемых ферм в лидерборде тикетов SFL.

Для каждой фермы с farmers.tickets_tracked = true делает один запрос к
/leaderboard/tickets/{farm_id} и, если ранг <= RANK_CUTOFF, пишет снэпшот
в ticket_leaderboard_snapshots. Фермы вне ранга (или отсутствующие в ответе
API) просто пропускаются — снэпшот не создаётся.

Запуск:
  python -m jobs.tickets_leaderboard
  или run_tickets_leaderboard() из планировщика бота.
"""
import asyncio
import logging

from shared import db, tickets_leaderboard

log = logging.getLogger(__name__)

DELAY_BETWEEN_FARMS_SEC = 0.5


async def run_tickets_leaderboard() -> dict:
    pool = await db.get_pool()
    farm_ids = await tickets_leaderboard.get_tracked_farm_ids(pool)

    saved = 0
    skipped = 0

    for farm_id in farm_ids:
        try:
            result = await tickets_leaderboard.fetch_farm_rank(farm_id)
        except tickets_leaderboard.FarmRankNotFound:
            skipped += 1
            await asyncio.sleep(DELAY_BETWEEN_FARMS_SEC)
            continue
        except Exception:
            log.exception("Ошибка запроса лидерборда тикетов для фермы %s", farm_id)
            skipped += 1
            await asyncio.sleep(DELAY_BETWEEN_FARMS_SEC)
            continue

        if result["rank"] > tickets_leaderboard.RANK_CUTOFF:
            skipped += 1
        else:
            await tickets_leaderboard.save_snapshot(
                pool, farm_id, result["rank"], result["tickets"], result["game_username"]
            )
            saved += 1

        await asyncio.sleep(DELAY_BETWEEN_FARMS_SEC)

    log.info(
        "Снэпшот лидерборда тикетов готов: сохранено %s, пропущено %s (всего %s)",
        saved, skipped, len(farm_ids),
    )
    return {"saved": saved, "skipped": skipped, "total": len(farm_ids)}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_tickets_leaderboard()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
