"""Работа с community API Sunflower Land. Уровень считает сайт из xp."""
import asyncio
import logging

import aiohttp
from shared import config

log = logging.getLogger(__name__)


def _to_float(value) -> float | None:
    """balance/coins приходят строкой или числом — приводим к float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


class FarmNotFound(Exception):
    pass


class RateLimited(Exception):
    """API вернул 429 даже после повторов."""
    pass


async def fetch_farm(farm_id: int) -> dict:
    """
    Дёргает community API и возвращает разобранный профиль:
    {farm_id, username, xp, balance, coins, farm_url}.
    Бросает FarmNotFound, если фермы нет.
    """
    url = f"{config.SFL_API_BASE}/community/farms/{farm_id}"

    # Через прокси, если задан (SOCKS5 требует aiohttp_socks; http — штатный proxy=)
    proxy = config.SFL_PROXY
    connector = None
    request_kwargs = {}
    if proxy:
        if proxy.startswith("socks"):
            from aiohttp_socks import ProxyConnector
            connector = ProxyConnector.from_url(proxy)
        else:
            request_kwargs["proxy"] = proxy

    # Ключ авторизации в заголовке x-api-key
    headers = {}
    if config.SFL_API_KEY:
        headers["x-api-key"] = config.SFL_API_KEY

    # Импорт здесь, чтобы не плодить циклических зависимостей
    from bot.throttle import api_limiter

    data = None
    for attempt in range(1, config.API_MAX_RETRIES + 1):
        # Глобальный троттл: не чаще заданного числа запросов/сек на весь бот
        async with api_limiter:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                    **request_kwargs,
                ) as resp:
                    if resp.status == 404:
                        raise FarmNotFound(f"Ферма {farm_id} не найдена")
                    if resp.status == 429:
                        # Слишком много запросов — ждём и повторяем
                        retry_after = resp.headers.get("Retry-After")
                        wait = (
                            float(retry_after)
                            if retry_after and retry_after.isdigit()
                            else config.API_RETRY_BACKOFF * attempt
                        )
                        log.warning(
                            "SFL API 429, попытка %s/%s, ждём %.1f с",
                            attempt, config.API_MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    break
    else:
        # Все попытки исчерпаны на 429
        raise RateLimited("SFL API перегружен, попробуйте позже")

    if data is None:
        raise RateLimited("SFL API перегружен, попробуйте позже")

    farm = data.get("farm")
    if not farm:
        raise FarmNotFound(f"Ферма {farm_id} не найдена")

    xp = _to_float((farm.get("bumpkin") or {}).get("experience"))
    return {
        "farm_id": int(data.get("id", farm_id)),
        "username": farm.get("username"),  # может быть None
        "xp": xp,
        "balance": _to_float(farm.get("balance")),
        "coins": _to_float(farm.get("coins")),
        "farm_url": config.FARM_URL_TEMPLATE.format(farm_id=farm_id),
    }
