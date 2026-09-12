"""Тесты для shared/game_updates.py: парсинг, классификация, очистка и форматирование."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared import game_updates

SAMPLE_RAW_BODY = (
    "What's Changed\n"
    "\n"
    "[FEAT] Love Boulder on Love Island (#7616) @adamhannigan\n"
    "[FIX] Address CodeRabbit review on the Lover's Dilemma scene (#7613) @adamhannigan\n"
    "[CHORE] Bump deps @adamhannigan\n"
    "Something unrelated in\n"
    "\n"
    "Full Changelog: https://example.com/compare/a...b"
)


def test_parse_lines_drops_noise():
    lines = game_updates.parse_lines(SAMPLE_RAW_BODY)
    assert lines == [
        "[FEAT] Love Boulder on Love Island (#7616) @adamhannigan",
        "[FIX] Address CodeRabbit review on the Lover's Dilemma scene (#7613) @adamhannigan",
        "[CHORE] Bump deps @adamhannigan",
        "Something unrelated in",
    ]


def test_classify_buckets_by_tag():
    lines = game_updates.parse_lines(SAMPLE_RAW_BODY)
    buckets = game_updates.classify(lines)
    assert len(buckets["feat"]) == 1
    assert len(buckets["fix"]) == 1
    assert len(buckets["chore"]) == 1
    assert buckets["other"] == ["Something unrelated in"]


def test_clean_items_strips_tags_prs_mentions_and_trailing_in():
    buckets = {
        "feat": ["[FEAT] Love Boulder on Love Island (#7616) @adamhannigan"],
        "other": ["Something unrelated in"],
    }
    cleaned = game_updates.clean_items(buckets)
    assert cleaned["feat"] == ["Love Boulder on Love Island"]
    assert cleaned["other"] == ["Something unrelated"]


def test_format_message_includes_emoji_headers_and_sections():
    buckets = {"feat": ["Новая механика"], "fix": [], "chore": [], "other": []}
    text = game_updates.format_message("v1.2.3 Test", "https://example.com/release", buckets)

    assert "📰 Зафиксировано обновление мира" in text
    assert "🌾 v1.2.3 Test" in text
    assert "🌱 Что-то новенькое:" in text
    assert "• Новая механика" in text
    assert "🔗 https://example.com/release" in text
    assert "🐛" not in text  # пустой бакет fix — секция не должна попасть в текст


def test_format_message_empty_buckets_uses_fallback_text():
    buckets = {"feat": [], "fix": [], "chore": [], "other": []}
    text = game_updates.format_message("v1.2.3", "https://example.com", buckets)

    assert "Новых записей об изменениях не найдено" in text
    assert "🌾 v1.2.3" in text


@pytest.mark.asyncio
async def test_translate_buckets_without_api_key_returns_original(monkeypatch):
    monkeypatch.setattr(game_updates.config, "AI_TRANSLATE_API_KEY", None)
    buckets = {"feat": ["Hello"], "fix": [], "chore": [], "other": []}

    result = await game_updates.translate_buckets(buckets)

    assert result == buckets


@pytest.mark.asyncio
async def test_translate_buckets_parses_ai_response(monkeypatch):
    monkeypatch.setattr(game_updates.config, "AI_TRANSLATE_API_KEY", "test-key")
    buckets = {"feat": ["Hello"], "fix": [], "chore": [], "other": []}

    ai_output = json.dumps([{"bucket": "feat", "text": "Привет"}])
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": ai_output}}]}

    client = AsyncMock()
    client.post.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.game_updates.httpx.AsyncClient", return_value=client):
        result = await game_updates.translate_buckets(buckets)

    assert result["feat"] == ["Привет"]


@pytest.mark.asyncio
async def test_translate_buckets_falls_back_on_malformed_ai_response(monkeypatch):
    monkeypatch.setattr(game_updates.config, "AI_TRANSLATE_API_KEY", "test-key")
    buckets = {"feat": ["Hello"], "fix": [], "chore": [], "other": []}

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": "not json"}}]}

    client = AsyncMock()
    client.post.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.game_updates.httpx.AsyncClient", return_value=client):
        result = await game_updates.translate_buckets(buckets)

    assert result == buckets


@pytest.mark.asyncio
async def test_fetch_latest_release_parses_atom_feed():
    feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>v2.28.22 Unlinking</title>
    <link rel="alternate" type="text/html" href="https://github.com/x/y/releases/tag/v2.28.22"/>
    <content type="html">&lt;h2&gt;What's Changed&lt;/h2&gt;
&lt;ul&gt;
&lt;li&gt;[FEAT] Love Boulder (&lt;a href="x"&gt;#7616&lt;/a&gt;) &lt;a href="y"&gt;@adamhannigan&lt;/a&gt;&lt;/li&gt;
&lt;/ul&gt;</content>
  </entry>
</feed>"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = feed_xml

    client = AsyncMock()
    client.get.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.game_updates.httpx.AsyncClient", return_value=client):
        release = await game_updates.fetch_latest_release()

    assert release["name"] == "v2.28.22 Unlinking"
    assert release["url"] == "https://github.com/x/y/releases/tag/v2.28.22"
    assert "[FEAT] Love Boulder" in release["raw_body"]
    assert "#7616" in release["raw_body"]
    assert "@adamhannigan" in release["raw_body"]


@pytest.mark.asyncio
async def test_fetch_latest_release_raises_when_feed_empty():
    feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = feed_xml

    client = AsyncMock()
    client.get.return_value = resp
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    with patch("shared.game_updates.httpx.AsyncClient", return_value=client):
        with pytest.raises(game_updates.NoReleasesFound):
            await game_updates.fetch_latest_release()
