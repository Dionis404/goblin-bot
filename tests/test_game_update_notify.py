"""Тесты для jobs/game_update_notify.py: дедупликация отправки по last-sent URL."""
from unittest.mock import AsyncMock, patch

import pytest

from jobs.game_update_notify import check_and_notify


@pytest.mark.asyncio
async def test_no_chat_id_configured_skips_send(monkeypatch):
    import jobs.game_update_notify as job
    monkeypatch.setattr(job.config, "GAME_UPDATE_NOTIFY_CHAT_ID", None)

    bot = AsyncMock()
    result = await check_and_notify(bot)

    assert result == {"sent": False, "reason": "no_chat_id"}
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_new_release_is_sent_and_recorded(monkeypatch):
    import jobs.game_update_notify as job
    monkeypatch.setattr(job.config, "GAME_UPDATE_NOTIFY_CHAT_ID", "-100200")

    release = {"name": "v1.2.3", "url": "https://example.com/v1.2.3", "raw_body": ""}
    bot = AsyncMock()

    with patch("jobs.game_update_notify.game_updates.fetch_latest_release", AsyncMock(return_value=release)), \
         patch("jobs.game_update_notify.game_updates.build_update_message", AsyncMock(return_value="text")), \
         patch("jobs.game_update_notify.bot_settings.get_str", AsyncMock(return_value=None)), \
         patch("jobs.game_update_notify.bot_settings.set_str", AsyncMock()) as mock_set:
        result = await check_and_notify(bot)

    bot.send_message.assert_awaited_once_with("-100200", "text")
    mock_set.assert_awaited_once_with("game_update_last_sent_url", release["url"])
    assert result == {"sent": True, "release": "v1.2.3"}


@pytest.mark.asyncio
async def test_same_release_as_last_sent_is_skipped(monkeypatch):
    import jobs.game_update_notify as job
    monkeypatch.setattr(job.config, "GAME_UPDATE_NOTIFY_CHAT_ID", "-100200")

    release = {"name": "v1.2.3", "url": "https://example.com/v1.2.3", "raw_body": ""}
    bot = AsyncMock()

    with patch("jobs.game_update_notify.game_updates.fetch_latest_release", AsyncMock(return_value=release)), \
         patch("jobs.game_update_notify.bot_settings.get_str", AsyncMock(return_value=release["url"])):
        result = await check_and_notify(bot)

    bot.send_message.assert_not_called()
    assert result == {"sent": False, "reason": "already_sent"}


@pytest.mark.asyncio
async def test_no_releases_in_feed_is_skipped(monkeypatch):
    import jobs.game_update_notify as job
    from shared.game_updates import NoReleasesFound

    monkeypatch.setattr(job.config, "GAME_UPDATE_NOTIFY_CHAT_ID", "-100200")
    bot = AsyncMock()

    with patch(
        "jobs.game_update_notify.game_updates.fetch_latest_release",
        AsyncMock(side_effect=NoReleasesFound()),
    ):
        result = await check_and_notify(bot)

    bot.send_message.assert_not_called()
    assert result == {"sent": False, "reason": "no_releases"}
