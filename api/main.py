"""FastAPI: данные сообщества для сайта GoblinCodex."""
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared import db, farm_cache


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

    result = {}
    for fid in farm_ids:
        row = by_id.get(fid)
        if row is None:
            result[fid] = None
            continue
        if farm_cache.is_stale(row["updated_at"]):
            background_tasks.add_task(farm_cache.refresh_farm, fid, pool)
        result[fid] = row["data"]
        await farm_cache.touch_last_requested(pool, fid)

    return result


@app.post("/farm/{farm_id}/refresh")
async def force_refresh_farm(farm_id: int, background_tasks: BackgroundTasks):
    pool = await db.get_pool()
    await farm_cache.ensure_placeholder(pool, farm_id)
    background_tasks.add_task(farm_cache.refresh_farm, farm_id, pool)
    return {"status": "refreshing"}
