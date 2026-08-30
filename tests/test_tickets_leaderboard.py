"""Тесты для shared/tickets_leaderboard.py: разбор ответа API лидерборда тикетов."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared import tickets_leaderboard


def _fake_response(payload: dict, status_code: int = 200) -> MagicMock:
    """Оборачивает payload в {"data": ...} — так реально отвечает /community/data."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"data": payload}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_fetch_farm_rank_finds_own_entry_in_ranking_details():
    payload = {
        "farmRankingDetails": [
            {"rank": 933, "farmId": 111, "id": "Other", "count": 10},
            {"rank": 934, "farmId": 62559, "id": "Dionis", "count": 9},
            {"rank": 935, "farmId": 222, "id": "Another", "count": 8},
        ]
    }
    client = AsyncMock()
    client.get.return_value = _fake_response(payload)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.tickets_leaderboard.httpx.AsyncClient", return_value=client):
        result = await tickets_leaderboard.fetch_farm_rank(62559)

    assert result == {"rank": 934, "tickets": 9, "game_username": "Dionis"}


@pytest.mark.asyncio
async def test_fetch_farm_rank_raises_when_farm_absent_from_details():
    payload = {"farmRankingDetails": [{"rank": 1, "farmId": 111, "id": "Other", "count": 10}]}
    client = AsyncMock()
    client.get.return_value = _fake_response(payload)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.tickets_leaderboard.httpx.AsyncClient", return_value=client):
        with pytest.raises(tickets_leaderboard.FarmRankNotFound):
            await tickets_leaderboard.fetch_farm_rank(999)


@pytest.mark.asyncio
async def test_fetch_farm_rank_raises_when_no_tickets_this_chapter():
    payload = {"farmRankingDetails": None}
    client = AsyncMock()
    client.get.return_value = _fake_response(payload)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.tickets_leaderboard.httpx.AsyncClient", return_value=client):
        with pytest.raises(tickets_leaderboard.FarmRankNotFound):
            await tickets_leaderboard.fetch_farm_rank(999)


@pytest.mark.asyncio
async def test_fetch_farm_rank_raises_on_404():
    client = AsyncMock()
    client.get.return_value = _fake_response({}, status_code=404)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.tickets_leaderboard.httpx.AsyncClient", return_value=client):
        with pytest.raises(tickets_leaderboard.FarmRankNotFound):
            await tickets_leaderboard.fetch_farm_rank(404)


@pytest.mark.asyncio
async def test_fetch_farm_rank_uses_top_ten_when_details_omitted():
    payload = {
        "farmRankingDetails": None,
        "topTen": [
            {"farmId": 111, "id": "Other", "count": 100},
            {"farmId": 62559, "id": "Dionis", "count": 90},
        ],
    }
    client = AsyncMock()
    client.get.return_value = _fake_response(payload)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.tickets_leaderboard.httpx.AsyncClient", return_value=client):
        result = await tickets_leaderboard.fetch_farm_rank(62559)

    assert result == {"rank": 2, "tickets": 90, "game_username": "Dionis"}


@pytest.mark.asyncio
async def test_fetch_top500_assigns_rank_by_position():
    payload = {
        "topTen": [
            {"farmId": 147426, "id": "n3paa", "count": 4552},
            {"farmId": 15223, "id": "Bacon", "count": 4552},
            {"farmId": 151471, "id": "JaySuper", "count": 4550},
        ]
    }
    client = AsyncMock()
    client.get.return_value = _fake_response(payload)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.tickets_leaderboard.httpx.AsyncClient", return_value=client):
        rows = await tickets_leaderboard.fetch_top500()

    assert rows == [
        {"rank": 1, "farm_id": 147426, "game_username": "n3paa", "tickets": 4552},
        {"rank": 2, "farm_id": 15223, "game_username": "Bacon", "tickets": 4552},
        {"rank": 3, "farm_id": 151471, "game_username": "JaySuper", "tickets": 4550},
    ]

    called_url = client.get.call_args.args[0]
    assert called_url.endswith("/community/data")
    assert client.get.call_args.kwargs["params"] == {
        "type": "ticketLeaderboard",
        "farmId": tickets_leaderboard.TOP500_QUERY_FARM_ID,
        "limit": tickets_leaderboard.TOP500_LIMIT,
    }


@pytest.mark.asyncio
async def test_get_top500_at_queries_snapshot_not_after_given_moment():
    pool = AsyncMock()
    pool.fetch.return_value = ["fake-row"]
    at = datetime(2026, 8, 25, 3, 0, tzinfo=timezone.utc)

    rows = await tickets_leaderboard.get_top500_at(pool, at)

    assert rows == ["fake-row"]
    query, arg = pool.fetch.call_args.args
    assert "taken_at <= $1" in query
    assert arg == at
