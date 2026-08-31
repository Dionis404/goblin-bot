"""
Почасовой сбор лидерборда тикетов SFL: топ-500 целиком + точное место
tracked-фермеров, одним проходом, чтобы экономить запросы к API (жёсткий
rate limit на community API).

1. Один запрос забирает топ-500 — сохраняется в top500_snapshots (как раньше,
   не зависит от tracked-фермеров, нужен для сайта/API).

2. Для каждой фермы с farmers.tickets_tracked = true и tickets_excluded = false:
   - если ферма уже нашлась в этом же топ-500 — её ранг/тикеты берутся оттуда,
     без дополнительного запроса;
   - иначе делается отдельный запрос к /community/data?type=ticketLeaderboard.
   Снэпшот в ticket_leaderboard_snapshots пишется, только если ранг <= RANK_CUTOFF.
   Если ранг фермы (из любого источника) >= TICKETS_EXCLUDE_RANK, она помечается
   tickets_excluded — дальше почасовым отдельным запросом не трогается (но
   продолжает подхватываться бесплатно, если сама всплывёт в топ-500).

Запуск:
  python -m jobs.tickets_leaderboard
  или run_tickets_leaderboard() из планировщика бота.
"""
import asyncio
import logging

from shared import config, db, tickets_leaderboard

log = logging.getLogger(__name__)

DELAY_BETWEEN_FARMS_SEC = config.TICKETS_DELAY_BETWEEN_FARMS_SEC


async def run_tickets_leaderboard() -> dict:
    pool = await db.get_pool()

    top500 = await tickets_leaderboard.fetch_top500()
    await tickets_leaderboard.save_top500_snapshot(pool, top500)
    top500_by_farm = {row["farm_id"]: row for row in top500}

    farm_ids = await tickets_leaderboard.get_trackable_farm_ids(pool)

    saved = 0
    skipped = 0
    from_top500 = 0
    excluded = 0

    for farm_id in farm_ids:
        cached = top500_by_farm.get(farm_id)
        if cached is not None:
            result = {
                "rank": cached["rank"],
                "tickets": cached["tickets"],
                "game_username": cached["game_username"],
            }
            from_top500 += 1
        else:
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
            await asyncio.sleep(DELAY_BETWEEN_FARMS_SEC)

        if result["rank"] > tickets_leaderboard.RANK_CUTOFF:
            skipped += 1
        else:
            await tickets_leaderboard.save_snapshot(
                pool, farm_id, result["rank"], result["tickets"], result["game_username"]
            )
            saved += 1

        if result["rank"] >= tickets_leaderboard.TICKETS_EXCLUDE_RANK:
            await tickets_leaderboard.mark_excluded(pool, farm_id)
            excluded += 1

    log.info(
        "Снэпшот лидерборда тикетов готов: сохранено %s, пропущено %s, "
        "из топ-500 без запроса %s, вновь исключено %s (всего tracked %s)",
        saved, skipped, from_top500, excluded, len(farm_ids),
    )
    return {
        "saved": saved,
        "skipped": skipped,
        "from_top500": from_top500,
        "excluded": excluded,
        "total": len(farm_ids),
    }


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_tickets_leaderboard()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
