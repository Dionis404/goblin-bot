"""Глобальные ограничители бота (значения из конфига)."""
from shared import config
from shared.throttle import RateLimiter, UserCooldown

api_limiter = RateLimiter(
    rate_per_sec=config.API_RATE_PER_SEC,
    concurrency=config.API_CONCURRENCY,
)
user_cooldown = UserCooldown(seconds=config.USER_COOLDOWN_SEC)
# Отдельный кулдаун на кнопку "✅ Да, это я": иначе нажатие сразу после
# ввода номера упиралось бы в user_cooldown, а без кулдауна вовсе каждое
# нажатие — лишний запрос к SFL, занимающий общий api_limiter.
confirm_cooldown = UserCooldown(seconds=config.USER_COOLDOWN_SEC)
# Жалобы "это моя ферма" админу — не чаще раза в 10 минут от одного человека
dispute_cooldown = UserCooldown(seconds=600)
