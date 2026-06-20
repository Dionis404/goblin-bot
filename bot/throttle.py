"""Защита от превышения rate limit SFL API и спама пользователей."""
import asyncio
import time

from shared import config


class RateLimiter:
    """
    Глобальный ограничитель запросов к внешнему API.
    Гарантирует не более одного запроса каждые (1 / rate) секунд
    и не более `concurrency` одновременных запросов.
    """

    def __init__(self, rate_per_sec: float, concurrency: int = 1):
        self._min_interval = 1.0 / rate_per_sec
        self._sem = asyncio.Semaphore(concurrency)
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        await self._sem.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
        return self

    async def __aexit__(self, *exc):
        self._sem.release()


class UserCooldown:
    """Anti-spam: не чаще 1 запроса от одного пользователя в `seconds` секунд."""

    def __init__(self, seconds: float):
        self._seconds = seconds
        self._last: dict[int, float] = {}

    def check(self, user_id: int) -> float:
        """
        Возвращает 0, если можно делать запрос (и помечает время),
        иначе — сколько секунд осталось ждать.
        """
        now = time.monotonic()
        last = self._last.get(user_id, 0.0)
        remaining = self._seconds - (now - last)
        if remaining > 0:
            return remaining
        self._last[user_id] = now
        return 0.0


# Глобальные экземпляры (значения из конфига)
api_limiter = RateLimiter(
    rate_per_sec=config.API_RATE_PER_SEC,
    concurrency=config.API_CONCURRENCY,
)
user_cooldown = UserCooldown(seconds=config.USER_COOLDOWN_SEC)
