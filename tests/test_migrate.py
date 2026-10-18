"""Тесты для shared/migrate.py: учёт миграций, baseline, откат упавшей."""
from contextlib import asynccontextmanager

import pytest

from shared import migrate


class FakeConn:
    """Фейк asyncpg.Connection: помнит таблицу учёта миграций и выполненные SQL."""

    def __init__(self, farmers_exists: bool, fail_on: str | None = None):
        self.farmers_exists = farmers_exists
        self.fail_on = fail_on
        self.applied: list[str] = []
        self.executed_sql: list[str] = []
        self.locked = False
        self._tx_pending: list[str] | None = None

    async def execute(self, sql: str, *args):
        if "pg_advisory_lock" in sql:
            self.locked = True
        elif "pg_advisory_unlock" in sql:
            self.locked = False
        elif sql.startswith(f"INSERT INTO {migrate.MIGRATIONS_TABLE}"):
            target = self._tx_pending if self._tx_pending is not None else self.applied
            target.append(args[0])
        elif f"CREATE TABLE IF NOT EXISTS {migrate.MIGRATIONS_TABLE}" in sql:
            pass
        else:
            if self.fail_on and self.fail_on in sql:
                raise RuntimeError("syntax error")
            self.executed_sql.append(sql)

    async def executemany(self, sql: str, rows):
        self.applied.extend(r[0] for r in rows)

    async def fetch(self, sql: str):
        return [{"name": n} for n in self.applied]

    async def fetchval(self, sql: str):
        return "farmers" if self.farmers_exists else None

    @asynccontextmanager
    async def _transaction(self):
        self._tx_pending = []
        try:
            yield
        except Exception:
            self._tx_pending = None  # откат: запись о миграции не сохраняется
            raise
        self.applied.extend(self._tx_pending)
        self._tx_pending = None

    def transaction(self):
        return self._transaction()


@pytest.fixture
def migrations_dir(tmp_path):
    for name, sql in [
        ("001_farmers.sql", "CREATE TABLE farmers ();"),
        ("011_tickets_excluded.sql", "ALTER TABLE farmers ADD x;"),
        ("012_new.sql", "ALTER TABLE farm_cache ADD y;"),
        ("013_newer.sql", "CREATE TABLE z ();"),
    ]:
        (tmp_path / name).write_text(sql, encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_existing_db_baselines_old_migrations_and_applies_new(migrations_dir):
    conn = FakeConn(farmers_exists=True)

    applied = await migrate.apply_migrations(conn, migrations_dir)

    assert applied == ["012_new.sql", "013_newer.sql"]
    assert conn.executed_sql == ["ALTER TABLE farm_cache ADD y;", "CREATE TABLE z ();"]
    assert set(conn.applied) == {"001_farmers.sql", "011_tickets_excluded.sql", "012_new.sql", "013_newer.sql"}
    assert conn.locked is False  # лок отпущен


@pytest.mark.asyncio
async def test_fresh_db_applies_everything(migrations_dir):
    conn = FakeConn(farmers_exists=False)

    applied = await migrate.apply_migrations(conn, migrations_dir)

    assert applied == ["001_farmers.sql", "011_tickets_excluded.sql", "012_new.sql", "013_newer.sql"]


@pytest.mark.asyncio
async def test_second_run_is_noop(migrations_dir):
    conn = FakeConn(farmers_exists=True)
    await migrate.apply_migrations(conn, migrations_dir)
    conn.executed_sql.clear()

    assert await migrate.apply_migrations(conn, migrations_dir) == []
    assert conn.executed_sql == []


@pytest.mark.asyncio
async def test_failed_migration_is_not_recorded_and_stops_the_run(migrations_dir):
    conn = FakeConn(farmers_exists=True, fail_on="farm_cache")

    with pytest.raises(RuntimeError):
        await migrate.apply_migrations(conn, migrations_dir)

    assert "012_new.sql" not in conn.applied
    assert "013_newer.sql" not in conn.applied  # следующие не применялись
    assert conn.locked is False


def test_real_migrations_include_baseline():
    names = [p.name for p in migrate.list_migrations()]
    assert migrate.BASELINE in names
    assert names == sorted(names)


def test_migrations_table_does_not_clash_with_other_services():
    """В общей БД sfl schema_migrations уже занята другим сервисом."""
    assert migrate.MIGRATIONS_TABLE != "schema_migrations"
    assert migrate.MIGRATIONS_TABLE in migrate.CREATE_TABLE_SQL
