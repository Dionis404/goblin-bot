"""Тесты для api/main.py: валидация входа и защита SFL API-ключа от перебора."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import FARMS_MAX_IDS, app
from shared import farm_cache
from tests.fake_pool import FakePool, FakeRecord


@pytest.fixture
def pool():
    pool = FakePool()
    farm_cache._not_found_until.clear()
    farm_cache._pending_refreshes = 0
    # Без `with TestClient(...)` lifespan не запускается — реальная БД не нужна
    with patch("api.main.db.get_pool", AsyncMock(return_value=pool)):
        yield pool
    farm_cache._not_found_until.clear()
    farm_cache._pending_refreshes = 0


@pytest.fixture
def client(pool):
    return TestClient(app)


def test_farms_rejects_too_many_ids(client):
    ids = ",".join(str(i) for i in range(1, FARMS_MAX_IDS + 2))
    resp = client.get(f"/farms?ids={ids}")
    assert resp.status_code == 400


@pytest.mark.parametrize("bad_id", ["0", "-5", str(2**63)])
def test_farms_rejects_out_of_range_ids(client, bad_id):
    resp = client.get(f"/farms?ids=1,{bad_id}")
    assert resp.status_code == 400


@pytest.mark.parametrize("bad_id", ["0", "-5", str(2**63)])
def test_farm_rejects_out_of_range_id(client, bad_id):
    assert client.get(f"/farm/{bad_id}").status_code == 422


def test_farms_does_not_create_placeholders_for_unknown_ids(client, pool):
    with patch("shared.farm_cache._fetch_from_sfl", AsyncMock(side_effect=TimeoutError("boom"))):
        resp = client.get("/farms?ids=101,102")

    assert resp.status_code == 200
    assert resp.json() == {"101": None, "102": None}
    assert pool._rows == {}  # мусорных строк в farm_cache не осталось


def test_known_missing_farm_is_not_requested(client):
    farm_cache._mark_missing(404404)
    fetch = AsyncMock()
    with patch("shared.farm_cache._fetch_from_sfl", fetch):
        resp = client.get("/farm/404404")

    assert resp.status_code == 200
    assert resp.json() is None
    fetch.assert_not_called()


def test_force_refresh_skips_fresh_data(client, pool):
    now = datetime.now(timezone.utc)
    pool._rows[5] = FakeRecord(
        farm_id=5, data={"x": 1}, updated_at=now, is_refreshing=False,
        tracked=True, first_seen=now, last_requested_at=now,
    )
    fetch = AsyncMock()
    with patch("shared.farm_cache._fetch_from_sfl", fetch):
        resp = client.post("/farm/5/refresh")

    assert resp.json() == {"status": "fresh"}
    fetch.assert_not_called()


@pytest.mark.parametrize("limit", ["0", "-1", "101"])
def test_auctions_limit_is_bounded(client, limit):
    assert client.get(f"/api/auctions?history=true&limit={limit}").status_code == 422


def test_first_hit_does_not_wait_behind_busy_queue(client, pool):
    """Очередь к SFL не пуста — первый запрос не ждёт её синхронно, обновление уходит в фон."""
    farm_cache._pending_refreshes = 1  # кто-то уже ждёт свой запрос к SFL
    fetch = AsyncMock(return_value={"id": 9, "farm": {}})
    with patch("shared.farm_cache._fetch_from_sfl", fetch):
        resp = client.get("/farm/9")

    assert resp.status_code == 200
    assert resp.json() is None  # данных пока нет, но и ожидания тоже
    # TestClient выполняет фоновые задачи после ответа — ферма обновилась
    assert pool._rows[9]["data"] == {"id": 9, "farm": {}}
