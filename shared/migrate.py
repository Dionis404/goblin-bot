"""
Автоприменение SQL-миграций из migrations/ (по порядку имён файлов).

Запуск: python -m shared.migrate — в docker-compose это отдельный
одноразовый сервис `migrate`, после успешного завершения которого
стартуют goblin-bot и goblin-api (depends_on: service_completed_successfully).
Упала миграция — бот и API не стартуют со схемой, не совпадающей с кодом.

- Применённые миграции учитываются в таблице schema_migrations.
- Каждая миграция — в своей транзакции: упавшая откатывается целиком и
  не записывается, следующие не применяются.
- pg_advisory_lock не даёт двум процессам применять миграции одновременно.
- Baseline: до появления раннера миграции 001–BASELINE применялись руками.
  Если schema_migrations пуста, а таблица farmers уже есть — это та самая
  существующая БД, и 001–BASELINE помечаются применёнными без выполнения.
"""
import asyncio
import logging
from pathlib import Path

import asyncpg

from shared import config

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Последняя миграция, применённая вручную до появления раннера
BASELINE = "011_tickets_excluded.sql"

# Произвольный, но постоянный ключ advisory-лока миграций goblin-bot
ADVISORY_LOCK_KEY = 0x60B11

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def list_migrations(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"), key=lambda p: p.name)


async def apply_migrations(conn: asyncpg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Применяет недостающие миграции, возвращает имена применённых (без baseline)."""
    await conn.execute("SELECT pg_advisory_lock($1)", ADVISORY_LOCK_KEY)
    try:
        await conn.execute(CREATE_TABLE_SQL)
        applied = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
        migrations = list_migrations(directory)

        if not applied and await conn.fetchval("SELECT to_regclass('farmers')") is not None:
            baseline = [p.name for p in migrations if p.name <= BASELINE]
            await conn.executemany(
                "INSERT INTO schema_migrations (name) VALUES ($1)", [(n,) for n in baseline]
            )
            applied.update(baseline)
            log.info("Существующая БД: %s миграций до %s помечены применёнными", len(baseline), BASELINE)

        newly_applied = []
        for path in migrations:
            if path.name in applied:
                continue
            log.info("Применяю миграцию %s", path.name)
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", path.name)
            newly_applied.append(path.name)

        if not newly_applied:
            log.info("Новых миграций нет")
        return newly_applied
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_KEY)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    conn = await asyncpg.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )
    try:
        await apply_migrations(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
