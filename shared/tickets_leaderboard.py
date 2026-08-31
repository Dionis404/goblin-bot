"""Лидерборд тикетов SFL: топ-500 + точное место tracked-фермеров, экономно.

Источник — GET /community/data?type=ticketLeaderboard (требует x-api-key,
VIP+level50 на стороне игры). Старый /leaderboard/tickets/{farm_id} — legacy,
может быть отключён в любой момент. У community API строгий rate limit,
поэтому jobs/tickets_leaderboard.py минимизирует число запросов:

1. Топ-500 целиком (top500_snapshots) — один запрос в час через
   ?type=ticketLeaderboard&farmId={любой_farm_id}&limit=500. FarmID в query
   не влияет на список (борд общий), но обязателен по формату API — берём
   TOP500_QUERY_FARM_ID. Не зависит от tracked-фермеров, нужен для сайта/API.

2. Точное место tracked-фермера (ticket_leaderboard_snapshots) — для фермеров
   с farmers.tickets_tracked = true И tickets_excluded = false. Если ферма
   уже нашлась в топ-500 из пункта 1, её ранг берётся оттуда бесплатно, без
   отдельного запроса. Иначе — отдельный запрос, возвращающий
   farmRankingDetails (узкое окно вокруг точного ранга, работает на любом
   месте, хоть 29000+); omitted, если ферма уже в топ-10 (тогда берём ранг
   из topTen), null — если у фермы нет тикетов в этой главе.
   Снэпшот пишется, только если rank <= RANK_CUTOFF — питает еженедельный
   отчёт в группе. Если ранг (из любого источника) >= TICKETS_EXCLUDE_RANK,
   ферма помечается tickets_excluded и больше не запрашивается отдельно
   (но продолжает подхватываться бесплатно, если сама всплывёт в топ-500).
"""
import asyncio
import logging
from datetime import datetime, timezone

import asyncpg
import httpx

from shared import config

log = logging.getLogger(__name__)

RANK_CUTOFF = 1200
TIMEOUT = 10.0

# Если последний известный ранг фермы >= этого порога, она больше не
# запрашивается отдельным HTTP-запросом каждый час (farmers.tickets_excluded).
# Всё ещё подхватывается бесплатно, если сама всплывёт в топ-500.
TICKETS_EXCLUDE_RANK = 2000

TOP500_QUERY_FARM_ID = 1  # произвольный валидный farm_id, только чтобы собрать topTen с limit=500
TOP500_LIMIT = 500


class FarmRankNotFound(Exception):
    """Ферма не встретилась в ответе API (нет тикетов / не существует)."""


def _api_headers() -> dict:
    return {"x-api-key": config.SFL_API_KEY} if config.SFL_API_KEY else {}


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
    """GET с повторами при 429, уважая Retry-After (у community API строгий лимит)."""
    for attempt in range(1, config.API_MAX_RETRIES + 1):
        resp = await client.get(url, params=params, headers=_api_headers())
        if resp.status_code != 429:
            return resp

        retry_after = resp.headers.get("Retry-After")
        wait = (
            float(retry_after)
            if retry_after and retry_after.replace(".", "", 1).isdigit()
            else config.API_RETRY_BACKOFF * attempt
        )
        log.warning(
            "SFL community API 429 (tickets), попытка %s/%s, ждём %.1f с",
            attempt, config.API_MAX_RETRIES, wait,
        )
        await asyncio.sleep(wait)

    return resp


async def fetch_farm_rank(farm_id: int) -> dict:
    """
    Возвращает {"rank", "tickets", "game_username"} для конкретной фермы.

    Бросает FarmRankNotFound, если у фермы нет тикетов в этой главе
    (farmRankingDetails == null) или её не удалось найти в ответе.
    Если ферма уже в топ-10, farmRankingDetails в ответе отсутствует —
    тогда берём её место из topTen.
    """
    url = f"{config.SFL_API_BASE}/community/data"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await _get_with_retry(client, url, {"type": "ticketLeaderboard", "farmId": farm_id})
        if resp.status_code == 404:
            raise FarmRankNotFound(f"Ферма {farm_id} не найдена в лидерборде тикетов")
        resp.raise_for_status()
        data = resp.json()["data"]

    details = data.get("farmRankingDetails")
    if details is None:
        for i, entry in enumerate(data.get("topTen") or [], start=1):
            if entry.get("farmId") == farm_id:
                return {
                    "rank": i,
                    "tickets": entry["count"],
                    "game_username": entry.get("id"),
                }
        raise FarmRankNotFound(f"Ферма {farm_id} не крафтила тикетов в этой главе")

    for entry in details:
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


async def get_trackable_farm_ids(pool: asyncpg.Pool) -> list[int]:
    """
    Tracked-фермеры, которых ещё стоит опрашивать отдельным запросом —
    без тех, кого уже пометили tickets_excluded (последний известный ранг
    был >= TICKETS_EXCLUDE_RANK, дальше проверять бессмысленно).
    """
    rows = await pool.fetch(
        "SELECT farm_id FROM farmers WHERE tickets_tracked = true AND tickets_excluded = false"
    )
    return [r["farm_id"] for r in rows]


async def mark_excluded(pool: asyncpg.Pool, farm_id: int) -> None:
    """Навсегда исключить ферму из почасового опроса (см. TICKETS_EXCLUDE_RANK)."""
    await pool.execute(
        "UPDATE farmers SET tickets_excluded = true WHERE farm_id = $1", farm_id
    )


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


# --- Топ-500 целиком (top500_snapshots) ---

async def fetch_top500() -> list[dict]:
    """Возвращает топ-500 [{"rank", "farm_id", "game_username", "tickets"}, ...]."""
    url = f"{config.SFL_API_BASE}/community/data"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await _get_with_retry(
            client,
            url,
            {"type": "ticketLeaderboard", "farmId": TOP500_QUERY_FARM_ID, "limit": TOP500_LIMIT},
        )
        resp.raise_for_status()
        data = resp.json()["data"]

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
