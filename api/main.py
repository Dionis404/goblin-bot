"""FastAPI: данные сообщества для сайта GoblinCodex."""
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from shared import auctions, db, farm_cache, lp_leaderboard, telegram_posts, tickets_leaderboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.get_pool()
    yield
    await db.close_pool()


app = FastAPI(title="GoblinCodex Community API", lifespan=lifespan)

# Сайт ходит с goblincodex.fun; на этапе разработки можно "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/community/farmers")
async def get_farmers():
    """Список привязанных фермеров для страницы сообщества."""
    rows = await db.list_farmers()
    return [
        {
            "farm_id": r["farm_id"],
            "game_username": r["game_username"],
            "telegram_username": r["telegram_username"],
            "xp": float(r["xp"]) if r["xp"] is not None else None,
            "balance": float(r["balance"]) if r["balance"] is not None else None,
            "coins": float(r["coins"]) if r["coins"] is not None else None,
            "farm_url": r["farm_url"],
        }
        for r in rows
    ]


# --- Кэш ферм (farm_cache) ---

@app.get("/farm/{farm_id}")
async def get_farm(farm_id: int, background_tasks: BackgroundTasks):
    pool = await db.get_pool()
    row = await farm_cache.get_farm(pool, farm_id)

    if row is None:
        # Первое обращение: единственный раз ждём внешний API синхронно.
        await farm_cache.ensure_placeholder(pool, farm_id)
        await farm_cache.refresh_farm(farm_id, pool)
        row = await farm_cache.get_farm(pool, farm_id)
        await farm_cache.touch_last_requested(pool, farm_id)
        return row["data"]

    await farm_cache.touch_last_requested(pool, farm_id)
    if farm_cache.is_stale(row["updated_at"]):
        background_tasks.add_task(farm_cache.refresh_farm, farm_id, pool)
    return row["data"]


@app.get("/farms")
async def get_farms(ids: str, background_tasks: BackgroundTasks):
    try:
        farm_ids = sorted({int(x) for x in ids.split(",") if x.strip()})
    except ValueError:
        raise HTTPException(status_code=400, detail="ids должен быть списком чисел через запятую")
    if not farm_ids:
        return {}

    pool = await db.get_pool()
    rows = await farm_cache.get_farms(pool, farm_ids)
    by_id = {r["farm_id"]: r for r in rows}

    missing_ids = [fid for fid in farm_ids if fid not in by_id]
    for fid in missing_ids:
        await farm_cache.ensure_placeholder(pool, fid)
        background_tasks.add_task(farm_cache.refresh_farm, fid, pool)

    def serialize(fid: int):
        row = by_id.get(fid)
        if row is None or row["data"] is None:
            return None
        return {
            "data": row["data"],
            "updated_at": row["updated_at"].isoformat(),
        }

    result = {}
    for fid in farm_ids:
        row = by_id.get(fid)
        if row is not None and farm_cache.is_stale(row["updated_at"]):
            background_tasks.add_task(farm_cache.refresh_farm, fid, pool)
        result[str(fid)] = serialize(fid)
        await farm_cache.touch_last_requested(pool, fid)

    return result


@app.post("/farm/{farm_id}/refresh")
async def force_refresh_farm(farm_id: int, background_tasks: BackgroundTasks):
    pool = await db.get_pool()
    await farm_cache.ensure_placeholder(pool, farm_id)
    background_tasks.add_task(farm_cache.refresh_farm, farm_id, pool)
    return {"status": "refreshing"}


# --- Посты канала @URGSFL (telegram_posts) ---

@app.get("/api/community/posts/{post_id}/image")
async def get_post_image(post_id: int):
    row = await telegram_posts.get_post_image(post_id)
    if row is None or row["image_data"] is None:
        raise HTTPException(status_code=404, detail="Картинка не найдена")

    return Response(
        content=row["image_data"],
        media_type=row["image_content_type"] or "image/jpeg",
    )


# --- LP-лидерборд (lp_current / lp_meta) ---

@app.get("/lp/leaderboard")
async def get_lp_leaderboard():
    """Топ-500 LP-провайдеров пула FLOWER/USDC + метаданные последнего обновления."""
    pool = await db.get_pool()
    rows = await lp_leaderboard.get_leaderboard(pool)
    meta = await lp_leaderboard.get_meta(pool)

    return {
        "meta": {
            "updated_at": meta["updated_at"] if meta else None,
            "block": meta["block"] if meta else None,
            "flower_price_usd": float(meta["flower_price_usd"]) if meta and meta["flower_price_usd"] is not None else None,
            "total_tvl": float(meta["total_tvl"]) if meta and meta["total_tvl"] is not None else None,
            "wallets": meta["wallets"] if meta else None,
        },
        "leaderboard": [
            {
                "owner": r["owner"],
                "rank": r["rank"],
                "prev_rank": r["prev_rank"],
                "value_usd": float(r["value_usd"]) if r["value_usd"] is not None else None,
                "positions": r["positions"],
                "farm_id": r["farm_id"],
            }
            for r in rows
        ],
    }


# --- Лидерборд тикетов (top500_snapshots) ---

@app.get("/api/tickets/top500")
async def get_tickets_top500(at: datetime | None = None):
    """
    Снэпшот глобального топ-500 лидерборда тикетов.

    Без параметра `at` — последний собранный снэпшот.
    С `at` (ISO 8601, например 2026-08-25T03:00:00Z) — снэпшот, ближайший
    к этому моменту, но не позже него ("как выглядел борд N часов/дней назад").
    """
    pool = await db.get_pool()
    rows = (
        await tickets_leaderboard.get_top500_at(pool, at)
        if at is not None
        else await tickets_leaderboard.get_latest_top500(pool)
    )

    return {
        "updated_at": rows[0]["taken_at"].isoformat() if rows else None,
        "leaderboard": [
            {
                "rank": r["rank"],
                "farm_id": r["farm_id"],
                "game_username": r["game_username"],
                "tickets": r["tickets"],
            }
            for r in rows
        ],
    }


# --- Аукционы (auctions / auction_results) — read-only, пишет auctioneer-bot ---

@app.get("/api/auctions")
async def get_auctions(upcoming: bool = False):
    if not upcoming:
        raise HTTPException(status_code=400, detail="Поддерживается только upcoming=true")

    pool = await db.get_pool()
    rows = await auctions.list_upcoming(pool)
    return [
        {
            "auction_id": r["auction_id"],
            "item_name": r["item_name"],
            "item_type": r["item_type"],
            "supply": r["supply"],
            "sfl_price": float(r["sfl_price"]) if r["sfl_price"] is not None else None,
            "ingredients": r["ingredients"],
            "start_at": r["start_at"],
            "end_at": r["end_at"],
        }
        for r in rows
    ]


@app.get("/api/auctions/{auction_id}/results")
async def get_auction_results(auction_id: str):
    pool = await db.get_pool()
    row = await auctions.get_results(pool, auction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Результаты аукциона ещё не готовы")

    return {
        "my_status": row["my_status"],
        "participant_count": row["participant_count"],
        "supply": row["supply"],
        "leaderboard": row["leaderboard"],
    }
