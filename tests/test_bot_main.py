"""Тесты для bot/main.py: расчёт окна еженедельного уведомления о лидерборде тикетов."""
from datetime import datetime
from zoneinfo import ZoneInfo

from bot.main import _current_notify_window

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
