"""Тесты для bot/main.py: окно еженедельного отчёта, LP-флаг, дата главы, логирование."""
import asyncio
import logging
import sys
import types
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bot import main as bot_main
from bot.main import _current_notify_window
from shared import config

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def test_window_is_open_on_sunday_for_previous_monday():
    # Воскресенье относится к неделе, начавшейся в прошлый понедельник —
    # то окно уже наступило и должно быть отправлено, если ещё не было.
    now = datetime(2026, 8, 30, 23, 59, tzinfo=MOSCOW_TZ)
    assert _current_notify_window(now) == "2026-08-24"


def test_window_is_none_just_before_trigger_hour():
    # Понедельник 02:59 — тоже ещё рано
    now = datetime(2026, 8, 31, 2, 59, tzinfo=MOSCOW_TZ)
    assert _current_notify_window(now) is None


def test_window_opens_at_3am_monday():
    now = datetime(2026, 8, 31, 3, 0, tzinfo=MOSCOW_TZ)
    assert _current_notify_window(now) == "2026-08-31"


def test_window_stays_same_id_for_rest_of_week():
    # Рестарт в среду той же недели должен видеть то же окно, что и в 03:00 ПН
    now = datetime(2026, 9, 2, 15, 0, tzinfo=MOSCOW_TZ)
    assert _current_notify_window(now) == "2026-08-31"


def test_window_advances_to_next_monday():
    now = datetime(2026, 9, 7, 3, 0, tzinfo=MOSCOW_TZ)
    assert _current_notify_window(now) == "2026-09-07"


# --- LP-лидерборд: флаг выключения ---

def _fake_lp_job(monkeypatch, run):
    fake_job = types.ModuleType("jobs.lp_leaderboard")
    fake_job.run_lp_leaderboard = run
    monkeypatch.setitem(sys.modules, "jobs.lp_leaderboard", fake_job)


def test_lp_loop_exits_without_work_when_disabled(monkeypatch):
    monkeypatch.setattr(bot_main.config, "LP_LEADERBOARD_ENABLED", False)
    called = []

    async def run_lp_leaderboard():
        called.append(True)

    _fake_lp_job(monkeypatch, run_lp_leaderboard)

    # выключенный цикл должен сразу завершиться, а не висеть в while True
    asyncio.run(asyncio.wait_for(bot_main.lp_leaderboard_loop(), timeout=1))
    assert called == []


def test_lp_loop_skips_without_graph_keys(monkeypatch):
    monkeypatch.setattr(bot_main.config, "LP_LEADERBOARD_ENABLED", True)
    monkeypatch.delenv("GRAPH_API_KEY", raising=False)
    monkeypatch.delenv("SUBGRAPH_ID", raising=False)
    called = []

    async def run_lp_leaderboard():
        called.append(True)

    _fake_lp_job(monkeypatch, run_lp_leaderboard)

    asyncio.run(asyncio.wait_for(bot_main.lp_leaderboard_loop(), timeout=1))
    assert called == []


def test_lp_loop_runs_job_when_enabled(monkeypatch):
    monkeypatch.setattr(bot_main.config, "LP_LEADERBOARD_ENABLED", True)
    monkeypatch.setenv("GRAPH_API_KEY", "key")
    monkeypatch.setenv("SUBGRAPH_ID", "subgraph")
    called = []

    async def run_lp_leaderboard():
        called.append(True)
        raise asyncio.CancelledError  # выходим из бесконечного цикла после первого запуска

    _fake_lp_job(monkeypatch, run_lp_leaderboard)

    try:
        asyncio.run(bot_main.lp_leaderboard_loop())
    except asyncio.CancelledError:
        pass
    assert called == [True]


# --- Дата новой главы из env ---

def test_chapter_reset_key_follows_chapter_date():
    # Ключ привязан к дате главы: новая глава = новый ключ = новый одноразовый сброс
    assert bot_main.CHAPTER_RESET_DONE_KEY.startswith("tickets_excluded_reset_")
    assert bot_main.NEW_CHAPTER_START.tzinfo is not None
    assert bot_main.NEW_CHAPTER_START.strftime("%Y_%m_%d") in bot_main.CHAPTER_RESET_DONE_KEY
    assert bot_main.NEW_CHAPTER_START == datetime(2026, 11, 2, tzinfo=timezone.utc)


def test_default_api_rate_respects_community_limit():
    # Проверяем дефолт из кода, а не итоговое значение: на него влияет локальный .env
    assert config.DEFAULT_API_RATE_PER_SEC <= 0.2  # не чаще 1 запроса в 5 с


def test_env_flag_defaults_and_parsing(monkeypatch):
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert config.env_flag("SOME_FLAG", default=True) is True  # локально без compose — включено
    monkeypatch.setenv("SOME_FLAG", "false")
    assert config.env_flag("SOME_FLAG", default=True) is False
    monkeypatch.setenv("SOME_FLAG", " ON ")
    assert config.env_flag("SOME_FLAG", default=False) is True


def test_httpx_request_urls_are_not_logged():
    """В URL The Graph зашит GRAPH_API_KEY — httpx не должен писать URL на INFO."""
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
