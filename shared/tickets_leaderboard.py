"""Лидерборд тикетов SFL: два независимых источника снэпшотов.

1. Топ-500 целиком (top500_snapshots) — почасовой снимок всего глобального
   борда через /leaderboard/tickets/{любой_farm_id}?limit=500. FarmID в пути
   не влияет на список (борд общий), но обязателен по формату API — берём
   TOP500_QUERY_FARM_ID. Не зависит от tracked-фермеров, нужен для сайта/API.

2. Точное место tracked-фермера (ticket_leaderboard_snapshots) — для фермеров
   с farmers.tickets_tracked = true. Запрос без limit возвращает
   farmRankingDetails — узкое окно вокруг точного ранга запрошенной фермы
   (работает на любом месте, хоть 29000+), поэтому на каждую отслеживаемую
   ферму достаточно одного лёгкого запроса в час. Пишется только если
   rank <= RANK_CUTOFF — питает еженедельный отчёт в группе.
"""
import logging
from datetime import datetime, timezone

import asyncpg
import httpx

from shared import config

log = logging.getLogger(__name__)

RANK_CUTOFF = 1200
TIMEOUT = 10.0

TOP500_QUERY_FARM_ID = 1  # произвольный валидный farm_id, только чтобы собрать topTen с limit=500
TOP500_LIMIT = 500


class FarmRankNotFound(Exception):
    """Ферма не встретилась в ответе API (нет тикетов / не существует)."""


async def fetch_farm_rank(farm_id: int) -> dict:
    """
    Возвращает {"rank", "tickets", "game_username"} для конкретной фермы.
    Бросает FarmRankNotFound, если фермы нет в farmRankingDetails ответа.
    """
    url = f"{config.SFL_API_BASE}/leaderboard/tickets/{farm_id}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            raise FarmRankNotFound(f"Ферма {farm_id} не найдена в лидерборде тикетов")
        resp.raise_for_status()
        data = resp.json()

    for entry in data.get("farmRankingDetails") or []:
        if entry.get("farmId") == farm_id:
            return {
                "rank": entry["rank"],
                "tickets": entry["count"],
                "game_username": entry.get("id"),
            }

    raise FarmRankNotFound(f"Ферма {farm_id} отсутствует в farmRankingDetails")


async def save_snapshot(
    pool: asyncpg.Pool, farm_id: int, rank: int, tickets: int, game_username: str | None
) -> None:
    await pool.execute(
        """
        INSERT INTO ticket_leaderboard_snapshots (farm_id, rank, tickets, game_username, taken_at)
        VALUES ($1, $2, $3, $4, now())
        """,
        farm_id, rank, tickets, game_username,
    )


async def get_tracked_farm_ids(pool: asyncpg.Pool) -> list[int]:
    rows = await pool.fetch("SELECT farm_id FROM farmers WHERE tickets_tracked = true")
    return [r["farm_id"] for r in rows]


async def get_tracked_farmers(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Отслеживаемые фермеры (farm_id + telegram_username) для еженедельного уведомления."""
    return await pool.fetch(
        "SELECT farm_id, telegram_username FROM farmers WHERE tickets_tracked = true"
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


# --- Топ-500 целиком (top500_snapshots) ---

async def fetch_top500() -> list[dict]:
    """Возвращает топ-500 [{"rank", "farm_id", "game_username", "tickets"}, ...]."""
    url = f"{config.SFL_API_BASE}/leaderboard/tickets/{TOP500_QUERY_FARM_ID}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url, params={"limit": TOP500_LIMIT})
        resp.raise_for_status()
        data = resp.json()

    entries = data.get("topTen") or []
    return [
        {
            "rank": i,
            "farm_id": entry["farmId"],
            "game_username": entry.get("id"),
            "tickets": entry["count"],
        }
        for i, entry in enumerate(entries, start=1)
    ]


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


async def save_top500_snapshot(pool: asyncpg.Pool, rows: list[dict]) -> None:
    now = datetime.now(timezone.utc)
    await pool.executemany(
        """
        INSERT INTO top500_snapshots (rank, farm_id, game_username, tickets, taken_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        [(r["rank"], r["farm_id"], r["game_username"], r["tickets"], now) for r in rows],
    )
