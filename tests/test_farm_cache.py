"""Тесты для shared/farm_cache.py: refresh_farm и связанные сценарии."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

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
        is_refreshing=True, tracked=True,
        first_seen=now, last_requested_at=now,
    )

    fetch_mock = AsyncMock(return_value=SFL_PAYLOAD)
    with patch("shared.farm_cache._fetch_from_sfl", fetch_mock):
        await farm_cache.refresh_farm(9, pool)

    fetch_mock.assert_not_called()
