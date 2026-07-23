"""
Мини-фейк asyncpg.Pool для юнит-тестов farm_cache без реальной БД.
Понимает только те запросы, что использует shared/farm_cache.py.
"""
import re
from datetime import datetime, timezone


class FakeRecord(dict):
    """asyncpg.Record ведёт себя как dict с доступом по ключу."""


class FakePool:
    def __init__(self):
        self._rows: dict[int, FakeRecord] = {}

    def _row(self, farm_id: int) -> FakeRecord | None:
        return self._rows.get(farm_id)

    async def fetchrow(self, query: str, *args):
        query = query.strip()
        if "WHERE farm_id = $1" in query and "farm_cache" in query:
            return self._row(args[0])
        raise NotImplementedError(query)

    async def fetch(self, query: str, *args):
        if "farm_id = ANY($1" in query:
            ids = args[0]
            return [self._rows[i] for i in ids if i in self._rows]
        if "WHERE tracked = true" in query:
            return [FakeRecord(farm_id=fid) for fid, r in self._rows.items() if r["tracked"]]
        raise NotImplementedError(query)

    async def execute(self, query: str, *args):
        query = query.strip()
        if query.startswith("UPDATE farm_cache SET last_requested_at"):
            farm_id = args[0]
            if farm_id in self._rows:
                self._rows[farm_id]["last_requested_at"] = _now()
            return
        if "INSERT INTO farm_cache" in query and "ON CONFLICT (farm_id) DO NOTHING" in query:
            farm_id, data = args
            if farm_id not in self._rows:
                self._rows[farm_id] = FakeRecord(
                    farm_id=farm_id, data=data, updated_at=_now(),
                    is_refreshing=False, tracked=True, first_seen=_now(),
                    last_requested_at=_now(),
                )
            return
        if query.startswith("UPDATE farm_cache SET is_refreshing = false"):
            farm_id = args[0]
            self._rows[farm_id]["is_refreshing"] = False
            return
        if query.startswith("UPDATE farm_cache") and "SET data = $2" in query:
            farm_id, data = args
            row = self._rows[farm_id]
            row["data"] = data
            row["updated_at"] = _now()
            row["is_refreshing"] = False
            return
        raise NotImplementedError(query)

    async def fetchval(self, query: str, *args):
        if "INSERT INTO farm_cache" in query and "is_refreshing" in query and "RETURNING farm_id" in query:
            farm_id, data = args
            existing = self._rows.get(farm_id)
            if existing is None:
                self._rows[farm_id] = FakeRecord(
                    farm_id=farm_id, data=data, updated_at=_now(),
                    is_refreshing=True, tracked=True, first_seen=_now(),
                    last_requested_at=_now(),
                )
                return farm_id
            if existing["is_refreshing"]:
                return None
            existing["is_refreshing"] = True
            return farm_id
        raise NotImplementedError(query)


def _now():
    return datetime.now(timezone.utc)
