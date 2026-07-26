"""
LP-лидерборд пула Uniswap v3 (Base) — топ-500 кошельков по value_usd.

Пайплайн:
  1. Забрать состояние пула (токены, decimals, sqrtPrice) из The Graph.
  2. Забрать все позиции с liquidity > 0 (курсорная пагинация по id).
  3. Конвертировать liquidity каждой позиции в token amounts (v3 tick math).
  4. Оценить каждую позицию в USD (предполагается, что одна сторона пула — USDC).
  5. Агрегировать по owner и записать топ-500 в lp_current / lp_meta.

Запуск:
  python -m jobs.lp_leaderboard
  или run_lp_leaderboard() из планировщика/cron.
"""
import logging
import math
import os
import sys
import time
from collections import defaultdict

import httpx

from shared import db, lp_leaderboard

log = logging.getLogger(__name__)

API_KEY = os.environ["GRAPH_API_KEY"]
SUBGRAPH_ID = os.environ["SUBGRAPH_ID"]
POOL = os.environ.get("POOL", "0xafe30319a948f322585fafc1cab1671a47eb3786").lower()

URL = f"https://gateway.thegraph.com/api/{API_KEY}/subgraphs/id/{SUBGRAPH_ID}"

TOP_N = 500
PAGE = 1000
Q96 = 2**96


# ---------------------------------------------------------------- GraphQL ---

def gql(query: str, variables: dict, retries: int = 5) -> dict:
    """POST GraphQL-запрос с ретраями и backoff (The Graph иногда флапает)."""
    for attempt in range(retries):
        try:
            r = httpx.post(URL, json={"query": query, "variables": variables},
                           timeout=30)
            r.raise_for_status()
            data = r.json()
            if "errors" in data:
                raise RuntimeError(data["errors"])
            return data["data"]
        except Exception as e:  # noqa: BLE001 - ретраим любую transient-ошибку
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("запрос упал (%s), ретрай через %sс...", e, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


POOL_QUERY = """
query ($pool: ID!) {
  pool(id: $pool) {
    sqrtPrice
    tick
    token0 { id symbol decimals }
    token1 { id symbol decimals }
  }
  _meta { block { number } }
}
"""

POSITIONS_QUERY = """
query ($pool: String!, $lastId: String!, $page: Int!) {
  positions(
    first: $page
    orderBy: id
    orderDirection: asc
    where: { pool: $pool, liquidity_gt: 0, id_gt: $lastId }
  ) {
    id
    owner
    liquidity
    tickLower { tickIdx }
    tickUpper { tickIdx }
  }
}
"""


def fetch_pool() -> tuple[dict, int]:
    data = gql(POOL_QUERY, {"pool": POOL})
    if data["pool"] is None:
        sys.exit(f"Пул {POOL} не найден в этом сабграфе — проверь SUBGRAPH_ID.")
    return data["pool"], int(data["_meta"]["block"]["number"])


def fetch_positions() -> list[dict]:
    out: list[dict] = []
    last_id = ""
    while True:
        data = gql(POSITIONS_QUERY,
                   {"pool": POOL, "lastId": last_id, "page": PAGE})
        batch = data["positions"]
        out.extend(batch)
        if len(batch) < PAGE:
            break
        last_id = batch[-1]["id"]
    return out


# ------------------------------------------------------------- v3 math ------

def sqrt_price_at_tick(tick: int) -> float:
    return math.sqrt(1.0001 ** tick)


def position_amounts(liquidity: int, tick_lower: int, tick_upper: int,
                     sp_current: float) -> tuple[float, float]:
    """Сырые (без учёта decimals) amounts token0 и token1."""
    sa = sqrt_price_at_tick(tick_lower)
    sb = sqrt_price_at_tick(tick_upper)
    L = float(liquidity)

    if sp_current <= sa:            # цена ниже диапазона: весь token0
        amount0 = L * (sb - sa) / (sa * sb)
        amount1 = 0.0
    elif sp_current >= sb:          # цена выше диапазона: весь token1
        amount0 = 0.0
        amount1 = L * (sb - sa)
    else:                           # в диапазоне
        amount0 = L * (sb - sp_current) / (sp_current * sb)
        amount1 = L * (sp_current - sa)
    return amount0, amount1


# --------------------------------------------------------------- расчёт -----

def build_leaderboard() -> tuple[list[dict], int, float]:
    """Возвращает (rows топ-N с rank, block, total_tvl, flower_price_usd)."""
    log.info("1/3 состояние пула...")
    pool, block = fetch_pool()
    t0, t1 = pool["token0"], pool["token1"]
    dec0, dec1 = int(t0["decimals"]), int(t1["decimals"])
    sp = int(pool["sqrtPrice"]) / Q96

    price0_in_1 = (sp * sp) * 10 ** (dec0 - dec1)
    log.info("пул: %s/%s  блок: %s  цена: 1 %s = %.6f %s",
              t0["symbol"], t1["symbol"], block, t0["symbol"], price0_in_1, t1["symbol"])

    if t1["symbol"].upper() in ("USDC", "USDBC", "USDT", "DAI"):
        usd_of = lambda a0, a1: a0 * price0_in_1 + a1          # noqa: E731
        token_price_usd = price0_in_1                          # цена token0 (напр. FLOWER)
    elif t0["symbol"].upper() in ("USDC", "USDBC", "USDT", "DAI"):
        usd_of = lambda a0, a1: a0 + a1 / price0_in_1          # noqa: E731
        token_price_usd = 1 / price0_in_1                      # цена token1 (напр. FLOWER)
    else:
        sys.exit("Ни одна сторона пула не стейбл — нужен внешний прайс-фид.")

    log.info("2/3 позиции...")
    positions = fetch_positions()
    log.info("всего активных позиций: %s", len(positions))

    log.info("3/3 расчёт и агрегация...")
    agg: dict[str, dict] = defaultdict(
        lambda: {"positions": 0, "amt0": 0.0, "amt1": 0.0})

    for p in positions:
        raw0, raw1 = position_amounts(
            int(p["liquidity"]),
            int(p["tickLower"]["tickIdx"]),
            int(p["tickUpper"]["tickIdx"]),
            sp,
        )
        a = agg[p["owner"].lower()]
        a["positions"] += 1
        a["amt0"] += raw0 / 10 ** dec0
        a["amt1"] += raw1 / 10 ** dec1

    rows = []
    for owner, a in agg.items():
        rows.append({
            "owner": owner,
            "positions": a["positions"],
            "value_usd": round(usd_of(a["amt0"], a["amt1"]), 2),
        })
    rows.sort(key=lambda r: r["value_usd"], reverse=True)

    total_tvl = sum(r["value_usd"] for r in rows)
    log.info("уникальных кошельков: %s  суммарный TVL: $%.0f", len(rows), total_tvl)

    top = rows[:TOP_N]
    for i, r in enumerate(top, 1):
        r["rank"] = i

    return top, block, total_tvl, token_price_usd


# ---------------------------------------------------------------- main ------

async def run_lp_leaderboard() -> dict:
    """Собирает лидерборд и записывает его в lp_current / lp_meta."""
    rows, block, total_tvl, flower_price_usd = build_leaderboard()

    pool = await db.get_pool()
    await lp_leaderboard.replace_leaderboard(
        pool,
        rows,
        block=block,
        flower_price_usd=flower_price_usd,
        total_tvl=total_tvl,
    )
    log.info("Готово: записано %s кошельков в lp_current (блок %s)", len(rows), block)
    return {"wallets": len(rows), "block": block, "total_tvl": total_tvl}


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        await run_lp_leaderboard()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
