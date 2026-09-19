"""Тесты для shared/auctions.py: read-only витрина auctions / auction_results."""
from unittest.mock import AsyncMock

import pytest

from shared import auctions


@pytest.mark.asyncio
async def test_list_past_without_item_name_filter():
    pool = AsyncMock()
    pool.fetch.return_value = []

    await auctions.list_past(pool, limit=10)

    query, *args = pool.fetch.call_args.args
    assert "ILIKE" not in query
    assert args == [10]


@pytest.mark.asyncio
async def test_list_past_with_item_name_filter():
    pool = AsyncMock()
    pool.fetch.return_value = []

    await auctions.list_past(pool, limit=5, item_name="Rice Shirt")

    query, *args = pool.fetch.call_args.args
    assert "item_name ILIKE $2" in query
    assert args == [5, "Rice Shirt"]


@pytest.mark.asyncio
async def test_get_results_joins_item_name_and_type():
    pool = AsyncMock()
    pool.fetchrow.return_value = {
        "item_name": "Rice Shirt",
        "item_type": "wearable",
        "my_status": "complete",
        "participant_count": 82,
        "supply": 100,
        "leaderboard": [{"rank": 1, "farmId": 129896}],
        "fetched_at": "2026-08-07T00:00:00Z",
    }

    row = await auctions.get_results(pool, "coin-aura-2024-08-07-drop-1")

    query, *args = pool.fetchrow.call_args.args
    assert "JOIN auctions a ON a.auction_id = r.auction_id" in query
    assert args == ["coin-aura-2024-08-07-drop-1"]
    assert row["item_name"] == "Rice Shirt"
    assert row["item_type"] == "wearable"


@pytest.mark.asyncio
async def test_get_results_returns_none_when_missing():
    pool = AsyncMock()
    pool.fetchrow.return_value = None

    row = await auctions.get_results(pool, "unknown-auction")

    assert row is None
