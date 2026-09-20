"""Тесты для jobs/daily_refresh.py: обновление статов фермеров сообщества."""
from unittest.mock import AsyncMock, patch

import pytest

from jobs.daily_refresh import run_daily_refresh


@pytest.mark.asyncio
async def test_updates_farmers_and_farm_cache_from_batch_response():
    pool = object()
    farm_entry = {"id": 1, "farm": {"username": "Dionis", "balance": "10", "coins": 5}}

    with patch("jobs.daily_refresh.db.get_pool", AsyncMock(return_value=pool)), \
         patch("jobs.daily_refresh.db.list_farmer_farm_ids", AsyncMock(return_value=[1])), \
         patch(
             "jobs.daily_refresh.farm_cache._fetch_batch_from_sfl",
             AsyncMock(return_value=({1: farm_entry}, [])),
         ), \
         patch("jobs.daily_refresh.db.update_farmer_stats", AsyncMock()) as mock_update_farmer, \
         patch("jobs.daily_refresh.farm_cache.upsert_farm_data", AsyncMock()) as mock_upsert_cache:
        result = await run_daily_refresh()

    mock_update_farmer.assert_awaited_once_with(1, "Dionis", None, 10.0, 5.0)
    mock_upsert_cache.assert_awaited_once_with(pool, 1, farm_entry)
    assert result == {"succeeded": 1, "skipped": 0, "failed": 0}


@pytest.mark.asyncio
async def test_api_skipped_farmer_is_not_written_anywhere():
    pool = object()

    with patch("jobs.daily_refresh.db.get_pool", AsyncMock(return_value=pool)), \
         patch("jobs.daily_refresh.db.list_farmer_farm_ids", AsyncMock(return_value=[1, 2])), \
         patch(
             "jobs.daily_refresh.farm_cache._fetch_batch_from_sfl",
             AsyncMock(return_value=({1: {"id": 1, "farm": {}}}, [2])),
         ), \
         patch("jobs.daily_refresh.db.update_farmer_stats", AsyncMock()) as mock_update_farmer, \
         patch("jobs.daily_refresh.farm_cache.upsert_farm_data", AsyncMock()) as mock_upsert_cache:
        result = await run_daily_refresh()

    mock_update_farmer.assert_awaited_once()  # только farm_id=1, не 2
    mock_upsert_cache.assert_awaited_once()
    assert result == {"succeeded": 1, "skipped": 1, "failed": 0}


@pytest.mark.asyncio
async def test_batch_http_error_marks_whole_chunk_failed():
    pool = object()

    with patch("jobs.daily_refresh.db.get_pool", AsyncMock(return_value=pool)), \
         patch("jobs.daily_refresh.db.list_farmer_farm_ids", AsyncMock(return_value=[1, 2, 3])), \
         patch(
             "jobs.daily_refresh.farm_cache._fetch_batch_from_sfl",
             AsyncMock(side_effect=TimeoutError("boom")),
         ), \
         patch("jobs.daily_refresh.db.update_farmer_stats", AsyncMock()) as mock_update_farmer:
        result = await run_daily_refresh()

    mock_update_farmer.assert_not_called()
    assert result == {"succeeded": 0, "skipped": 0, "failed": 3}


@pytest.mark.asyncio
async def test_no_farmers_does_nothing():
    pool = object()

    with patch("jobs.daily_refresh.db.get_pool", AsyncMock(return_value=pool)), \
         patch("jobs.daily_refresh.db.list_farmer_farm_ids", AsyncMock(return_value=[])), \
         patch("jobs.daily_refresh.farm_cache._fetch_batch_from_sfl", AsyncMock()) as mock_fetch:
        result = await run_daily_refresh()

    mock_fetch.assert_not_called()
    assert result == {"succeeded": 0, "skipped": 0, "failed": 0}


@pytest.mark.asyncio
async def test_splits_into_chunks_of_100_with_delay(monkeypatch):
    pool = object()
    farm_ids = list(range(1, 151))  # 150 фермеров -> 2 batch-запроса (100 + 50)

    fetch_mock = AsyncMock(
        side_effect=lambda ids: ({fid: {"id": fid, "farm": {}} for fid in ids}, [])
    )
    sleep_mock = AsyncMock()

    with patch("jobs.daily_refresh.db.get_pool", AsyncMock(return_value=pool)), \
         patch("jobs.daily_refresh.db.list_farmer_farm_ids", AsyncMock(return_value=farm_ids)), \
         patch("jobs.daily_refresh.farm_cache._fetch_batch_from_sfl", fetch_mock), \
         patch("jobs.daily_refresh.db.update_farmer_stats", AsyncMock()), \
         patch("jobs.daily_refresh.farm_cache.upsert_farm_data", AsyncMock()), \
         patch("jobs.daily_refresh.asyncio.sleep", sleep_mock):
        result = await run_daily_refresh()

    assert fetch_mock.await_count == 2
    sleep_mock.assert_awaited_once()  # пауза между 2 чанками, не перед первым
    assert result == {"succeeded": 150, "skipped": 0, "failed": 0}
