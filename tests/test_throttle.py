"""Тесты для shared/throttle.py: кулдаун пользователя."""
from unittest.mock import patch

from shared.throttle import UserCooldown


def test_first_request_allowed_right_after_boot():
    """monotonic() считает от загрузки машины — сразу после ребута первый запрос не блокируется."""
    cooldown = UserCooldown(seconds=600)
    with patch("shared.throttle.time.monotonic", return_value=100.0):
        assert cooldown.check(1) == 0.0


def test_repeated_request_is_blocked_until_cooldown_passes():
    cooldown = UserCooldown(seconds=10)
    with patch("shared.throttle.time.monotonic", return_value=1000.0):
        assert cooldown.check(1) == 0.0
    with patch("shared.throttle.time.monotonic", return_value=1004.0):
        assert cooldown.check(1) == 6.0
        assert cooldown.check(2) == 0.0  # другой пользователь независим
    with patch("shared.throttle.time.monotonic", return_value=1010.0):
        assert cooldown.check(1) == 0.0
