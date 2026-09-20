"""Тесты для jobs/daily_refresh.py: батч-прогрев farm_cache tracked-ферм."""
from unittest.mock import AsyncMock, patch

import pytest

from jobs.daily_refresh import run_daily_refresh


@pytest.mark.asyncio
async def test_run_daily_refresh_delegates_to_batch_refresh():
    rows = [{"farm_id": 1}, {"farm_id": 2}, {"farm_id": 3}]
    pool = AsyncMock()
    pool.fetch.return_value = rows

    batch_result = {"succeeded": 2, "skipped": 1, "failed": 0}
    with patch("jobs.daily_refresh.db.get_pool", AsyncMock(return_value=pool)), \
         patch(
             "jobs.daily_refresh.farm_cache.refresh_farms_batch",
             AsyncMock(return_value=batch_result),
         ) as mock_batch:
        result = await run_daily_refresh()

    mock_batch.assert_awaited_once()
    call_args = mock_batch.await_args
    assert call_args.args[0] == [1, 2, 3]
    assert call_args.kwargs["delay_between_chunks_sec"] > 0
    assert result == batch_result


@pytest.mark.asyncio
async def test_run_daily_refresh_with_no_tracked_farms():
    pool = AsyncMock()
    pool.fetch.return_value = []

    with patch("jobs.daily_refresh.db.get_pool", AsyncMock(return_value=pool)), \
         patch(
             "jobs.daily_refresh.farm_cache.refresh_farms_batch",
             AsyncMock(return_value={"succeeded": 0, "skipped": 0, "failed": 0}),
         ) as mock_batch:
        result = await run_daily_refresh()

    mock_batch.assert_awaited_once_with([], pool, delay_between_chunks_sec=5.0)
    assert result == {"succeeded": 0, "skipped": 0, "failed": 0}
