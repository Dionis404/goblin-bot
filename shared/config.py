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
API_RATE_PER_SEC = float(os.environ.get("API_RATE_PER_SEC", "2"))    # запросов/сек к SFL API
API_CONCURRENCY = int(os.environ.get("API_CONCURRENCY", "1"))         # одновременных запросов
USER_COOLDOWN_SEC = float(os.environ.get("USER_COOLDOWN_SEC", "5"))   # пауза между запросами одного юзера
API_MAX_RETRIES = int(os.environ.get("API_MAX_RETRIES", "3"))         # повторы при 429
API_RETRY_BACKOFF = float(os.environ.get("API_RETRY_BACKOFF", "2"))   # базовая пауза backoff, сек

# --- API (FastAPI) ---
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
