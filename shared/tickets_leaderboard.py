"""Лидерборд тикетов SFL: чтение снэпшотов из БД для бота.

Сбор данных (топ-500 + места tracked-фермеров) делает sfl-collector —
бот в SFL API за лидербордом не ходит. Здесь только запросы к БД,
нужные /tracking_lb, еженедельному отчёту и сбросу tickets_excluded
при смене главы.
"""
import logging
from datetime import datetime

import asyncpg

log = logging.getLogger(__name__)

RANK_CUTOFF = 1200

# Если последний известный ранг фермы >= этого порога, она больше не
# опрашивается отдельно (farmers.tickets_excluded; снимает sfl-collector
# при смене главы через reset_all_excluded).
TICKETS_EXCLUDE_RANK = 2000


async def reset_all_excluded(pool: asyncpg.Pool) -> int:
    """
    Сбрасывает tickets_excluded всем фермерам — вызывается один раз со стартом
    новой главы (тикеты обнуляются игрой, старый "низкий ранг" больше не
    актуален). Возвращает число затронутых строк.
    """
    result = await pool.execute(
        "UPDATE farmers SET tickets_excluded = false WHERE tickets_excluded = true"
    )
    return int(result.split()[-1])


async def get_tracked_farmers(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Отслеживаемые фермеры (farm_id + telegram_username + tickets_excluded)."""
    return await pool.fetch(
        "SELECT farm_id, telegram_username, tickets_excluded FROM farmers WHERE tickets_tracked = true"
    )


async def get_latest_snapshot_before(
    pool: asyncpg.Pool, farm_id: int, before: datetime
) -> asyncpg.Record | None:
    """Последний снэпшот фермы строго до указанного момента (для сравнения ВС->ПН)."""
    return await pool.fetchrow(
        """
        SELECT * FROM ticket_leaderboard_snapshots
        WHERE farm_id = $1 AND taken_at < $2
        ORDER BY taken_at DESC
        LIMIT 1
        """,
        farm_id, before,
    )


async def set_tracking(pool: asyncpg.Pool, telegram_id: int, enabled: bool) -> None:
    await pool.execute(
        "UPDATE farmers SET tickets_tracked = $2 WHERE telegram_id = $1",
        telegram_id, enabled,
    )


async def get_tracked_with_top500(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """
    Tracked-фермеры + их место в последнем снэпшоте топ-500.
    top500_rank = NULL -> ферма сейчас вне топ-500.
    """
    return await pool.fetch(
        """
        SELECT f.farm_id, f.telegram_username, f.tickets_excluded,
               t.rank AS top500_rank, t.tickets AS top500_tickets,
               t.taken_at AS top500_taken_at
        FROM farmers f
        LEFT JOIN top500_snapshots t
          ON t.farm_id = f.farm_id
         AND t.taken_at = (SELECT MAX(taken_at) FROM top500_snapshots)
        WHERE f.tickets_tracked = true
        ORDER BY t.rank NULLS LAST, f.farm_id
        """
    )


# --- Топ-500 целиком (top500_snapshots) — чтение ---

async def get_latest_top500(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Последний почасовой снэпшот топ-500, отсортированный по месту."""
    return await pool.fetch(
        """
        SELECT * FROM top500_snapshots
        WHERE taken_at = (SELECT MAX(taken_at) FROM top500_snapshots)
        ORDER BY rank
        """
    )


async def get_top500_at(pool: asyncpg.Pool, at: datetime) -> list[asyncpg.Record]:
    """
    Снэпшот топ-500, ближайший к моменту `at`, но не позже него
    (историческая точка "как выглядел борд на такой-то момент").
    """
    return await pool.fetch(
        """
        SELECT * FROM top500_snapshots
        WHERE taken_at = (
            SELECT MAX(taken_at) FROM top500_snapshots WHERE taken_at <= $1
        )
        ORDER BY rank
        """,
        at,
    )
