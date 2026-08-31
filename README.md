# goblin-bot

Telegram-бот сообщества [GoblinCodex](https://goblincodex.fun) — экосистемы для игроков Sunflower Land. Параллельно с ботом в том же процессе работает FastAPI-сервис (`goblin-api`) с данными для сайта.

## Что умеет

**Бот (личка, в группах молчит)**
- `/start` — привязка номера фермы к Telegram-аккаунту (проверка через community API SFL, подтверждение по нику, привязка 1-к-1 и без возможности сменить)
- `/tracking_lb` — включить/выключить личное отслеживание места в лидерборде тикетов; если ферма в топ-1200, раз в неделю (ночь с ВС на ПН, 03:00 МСК) сводка уходит в группу
- `/refresh_lp` — админская команда, ручной пересбор LP-лидерборда пула FLOWER/USDC
- `/subscriber_notify on|off` — админская команда, уведомления в личку о подписке/отписке от канала `@URGSFL`
- Зеркалирует посты канала [@URGSFL](https://t.me/URGSFL) в таблицу `telegram_posts` (polling, без вебхука на сайте)
- Считает подписчиков `@URGSFL` каждые 15 минут → `telegram_stats`
- Защита от rate limit SFL API (throttle + anti-spam + retry на 429)

**Фоновые задачи (`jobs/`, крутятся внутри `bot/main.py`)**
- Почасовой снэпшот топ-500 + места отслеживаемых ферм → `tickets_leaderboard.py` (топ-500 переиспользуется для tracked-ферм, чтобы экономить запросы к API; фермы с рангом ниже 2000 навсегда исключаются из отдельного опроса — `farmers.tickets_excluded`)
- Еженедельная рассылка отчёта по местам → `tickets_weekly_notify.py`
- Сбор LP-лидерборда пула FLOWER/USDC (Uniswap v3, Base, через The Graph) → `lp_leaderboard.py`
- Батч-прогрев кэша ферм (`daily_refresh.py`) — запускается вручную/по крону, не в основном цикле бота

**API для сайта (`goblin-api`, доступен только внутри docker-сети `shared-net`)**
- `GET /community/farmers` — список привязанных фермеров
- `GET /farm/{farm_id}`, `GET /farms?ids=`, `POST /farm/{farm_id}/refresh` — кэш данных фермы (`farm_cache`) с фоновым обновлением по TTL
- `GET /lp/leaderboard` — топ-500 LP-провайдеров пула FLOWER/USDC
- `GET /api/tickets/top500` — снэпшот топ-500 лидерборда тикетов, с историческим срезом через `?at=`; подробности — [docs/tickets-leaderboard-api.md](docs/tickets-leaderboard-api.md)
- `GET /api/auctions?upcoming=true`, `GET /api/auctions/{auction_id}/results` — read-only витрина аукционов (пишет отдельный сервис `auctioneer-bot`)

## Стек

- Python 3.13, aiogram 3, FastAPI, asyncpg
- PostgreSQL (общая БД `sfl` с другими сервисами проекта)
- Docker / Docker Compose

## Структура

```
goblin-bot/
├── shared/      — конфиг, слой БД, доступ к SFL/Graph API (переиспользуется ботом, API и jobs)
├── bot/         — Telegram-бот (handlers, channel, subscriber_notify, sfl_api, throttle)
├── api/         — FastAPI для сайта (goblin-api)
├── jobs/        — фоновые задачи (лидерборды, батч-прогрев кэша)
├── migrations/  — SQL-миграции БД sfl, по порядку номеров
├── tests/       — pytest
├── docs/        — документация внешних API
├── Dockerfile, docker-compose.yml, requirements.txt
└── .env.example
```

## Локальный запуск

1. Применить миграции к БД `sfl` (по порядку, `migrations/001…` → `011…`).
2. `cp .env.example .env` → заполнить токены, ключи, пароль БД (см. комментарии в файле).
3. `pip install -r requirements.txt`
4. `python -m bot.main` (или `docker compose up --build`)

## Тесты

```
pip install -r requirements-dev.txt
pytest
```

## Деплой

GHCR + GitHub Actions ([.github/workflows/deploy.yml](.github/workflows/deploy.yml)) → стек в Portainer на сети `shared-net`. Подробности — в комментариях к `docker-compose.yml`.
