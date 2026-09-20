"""Тесты для shared/farm_cache.py: refresh_farm, refresh_farms_batch и связанные сценарии."""
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


def _make_row(farm_id: int, tracked: bool = True) -> FakeRecord:
    now = datetime.now(timezone.utc)
    return FakeRecord(
        farm_id=farm_id, data=None, updated_at=now,
        is_refreshing=False, tracked=tracked,
        first_seen=now, last_requested_at=now,
    )


@pytest.mark.asyncio
async def test_refresh_farms_batch_normalizes_response_shape():
    """getFarms отдаёт farms[id] без обёртки — должно нормализоваться в {"id", "farm"}."""
    pool = FakePool()
    pool._rows[121500] = _make_row(121500)
    pool._rows[121501] = _make_row(121501)

    api_response = {
        "farms": {
            "121500": {"balance": "10", "coins": 5},
            "121501": {"balance": "20", "coins": 8},
        },
        "skipped": [],
    }
    resp = AsyncMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: api_response
    client = AsyncMock()
    client.post.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.farm_cache.httpx.AsyncClient", return_value=client):
        result = await farm_cache.refresh_farms_batch([121500, 121501], pool)

    assert result == {"succeeded": 2, "skipped": 0, "failed": 0}
    row = await farm_cache.get_farm(pool, 121500)
    assert row["data"] == {"id": 121500, "farm": {"balance": "10", "coins": 5}}


@pytest.mark.asyncio
async def test_refresh_farms_batch_marks_api_skipped_ids():
    """Ферма, отсутствующая в ответе (API skipped), учитывается отдельно и не ломает остальных."""
    pool = FakePool()
    pool._rows[1] = _make_row(1)
    pool._rows[2] = _make_row(2)

    api_response = {"farms": {"1": {"balance": "10"}}, "skipped": [2]}
    resp = AsyncMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: api_response
    client = AsyncMock()
    client.post.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.farm_cache.httpx.AsyncClient", return_value=client):
        result = await farm_cache.refresh_farms_batch([1, 2], pool)

    assert result == {"succeeded": 1, "skipped": 1, "failed": 0}
    assert pool._rows[2]["is_refreshing"] is False
    assert pool._rows[2]["data"] is None  # старые данные (их и не было) не тронуты


@pytest.mark.asyncio
async def test_refresh_farms_batch_keeps_old_data_on_api_error():
    """Ошибка внешнего API на весь batch не должна затирать данные и виснуть на is_refreshing."""
    pool = FakePool()
    old_data = {"id": 5, "farm": {"username": "goblin"}}
    pool._rows[5] = FakeRecord(
        farm_id=5, data=old_data, updated_at=datetime.now(timezone.utc),
        is_refreshing=False, tracked=True,
        first_seen=datetime.now(timezone.utc), last_requested_at=datetime.now(timezone.utc),
    )

    with patch(
        "shared.farm_cache._fetch_batch_from_sfl", AsyncMock(side_effect=TimeoutError("boom"))
    ):
        result = await farm_cache.refresh_farms_batch([5], pool)

    assert result == {"succeeded": 0, "skipped": 0, "failed": 1}
    row = await farm_cache.get_farm(pool, 5)
    assert row["data"] == old_data
    assert row["is_refreshing"] is False


@pytest.mark.asyncio
async def test_refresh_farms_batch_splits_into_chunks_of_100(monkeypatch):
    """Список больше BATCH_MAX_IDS должен уйти несколькими batch-запросами."""
    pool = FakePool()
    farm_ids = list(range(1, 151))  # 150 ферм -> 2 запроса (100 + 50)
    for fid in farm_ids:
        pool._rows[fid] = _make_row(fid)

    fetch_mock = AsyncMock(
        side_effect=lambda ids: ({fid: {"id": fid, "farm": {}} for fid in ids}, [])
    )
    with patch("shared.farm_cache._fetch_batch_from_sfl", fetch_mock):
        result = await farm_cache.refresh_farms_batch(farm_ids, pool)

    assert result == {"succeeded": 150, "skipped": 0, "failed": 0}
    assert fetch_mock.await_count == 2
    call_sizes = sorted(len(c.args[0]) for c in fetch_mock.await_args_list)
    assert call_sizes == [50, 100]


@pytest.mark.asyncio
async def test_refresh_farms_batch_skips_farm_already_refreshing():
    """Ферма с is_refreshing=true не должна попасть в batch-запрос."""
    pool = FakePool()
    pool._rows[1] = _make_row(1)
    pool._rows[2] = FakeRecord(
        farm_id=2, data=None, updated_at=datetime.now(timezone.utc),
        is_refreshing=True, tracked=True,
        first_seen=datetime.now(timezone.utc), last_requested_at=datetime.now(timezone.utc),
    )

    fetch_mock = AsyncMock(return_value=({1: {"id": 1, "farm": {}}}, []))
    with patch("shared.farm_cache._fetch_batch_from_sfl", fetch_mock):
        result = await farm_cache.refresh_farms_batch([1, 2], pool)

    fetch_mock.assert_awaited_once_with([1])
    assert result == {"succeeded": 1, "skipped": 0, "failed": 0}


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
