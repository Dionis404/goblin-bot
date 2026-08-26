"""
Почасовой снэпшот глобального топ-500 лидерборда тикетов SFL (top500_snapshots).

Один тяжёлый запрос /leaderboard/tickets/{любой_farm_id}?limit=500 в час —
не зависит от tracked-фермеров, нужен для отдачи полного борда через сайт/API.

Запуск:
  python -m jobs.top500_snapshot
  или run_top500_snapshot() из планировщика бота.
"""
import asyncio
import logging

from shared import db, tickets_leaderboard

log = logging.getLogger(__name__)


async def run_top500_snapshot() -> dict:
    pool = await db.get_pool()
    rows = await tickets_leaderboard.fetch_top500()
    await tickets_leaderboard.save_top500_snapshot(pool, rows)
    log.info("Снэпшот топ-500 лидерборда тикетов сохранён: %s строк", len(rows))
    return {"rows": len(rows)}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_top500_snapshot()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
