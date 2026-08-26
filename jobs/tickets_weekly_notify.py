"""
Еженедельное уведомление в группу о местах в лидерборде тикетов SFL.

Отправляется в ночь с воскресенья на понедельник в 03:00 (Europe/Moscow).
В сообщение попадают только отслеживаемые фермы (farmers.tickets_tracked),
у которых есть снэпшот с rank <= RANK_CUTOFF (берётся последний перед
моментом отправки) — остальные в сообщение не включаются.

Запуск:
  python -m jobs.tickets_weekly_notify
  или run_tickets_weekly_notify(bot) из планировщика бота.
"""
import logging
from datetime import datetime, timezone

from aiogram import Bot

from shared import config, db, tickets_leaderboard

log = logging.getLogger(__name__)


def _display_name(telegram_username: str | None, game_username: str | None, farm_id: int) -> str:
    if telegram_username:
        return f"@{telegram_username}"
    if game_username:
        return game_username
    return f"Ферма #{farm_id}"


async def build_weekly_report(as_of: datetime | None = None) -> list[dict]:
    """Список {display_name, rank, tickets}, отсортированный по месту (по возрастанию)."""
    as_of = as_of or datetime.now(timezone.utc)
    pool = await db.get_pool()
    farmers = await tickets_leaderboard.get_tracked_farmers(pool)

    report = []
    for farmer in farmers:
        snapshot = await tickets_leaderboard.get_latest_snapshot_before(
            pool, farmer["farm_id"], as_of
        )
        if snapshot is None:
            continue
        report.append({
            "display_name": _display_name(
                farmer["telegram_username"], snapshot["game_username"], farmer["farm_id"]
            ),
            "rank": snapshot["rank"],
            "tickets": snapshot["tickets"],
        })

    report.sort(key=lambda r: r["rank"])
    return report


def format_report(report: list[dict]) -> str:
    if not report:
        return "🎟 На этой неделе никто из отслеживаемых фермеров не попал в топ-1200 лидерборда тикетов."

    lines = ["🎟 <b>Лидерборд тикетов — итоги недели</b>\n"]
    for r in report:
        lines.append(f"{r['display_name']} — {r['rank']} место — {r['tickets']} тикетов")
    return "\n".join(lines)


async def run_tickets_weekly_notify(bot: Bot) -> dict:
    if config.TICKETS_NOTIFY_CHAT_ID is None:
        log.warning("TICKETS_NOTIFY_CHAT_ID не задан — еженедельное уведомление пропущено")
        return {"sent": False, "reason": "no_chat_id"}

    report = await build_weekly_report()
    text = format_report(report)

    await bot.send_message(config.TICKETS_NOTIFY_CHAT_ID, text)
    log.info("Еженедельное уведомление о лидерборде тикетов отправлено (%s фермеров в отчёте)",
              len(report))
    return {"sent": True, "count": len(report)}
