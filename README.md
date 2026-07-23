# goblin-bot

Telegram-бот сообщества [GoblinCodex](https://goblincodex.fun) — экосистемы для игроков Sunflower Land.

## Что умеет (этап 1)

- Принимает номер фермы в личном чате
- Проверяет ферму через community API Sunflower Land
- Показывает ник игрока для подтверждения
- Записывает привязку в БД (одна ферма ↔ один Telegram, без смены)
- В группах молчит — обрабатывает только личные сообщения
- Защита от rate limit API (throttle + anti-spam + retry на 429)
- Зеркалирует посты канала [@URGSFL](https://t.me/URGSFL) в таблицу `telegram_posts` (заменяет собой прежний вебхук на сайте, конфликтовавший с polling)

Параллельно работает FastAPI-сервис: `GET /community/farmers` отдаёт список фермеров для страницы сообщества на сайте.

## Стек

- Python 3.13, aiogram 3, FastAPI, asyncpg
- PostgreSQL (общая БД `sfl` с другими сервисами проекта)
- Docker / Docker Compose

## Структура

```
goblin-bot/
├── shared/   — конфиг и общий слой БД
├── bot/      — Telegram-бот (handlers, sfl_api, throttle)
├── api/      — FastAPI для сайта
├── migrations/  — SQL-миграции
├── Dockerfile, docker-compose.yml, requirements.txt
└── .env.example
```

## Локальный запуск

1. Применить миграции к БД `sfl`.
2. `cp .env.example .env` → заполнить токены, ключи, пароль БД.
3. `pip install -r requirements.txt`
4. `python -m bot.main` (или `docker compose up --build`)

## Деплой

GHCR + GitHub Actions → стек в Portainer на сети `shared-net`.
Подробности — в комментариях к `docker-compose.yml`.
