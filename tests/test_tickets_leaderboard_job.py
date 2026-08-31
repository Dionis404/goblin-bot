"""
Тесты для jobs/tickets_leaderboard.py: объединённый проход топ-500 +
tracked-фермеров с переиспользованием топ-500 и постоянным исключением
ферм с рангом ниже TICKETS_EXCLUDE_RANK.
"""
from unittest.mock import AsyncMock, patch

import pytest

from jobs.tickets_leaderboard import run_tickets_leaderboard


def _patch_config_delay(monkeypatch):
    import jobs.tickets_leaderboard as job
    monkeypatch.setattr(job, "DELAY_BETWEEN_FARMS_SEC", 0)


@pytest.mark.asyncio
async def test_farm_found_in_top500_skips_http_request(monkeypatch):
    _patch_config_delay(monkeypatch)

    top500 = [{"rank": 42, "farm_id": 62559, "game_username": "Dionis", "tickets": 5000}]

    with patch("shared.tickets_leaderboard.fetch_top500", AsyncMock(return_value=top500)), \
         patch("shared.tickets_leaderboard.save_top500_snapshot", AsyncMock()), \
         patch("shared.tickets_leaderboard.get_trackable_farm_ids", AsyncMock(return_value=[62559])), \
         patch("shared.tickets_leaderboard.fetch_farm_rank", AsyncMock()) as mock_fetch, \
         patch("shared.tickets_leaderboard.save_snapshot", AsyncMock()) as mock_save, \
         patch("shared.tickets_leaderboard.mark_excluded", AsyncMock()), \
         patch("shared.db.get_pool", AsyncMock(return_value=object())):
        result = await run_tickets_leaderboard()

    mock_fetch.assert_not_called()
    mock_save.assert_awaited_once()
    assert result == {"saved": 1, "skipped": 0, "from_top500": 1, "excluded": 0, "total": 1}


@pytest.mark.asyncio
async def test_farm_outside_top500_makes_http_request(monkeypatch):
    _patch_config_delay(monkeypatch)

    with patch("shared.tickets_leaderboard.fetch_top500", AsyncMock(return_value=[])), \
         patch("shared.tickets_leaderboard.save_top500_snapshot", AsyncMock()), \
         patch("shared.tickets_leaderboard.get_trackable_farm_ids", AsyncMock(return_value=[62559])), \
         patch(
             "shared.tickets_leaderboard.fetch_farm_rank",
             AsyncMock(return_value={"rank": 900, "tickets": 3000, "game_username": "Dionis"}),
         ) as mock_fetch, \
         patch("shared.tickets_leaderboard.save_snapshot", AsyncMock()) as mock_save, \
         patch("shared.tickets_leaderboard.mark_excluded", AsyncMock()), \
         patch("shared.db.get_pool", AsyncMock(return_value=object())):
        result = await run_tickets_leaderboard()

    mock_fetch.assert_awaited_once_with(62559)
    mock_save.assert_awaited_once()
    assert result == {"saved": 1, "skipped": 0, "from_top500": 0, "excluded": 0, "total": 1}


@pytest.mark.asyncio
async def test_low_rank_marks_farm_excluded(monkeypatch):
    _patch_config_delay(monkeypatch)

    with patch("shared.tickets_leaderboard.fetch_top500", AsyncMock(return_value=[])), \
         patch("shared.tickets_leaderboard.save_top500_snapshot", AsyncMock()), \
         patch("shared.tickets_leaderboard.get_trackable_farm_ids", AsyncMock(return_value=[406])), \
         patch(
             "shared.tickets_leaderboard.fetch_farm_rank",
             AsyncMock(return_value={"rank": 8000, "tickets": 100, "game_username": "MCDUCK"}),
         ), \
         patch("shared.tickets_leaderboard.save_snapshot", AsyncMock()) as mock_save, \
         patch("shared.tickets_leaderboard.mark_excluded", AsyncMock()) as mock_exclude, \
         patch("shared.db.get_pool", AsyncMock(return_value=object())):
        result = await run_tickets_leaderboard()

    mock_save.assert_not_called()  # rank > RANK_CUTOFF — снэпшот не пишется
    mock_exclude.assert_awaited_once()
    assert result == {"saved": 0, "skipped": 1, "from_top500": 0, "excluded": 1, "total": 1}


@pytest.mark.asyncio
async def test_farm_found_in_top500_with_low_rank_is_also_excluded(monkeypatch):
    """Даже бесплатное попадание из топ-500 должно триггерить exclude, если ранг низкий."""
    _patch_config_delay(monkeypatch)

    top500 = [{"rank": 2500, "farm_id": 999, "game_username": "Ghost", "tickets": 10}]

    with patch("shared.tickets_leaderboard.fetch_top500", AsyncMock(return_value=top500)), \
         patch("shared.tickets_leaderboard.save_top500_snapshot", AsyncMock()), \
         patch("shared.tickets_leaderboard.get_trackable_farm_ids", AsyncMock(return_value=[999])), \
         patch("shared.tickets_leaderboard.fetch_farm_rank", AsyncMock()) as mock_fetch, \
         patch("shared.tickets_leaderboard.save_snapshot", AsyncMock()) as mock_save, \
         patch("shared.tickets_leaderboard.mark_excluded", AsyncMock()) as mock_exclude, \
         patch("shared.db.get_pool", AsyncMock(return_value=object())):
        result = await run_tickets_leaderboard()

    mock_fetch.assert_not_called()
    mock_save.assert_not_called()
    mock_exclude.assert_awaited_once()
    assert result == {"saved": 0, "skipped": 1, "from_top500": 1, "excluded": 1, "total": 1}
