"""Тесты для shared/farm_cache.py: refresh_farm и связанные сценарии."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from shared import farm_cache
from tests.fake_pool import FakePool, FakeRecord


SFL_PAYLOAD = {"id": 123, "farm": {"username": "goblin", "balance": "10", "coins": "5"}}


@pytest.mark.asyncio
async def test_first_refresh_creates_record():
    """(а) первое создание записи: строки ещё нет -> refresh_farm её создаёт и заполняет data."""
    pool = FakePool()

    with patch("shared.farm_cache._fetch_from_sfl", AsyncMock(return_value=SFL_PAYLOAD)):
        await farm_cache.refresh_farm(123, pool)

    row = await farm_cache.get_farm(pool, 123)
    assert row is not None
    assert row["data"] == SFL_PAYLOAD
    assert row["is_refreshing"] is False
    assert row["tracked"] is True


@pytest.mark.asyncio
async def test_stale_data_returned_immediately_and_refreshed_in_background():
    """(б) устаревшие данные возвращаются сразу, обновление не блокирует ответ."""
    pool = FakePool()
    old_data = {"id": 42, "farm": {"username": "old"}}
    stale_time = datetime.now(timezone.utc) - timedelta(hours=7)
    pool._rows[42] = FakeRecord(
        farm_id=42, data=old_data, updated_at=stale_time,
        is_refreshing=False, tracked=True,
        first_seen=stale_time, last_requested_at=stale_time,
    )

    assert farm_cache.is_stale(pool._rows[42]["updated_at"]) is True

    row = await farm_cache.get_farm(pool, 42)
    assert row["data"] == old_data  # старые данные доступны немедленно, до фонового обновления

    new_data = {"id": 42, "farm": {"username": "new"}}
    with patch("shared.farm_cache._fetch_from_sfl", AsyncMock(return_value=new_data)):
        await farm_cache.refresh_farm(42, pool)  # имитация фонового вызова

    refreshed = await farm_cache.get_farm(pool, 42)
    assert refreshed["data"] == new_data
    assert not farm_cache.is_stale(refreshed["updated_at"])


@pytest.mark.asyncio
async def test_external_api_error_keeps_old_data():
    """(в) ошибка внешнего API не должна затирать старые данные."""
    pool = FakePool()
    old_data = {"id": 7, "farm": {"username": "goblin"}}
    now = datetime.now(timezone.utc)
    pool._rows[7] = FakeRecord(
        farm_id=7, data=old_data, updated_at=now,
        is_refreshing=False, tracked=True,
        first_seen=now, last_requested_at=now,
    )

    with patch("shared.farm_cache._fetch_from_sfl", AsyncMock(side_effect=TimeoutError("boom"))):
        await farm_cache.refresh_farm(7, pool)

    row = await farm_cache.get_farm(pool, 7)
    assert row["data"] == old_data  # данные не потеряны
    assert row["is_refreshing"] is False  # флаг корректно сброшен


@pytest.mark.asyncio
async def test_refresh_skips_when_already_refreshing():
    """Повторный вызов refresh_farm не должен дублировать обновление той же фермы."""
    pool = FakePool()
    now = datetime.now(timezone.utc)
    pool._rows[9] = FakeRecord(
        farm_id=9, data=None, updated_at=now,
        is_refreshing=True, refresh_started_at=now, tracked=True,
        first_seen=now, last_requested_at=now,
    )

    fetch_mock = AsyncMock(return_value=SFL_PAYLOAD)
    with patch("shared.farm_cache._fetch_from_sfl", fetch_mock):
        await farm_cache.refresh_farm(9, pool)

    fetch_mock.assert_not_called()


@pytest.fixture(autouse=True)
def _reset_not_found_cache():
    farm_cache._not_found_until.clear()
    yield
    farm_cache._not_found_until.clear()


@pytest.mark.asyncio
async def test_stale_refresh_lock_is_taken_over():
    """Лок, зависший после рестарта процесса, протухает и не блокирует ферму навсегда."""
    pool = FakePool()
    long_ago = datetime.now(timezone.utc) - timedelta(seconds=farm_cache.REFRESH_LOCK_TIMEOUT_SEC + 60)
    pool._rows[11] = FakeRecord(
        farm_id=11, data={"old": True}, updated_at=long_ago,
        is_refreshing=True, refresh_started_at=long_ago, tracked=True,
        first_seen=long_ago, last_requested_at=long_ago,
    )

    with patch("shared.farm_cache._fetch_from_sfl", AsyncMock(return_value=SFL_PAYLOAD)):
        await farm_cache.refresh_farm(11, pool)

    row = await farm_cache.get_farm(pool, 11)
    assert row["data"] == SFL_PAYLOAD
    assert row["is_refreshing"] is False


@pytest.mark.asyncio
async def test_failed_first_refresh_leaves_no_placeholder():
    """Ошибка SFL при первом запросе не оставляет пустую строку в farm_cache."""
    pool = FakePool()

    with patch("shared.farm_cache._fetch_from_sfl", AsyncMock(side_effect=TimeoutError("boom"))):
        await farm_cache.refresh_farm(555, pool)

    assert await farm_cache.get_farm(pool, 555) is None


@pytest.mark.asyncio
async def test_not_found_farm_is_cached_and_not_requested_again():
    """404 от SFL попадает в отрицательный кэш — повторный refresh не ходит в API."""
    pool = FakePool()
    request = httpx.Request("GET", "https://example.com")
    not_found = httpx.HTTPStatusError(
        "404", request=request, response=httpx.Response(404, request=request)
    )
    fetch_mock = AsyncMock(side_effect=not_found)

    with patch("shared.farm_cache._fetch_from_sfl", fetch_mock):
        await farm_cache.refresh_farm(777, pool)
        await farm_cache.refresh_farm(777, pool)

    assert fetch_mock.await_count == 1
    assert farm_cache.is_known_missing(777)
    assert await farm_cache.get_farm(pool, 777) is None


@pytest.mark.asyncio
async def test_refresh_slots_are_limited_and_released():
    pool = FakePool()
    reserved = 0
    while farm_cache.reserve_refresh_slot():
        reserved += 1
    try:
        assert reserved == farm_cache.MAX_PENDING_REFRESHES
        with patch("shared.farm_cache._fetch_from_sfl", AsyncMock(return_value=SFL_PAYLOAD)):
            await farm_cache.refresh_farm_reserved(1, pool)
        assert farm_cache.reserve_refresh_slot()  # слот освободился
    finally:
        farm_cache._pending_refreshes = 0


@pytest.mark.asyncio
async def test_upsert_farm_data_creates_and_updates_without_lock():
    """upsert_farm_data пишет данные независимо от is_refreshing, в т.ч. для новой строки."""
    pool = FakePool()

    await farm_cache.upsert_farm_data(pool, 55, {"id": 55, "farm": {"balance": "1"}})
    row = await farm_cache.get_farm(pool, 55)
    assert row["data"] == {"id": 55, "farm": {"balance": "1"}}

    await farm_cache.upsert_farm_data(pool, 55, {"id": 55, "farm": {"balance": "2"}})
    row = await farm_cache.get_farm(pool, 55)
    assert row["data"] == {"id": 55, "farm": {"balance": "2"}}


def test_parse_farmer_stats_extracts_all_fields():
    farm_entry = {
        "id": 62559,
        "farm": {
            "username": "Dionis",
            "balance": "1250.421",
            "coins": 128350,
            "bumpkin": {"experience": 105300},
        },
    }
    stats = farm_cache.parse_farmer_stats(farm_entry)
    assert stats == {
        "game_username": "Dionis",
        "xp": 105300.0,
        "balance": 1250.421,
        "coins": 128350.0,
    }


def test_parse_farmer_stats_handles_missing_fields():
    stats = farm_cache.parse_farmer_stats({"id": 1, "farm": {}})
    assert stats == {"game_username": None, "xp": None, "balance": None, "coins": None}


@pytest.mark.asyncio
async def test_fetch_batch_from_sfl_normalizes_and_parses_ids():
    api_response = {"farms": {"121500": {"balance": "10"}}, "skipped": ["999"]}
    resp = AsyncMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: api_response
    client = AsyncMock()
    client.post.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.farm_cache.httpx.AsyncClient", return_value=client):
        farms, skipped = await farm_cache._fetch_batch_from_sfl([121500, 999])

    assert farms == {121500: {"id": 121500, "farm": {"balance": "10"}}}
    assert skipped == [999]


@pytest.mark.asyncio
async def test_fetch_batch_from_sfl_rejects_over_limit():
    with pytest.raises(ValueError):
        await farm_cache._fetch_batch_from_sfl(list(range(farm_cache.BATCH_MAX_IDS + 1)))
