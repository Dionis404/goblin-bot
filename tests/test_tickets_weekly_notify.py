"""Тесты для jobs/tickets_weekly_notify.py: форматирование еженедельного отчёта."""
from jobs.tickets_weekly_notify import _display_name, format_report


def test_display_name_prefers_telegram_username():
    assert _display_name("ivan", "IvanGame", 1) == "@ivan"


def test_display_name_falls_back_to_game_username():
    assert _display_name(None, "IvanGame", 1) == "IvanGame"


def test_display_name_falls_back_to_farm_id():
    assert _display_name(None, None, 42) == "Ферма #42"


def test_format_report_empty():
    text = format_report([])
    assert "никто" in text.lower()


def test_format_report_sorted_lines():
    report = [
        {"display_name": "@ivan", "rank": 98, "tickets": 2550},
        {"display_name": "@petro", "rank": 610, "tickets": 900},
    ]
    text = format_report(report)
    assert "@ivan — 98 место — 2550 тикетов" in text
    assert "@petro — 610 место — 900 тикетов" in text
