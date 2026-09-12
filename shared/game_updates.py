"""
Уведомление о новой версии игры Sunflower Land: атом-фид релизов GitHub →
парсинг → классификация по тегам ([FEAT]/[FIX]/[CHORE]) → AI-перевод на
русский → сообщение в Telegram. Перенос n8n-workflow "Уведомление о новой
версии игры" на Python (jobs/game_update_notify.py — цикл опроса раз в минуту).
"""
import html
import json
import logging
import re
from xml.etree import ElementTree

import httpx

from shared import config

log = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
HTTP_TIMEOUT = 10.0
AI_TIMEOUT = 30.0

_SKIP_LINE_PREFIXES = ("what", "no change", "full changelog")

_TAG_BUCKETS = [
    ("[FEAT]", "feat"),
    ("[FIX]", "fix"),
    ("[CHORE]", "chore"),
]

_TRANSLATE_SYSTEM_PROMPT = """\
Ты переводчик changelog'ов игры Sunflower Land (браузерная фермерская игра). \
Переведи каждый пункт на живой разговорный русский язык, используя игровую \
тематику где уместно. Сохраняй смысл точно, но делай текст живым и немного \
эмоционным.

Входные данные — JSON-массив объектов { bucket, text }.
Верни ТОЛЬКО валидный JSON-массив. Без пояснений, без markdown, без ```json.
Только сырой JSON начинающийся с [ и заканчивающийся ].
Если текст слишком длинный — сокращай переводы, но не обрывай массив."""


class NoReleasesFound(Exception):
    """В фиде нет ни одной записи."""


_BLOCK_TAGS_RE = re.compile(r"</?(h1|h2|h3|h4|h5|h6|ul|ol|li|p|br|div)\b[^>]*>", re.IGNORECASE)


def _strip_html(raw_html: str) -> str:
    """
    Грубый эквивалент contentSnippet из n8n RSS-ноды: HTML -> текст.
    Блочные теги (li/h2/p/br/...) дают перевод строки, инлайновые (a/span/...)
    вырезаются на месте — иначе PR-ссылки и @упоминания разрывают строку пункта.
    """
    text = _BLOCK_TAGS_RE.sub("\n", raw_html)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text


async def fetch_latest_release() -> dict:
    """Возвращает {"name", "url", "raw_body"} для самой свежей записи фида."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(config.GAME_UPDATE_FEED_URL)
        resp.raise_for_status()
        feed_xml = resp.text

    root = ElementTree.fromstring(feed_xml)
    entry = root.find("atom:entry", ATOM_NS)
    if entry is None:
        raise NoReleasesFound("Фид релизов пуст")

    title_el = entry.find("atom:title", ATOM_NS)
    link_el = entry.find("atom:link", ATOM_NS)
    content_el = entry.find("atom:content", ATOM_NS)

    name = title_el.text if title_el is not None else ""
    url = link_el.get("href") if link_el is not None else ""
    raw_content = content_el.text if content_el is not None and content_el.text else ""

    raw_body = _strip_html(raw_content).replace("\r", "").replace("*", "•").strip()

    return {"name": name, "url": url, "raw_body": raw_body}


def parse_lines(raw_body: str) -> list[str]:
    """Разбивает тело релиза на строки, отбрасывая служебные (What's Changed и т.п.)."""
    lines = []
    for line in raw_body.split("\n"):
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(_SKIP_LINE_PREFIXES):
            continue
        lines.append(line)
    return lines


def classify(lines: list[str]) -> dict[str, list[str]]:
    """Раскладывает строки по бакетам feat/fix/chore/other по тегам в квадратных скобках."""
    buckets: dict[str, list[str]] = {"feat": [], "fix": [], "chore": [], "other": []}
    for line in lines:
        upper = line.upper()
        bucket = next((b for tag, b in _TAG_BUCKETS if tag in upper), "other")
        buckets[bucket].append(line)
    return buckets


def _clean_line(line: str) -> str:
    line = re.sub(r"^[•*]\s*", "", line)
    line = re.sub(r"\[.*?\]\s*", "", line)
    line = re.sub(r"\(#\d+\)", "", line)
    line = re.sub(r"#\d+", "", line)
    line = re.sub(r"@\S+", "", line)
    line = re.sub(r"\bin\b\s*$", "", line, flags=re.IGNORECASE)
    return line.strip()


def clean_items(buckets: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: [_clean_line(line) for line in lines] for key, lines in buckets.items()}


def _items_payload(buckets: dict[str, list[str]]) -> list[dict]:
    return [
        {"bucket": bucket, "text": text}
        for bucket, lines in buckets.items()
        for text in lines
        if text.strip()
    ]


def _parse_ai_response(raw_text: str, fallback_buckets: dict[str, list[str]]) -> dict[str, list[str]]:
    """Парсит ответ модели (JSON-массив {bucket, text}); при ошибке — откат на оригинал."""
    translated: dict[str, list[str]] = {"feat": [], "fix": [], "chore": [], "other": []}
    try:
        cleaned = re.sub(r"```json\s*|```\s*", "", raw_text).strip()
        items = json.loads(cleaned)
        for item in items:
            bucket = item.get("bucket")
            if bucket in translated:
                translated[bucket].append(item["text"])
        return translated
    except Exception:
        log.warning("Не удалось разобрать ответ AI-перевода, использую оригинал текста", exc_info=True)
        return fallback_buckets


async def translate_buckets(buckets: dict[str, list[str]]) -> dict[str, list[str]]:
    """AI-перевод пунктов changelog'а на русский. При любой ошибке — откат на оригинал."""
    items = _items_payload(buckets)
    if not items:
        return buckets

    if not config.AI_TRANSLATE_API_KEY:
        log.warning("AI_TRANSLATE_API_KEY не задан — уведомление о версии игры пойдёт без перевода")
        return buckets

    payload = {
        "model": config.AI_TRANSLATE_MODEL,
        "messages": [
            {"role": "system", "content": _TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
        ],
    }
    headers = {"Authorization": f"Bearer {config.AI_TRANSLATE_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
            resp = await client.post(
                f"{config.AI_TRANSLATE_API_BASE}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        raw_text = data["choices"][0]["message"]["content"]
    except Exception:
        log.exception("Ошибка запроса AI-перевода changelog'а, использую оригинал текста")
        return buckets

    return _parse_ai_response(raw_text, buckets)


def format_message(name: str, url: str, buckets: dict[str, list[str]]) -> str:
    """Собирает финальный текст сообщения — эмодзи-заголовки и формат 1-в-1 с n8n."""
    def section(title: str, lines: list[str]) -> str | None:
        if not lines:
            return None
        body = "\n".join(f"• {line}" for line in lines)
        return f"{title}\n{body}"

    sections = [
        section("🌱 Что-то новенькое:", buckets.get("feat", [])),
        section("🐛 Баги снова пытались устроить хаос, но разработчики успели первыми:", buckets.get("fix", [])),
        section("⚙️ Подкручены системные шестерёнки острова:", buckets.get("chore", [])),
        section("📦 Прочие странности и изменения мира", buckets.get("other", [])),
    ]
    sections = [s for s in sections if s]

    if sections:
        joined = "\n\n".join(sections)
        return (
            f"📰 Зафиксировано обновление мира\n"
            f"🌾 {name}\n"
            f"📋 Цифровые поля SFL зафиксировали свежие изменения мира:\n\n"
            f"{joined}\n\n"
            f"🔗 {url}"
        )

    return (
        f"Зафиксировано обновление мира:\n"
        f"🌾 {name}\n"
        f"Разработчики прошли по острову… ничего не сломали. Подозрительно спокойно.\n\n"
        f"📋 Новых записей об изменениях не найдено.\n"
        f"🔗 {url}"
    )


async def build_update_message(release: dict) -> str:
    """Полный пайплайн: строки -> классификация -> очистка -> перевод -> сообщение."""
    lines = parse_lines(release["raw_body"])
    buckets = classify(lines)
    buckets = clean_items(buckets)
    buckets = await translate_buckets(buckets)
    return format_message(release["name"], release["url"], buckets)
