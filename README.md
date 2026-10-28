# goblin-bot

Telegram-бот сообщества [GoblinCodex](https://goblincodex.fun) — экосистемы для игроков Sunflower Land. Параллельно с ботом в том же процессе работает FastAPI-сервис (`goblin-api`) с данными для сайта.

## Что умеет

**Бот (личка, в группах молчит)**
- `/start` — привязка номера фермы к Telegram-аккаунту (проверка через community API SFL, подтверждение по нику, привязка 1-к-1 и без возможности сменить)
- `/tracking_lb` — включить/выключить личное отслеживание места в лидерборде тикетов; если ферма в топ-1200, раз в неделю (ночь с ВС на ПН, 03:00 МСК) сводка уходит в группу
- `/refresh_lp` — админская команда, ручной пересбор LP-лидерборда пула FLOWER/USDC
- `/refresh_farms` — админская команда, ручное обновление xp/balance/coins/ника всех фермеров сообщества (`farmers` + `farm_cache`)
- `/subscriber_notify on|off` — админская команда, уведомления в личку о подписке/отписке от канала `@URGSFL`
- `/tickets_weekly_notify on|off` — админская команда, вкл/выкл еженедельную рассылку отчёта по лидерборду тикетов в группу
- `/whois <farm_id | @ник | telegram_id>`, `/unlink <farm_id>` — админские команды: кто привязал ферму / снять привязку (с подтверждением, опционально с уведомлением пользователя). Владение фермой при привязке не проверяется — если ферма уже занята, бот показывает кнопку «🚩 Это моя ферма — сообщить админу»: админу сразу приходит карточка привязки с кнопками отвязки (жалоба — не чаще раза в 10 минут от человека)
- `/bind_notify on|off` — админская команда, уведомления в личку о каждой новой привязке фермы (по умолчанию включены)
- `/admin` — админская команда, справка со списком всех админских команд (в меню "☰" бота они не светятся)
- Проверка вступающих в чат (`JOIN_VERIFY_CHAT_ID`): на заявку бот присылает в личку ссылку на правила (`CHAT_RULES_URL`) и эмодзи-капчу; правильный ответ — согласие с правилами, затем проверка подписки на канал (`REQUIRED_CHANNEL`, по умолчанию `TELEGRAM_POSTS_CHANNEL`; не подписан — кнопки «Подписаться» / «Я подписался»), после чего заявка одобряется. 3 неверных ответа — отказ; без ответа через 12 ч напоминание (best effort — Telegram даёт писать заявителю только 5 минут, если тот не запускал бота), через 24 ч отказ. Админу приходят уведомления о каждой новой заявке, принятии, отказах, таймаутах и ошибках; о заявках в чаты без автопроверки (JOIN_VERIFY_CHAT_ID не задан или другой чат) — тоже. В группе нужно включить «Одобрение новых участников», бот — админ с правом «Приглашать пользователей»; для проверки подписки бот должен быть админом канала
- Зеркалирует посты канала [@URGSFL](https://t.me/URGSFL) в таблицу `telegram_posts` (polling, без вебхука на сайте)
- Считает подписчиков `@URGSFL` каждые 15 минут → `telegram_stats`
- Защита от rate limit SFL API (throttle + anti-spam + retry на 429)

**Фоновые задачи (`jobs/`, крутятся внутри `bot/main.py`)**
- Почасовой снэпшот топ-500 + места отслеживаемых ферм → `tickets_leaderboard.py` — **в проде выключен** (`TICKETS_LEADERBOARD_ENABLED=false` в compose): сбор делает [sfl-collector](https://github.com/Dionis404/sfl-collector) в те же таблицы под общим лимитом SFL API (~1 запрос / 5 с на IP), бот только читает снэпшоты для отчёта, `/tracking_lb` и `/tickets_check` (топ-500 переиспользуется для tracked-ферм, чтобы экономить запросы к API; фермы с рангом ниже 2000 навсегда исключаются из отдельного опроса — `farmers.tickets_excluded`; при смене главы это неактуально, поэтому `tickets_excluded` сбрасывается автоматически один раз (см. `tickets_excluded_reset_loop` в `bot/main.py`, дата `NEW_CHAPTER_START` зашита в коде — сейчас 2026-11-02 00:00 UTC, нужно обновлять на каждую новую главу)
- Еженедельная рассылка отчёта по местам → `tickets_weekly_notify.py`
- Почасовой пересбор LP-лидерборда пула FLOWER/USDC (Uniswap v3, Base, через The Graph) → `lp_leaderboard.py` (пропускается с предупреждением в логах, если `GRAPH_API_KEY`/`SUBGRAPH_ID` не заданы)
- Ежедневное обновление данных всех фермеров сообщества (`farmers.xp/balance/coins/game_username` + `farm_cache`) → `daily_refresh.py` (можно запустить и вручную/по крону — `python -m jobs.daily_refresh`)

**API для сайта (`goblin-api`, доступен только внутри docker-сети `shared-net`)**
- `GET /community/farmers` — список привязанных фермеров
- `GET /farm/{farm_id}`, `GET /farms?ids=` (не больше 100 id), `POST /farm/{farm_id}/refresh` (не чаще раза в 5 минут на ферму) — кэш данных фермы (`farm_cache`) с фоновым обновлением по TTL; запросы к SFL идут через общий троттл и ограниченную очередь, несуществующие фермы на час попадают в отрицательный кэш
- `GET /lp/leaderboard` — топ-500 LP-провайдеров пула FLOWER/USDC
- `GET /api/tickets/top500` — снэпшот топ-500 лидерборда тикетов, с историческим срезом через `?at=`; подробности — [docs/tickets-leaderboard-api.md](docs/tickets-leaderboard-api.md)
- `GET /api/auctions?upcoming=true` / `?history=true&limit=&item_name=` — список предстоящих/прошедших аукционов (с фильтром по предмету для history), `GET /api/auctions/{auction_id}/results` — результаты конкретного аукциона, включая item_name/item_type и частичный leaderboard (read-only витрина, пишет отдельный сервис `auctioneer-bot`; полной истории ставок нет — Community API отдаёт только частичный финальный снимок)

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

1. Применить миграции к БД `sfl`: `python -m shared.migrate` (применяет только новые, учёт в таблице `goblin_bot_migrations` — не `schema_migrations`, она в общей БД занята другим сервисом). На сервере это делает одноразовый сервис `migrate` в `docker-compose.yml` — бот и API стартуют только после его успешного завершения, руками миграции применять не нужно.
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
