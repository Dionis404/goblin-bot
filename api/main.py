"""FastAPI: данные сообщества для сайта GoblinCodex."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared import db


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
    allow_methods=["GET"],
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
