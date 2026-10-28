import os

# Локальный запуск: подхватываем .env, если установлен python-dotenv.
# В Docker переменные приходят через env_file, dotenv не требуется.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Telegram ---
# Обязателен для bot/main.py; api/main.py его не требует.
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TELEGRAM_PROXY = os.environ.get("TELEGRAM_PROXY", "").strip() or None

# --- PostgreSQL (postgres-main, БД sfl) ---
DB_HOST = os.environ.get("DB_HOST", "postgres-main")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "sfl")
DB_USER = os.environ.get("DB_USER", "goblin")
DB_PASSWORD = os.environ.get("DB_PASSWORD")

# Канал, посты которого зеркалируются в telegram_posts (без @)
TELEGRAM_POSTS_CHANNEL = os.environ.get("TELEGRAM_POSTS_CHANNEL", "URGSFL")

# --- SFL API ---
SFL_API_BASE = os.environ.get("SFL_API_BASE", "https://api.sunflower-land.com")
# Ключ авторизации community API (передаётся в заголовке x-api-key)
SFL_API_KEY = os.environ.get("SFL_API_KEY", "").strip() or None
# Прокси для запросов к SFL API. Если не задан — берём тот же, что для Telegram.
SFL_PROXY = os.environ.get("SFL_PROXY", "").strip() or TELEGRAM_PROXY
# Ссылка на ферму для отображения
FARM_URL_TEMPLATE = os.environ.get(
    "FARM_URL_TEMPLATE", "https://sunflower-land.com/play/#/visit/{farm_id}"
)

# --- Защита от rate limit / спама ---
# Консервативные значения (точный лимит SFL API неизвестен).
# Лимит community API — по IP (~1 запрос / 5 с, при перегрузе 1 / 10 с) и общий
# для всех сервисов на VPS (бот, goblin-api, sfl-collector). 0.15 = не чаще
# одного запроса в ~6.7 с из этого процесса.
API_RATE_PER_SEC = float(os.environ.get("API_RATE_PER_SEC", "0.15"))  # запросов/сек к SFL API
API_CONCURRENCY = int(os.environ.get("API_CONCURRENCY", "1"))         # одновременных запросов
USER_COOLDOWN_SEC = float(os.environ.get("USER_COOLDOWN_SEC", "5"))   # пауза между запросами одного юзера
API_MAX_RETRIES = int(os.environ.get("API_MAX_RETRIES", "3"))         # повторы при 429
API_RETRY_BACKOFF = float(os.environ.get("API_RETRY_BACKOFF", "2"))   # базовая пауза backoff, сек

# --- API (FastAPI) ---
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))

# --- Администраторы бота (доступ к служебным командам, например /refresh_lp) ---
ADMIN_TELEGRAM_IDS = {
    int(x) for x in os.environ.get("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()
}

# --- Уведомления о подписке/отписке от канала @URGSFL ---
# Кому в личку слать уведомления и кто командой /subscriber_notify управляет тогглом.
# Берём первого (единственного) администратора из ADMIN_TELEGRAM_IDS — отдельная
# переменная не нужна, пока админ один.
NOTIFY_ADMIN_TELEGRAM_ID = next(iter(ADMIN_TELEGRAM_IDS), None)

# --- Лидерборд тикетов SFL (ticket_leaderboard_snapshots) ---
# Группа, куда шлётся еженедельное сравнение мест (ночь с ВС на ПН, 03:00 МСК).
TICKETS_NOTIFY_CHAT_ID = os.environ.get("TICKETS_NOTIFY_CHAT_ID", "").strip() or None
# Пауза между запросами к разным фермам в почасовом сборе — у community API
# (/community/data?type=ticketLeaderboard) жёсткий лимит, 0.5с даёт сплошной 429.
TICKETS_DELAY_BETWEEN_FARMS_SEC = float(os.environ.get("TICKETS_DELAY_BETWEEN_FARMS_SEC", "6"))
# Почасовой сбор лидерборда тикетов (top500_snapshots + места отслеживаемых ферм).
# Перенесён в sfl-collector: там он выполняется под общим лимитом API.
# Выключать здесь, когда sfl-collector запущен с TICKETS_ENABLED=true —
# иначе в top500_snapshots будут двойные снимки. Таблицы те же, поэтому
# еженедельный отчёт и /tracking_lb продолжают работать без изменений.
TICKETS_LEADERBOARD_ENABLED = os.environ.get(
    "TICKETS_LEADERBOARD_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}

# --- Уведомления о новых версиях игры (jobs/game_update_notify.py) ---
# Чат, куда шлётся сообщение о свежем релизе sunflower-land. Отдельная
# переменная (не переиспользуем TICKETS_NOTIFY_CHAT_ID впрямую), но по
# умолчанию — тот же чат, что и для лидерборда тикетов.
GAME_UPDATE_NOTIFY_CHAT_ID = (
    os.environ.get("GAME_UPDATE_NOTIFY_CHAT_ID", "").strip() or TICKETS_NOTIFY_CHAT_ID
)
# Atom-фид релизов игры и частота опроса.
GAME_UPDATE_FEED_URL = os.environ.get(
    "GAME_UPDATE_FEED_URL", "https://github.com/sunflower-land/sunflower-land/releases.atom"
)
GAME_UPDATE_POLL_INTERVAL_SEC = int(os.environ.get("GAME_UPDATE_POLL_INTERVAL_SEC", "60"))

# --- AI-перевод changelog'а на русский (OpenAI-совместимый эндпоинт) ---
# По умолчанию — routerai.ru (тот же провайдер, что и ROUTERAI_API_KEY для
# остальных AI-задач в проекте); можно указать любой OpenAI-совместимый base URL.
# Ключ по умолчанию берём из уже существующего ROUTERAI_API_KEY — отдельно
# задавать не обязательно.
AI_TRANSLATE_API_BASE = os.environ.get("AI_TRANSLATE_API_BASE", "https://routerai.ru/api/v1")
AI_TRANSLATE_API_KEY = (
    os.environ.get("AI_TRANSLATE_API_KEY", "").strip()
    or os.environ.get("ROUTERAI_API_KEY", "").strip()
    or None
)
AI_TRANSLATE_MODEL = os.environ.get("AI_TRANSLATE_MODEL", "google/gemini-2.5-flash")

# --- Проверка вступающих в чат (bot/join_verify.py) ---
# Чат, заявки на вступление в который бот обрабатывает: шлёт правила и
# эмодзи-капчу, после правильного ответа одобряет. Пусто = функция выключена,
# заявки ждут ручного решения админа, как раньше.
JOIN_VERIFY_CHAT_ID = int(os.environ["JOIN_VERIFY_CHAT_ID"]) if os.environ.get("JOIN_VERIFY_CHAT_ID", "").strip() else None
# Ссылка на правила чата на сайте
CHAT_RULES_URL = os.environ.get("CHAT_RULES_URL", "").strip() or None
# Канал (без @), подписка на который обязательна для вступления. По умолчанию —
# тот же канал, что зеркалируется в telegram_posts. Бот должен быть его админом,
# иначе Telegram не отдаёт статус участника. Пусто и без TELEGRAM_POSTS_CHANNEL —
# проверка подписки выключена.
REQUIRED_CHANNEL = (
    os.environ.get("REQUIRED_CHANNEL", "").strip().lstrip("@") or TELEGRAM_POSTS_CHANNEL or None
)
