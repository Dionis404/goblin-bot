"""Безопасная сборка HTML-сообщений Telegram (бот работает с parse_mode=HTML)."""
import html

# Лимит Telegram — 4096 символов, оставляем запас под эмодзи/суррогатные пары.
TELEGRAM_MESSAGE_LIMIT = 4000


def esc(value, empty: str = "—") -> str:
    """
    Экранирует любые внешние данные (ники из игры, имена в Telegram, changelog)
    перед вставкой в HTML-сообщение — иначе "<" в нике ломает отправку
    ("can't parse entities"), а "<a href=...>" позволяет подсунуть ссылку.
    """
    if value is None:
        return empty
    return html.escape(str(value), quote=False)


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """
    Режет длинный текст на части не длиннее `limit` по границам строк — в
    отличие от обрезки text[:N], не разрывает HTML-тег посреди строки.
    Строка длиннее лимита (на практике не встречается) режется принудительно.
    """
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks
