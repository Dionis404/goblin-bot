FROM python:3.13-slim

WORKDIR /app

# Зависимости отдельным слоем для кэша
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код
COPY shared/ ./shared/
COPY bot/ ./bot/
COPY api/ ./api/
COPY jobs/ ./jobs/

# Не root: при RCE в зависимостях у процесса не будет прав root в контейнере
RUN useradd --system --no-create-home app
USER app

# Команда переопределяется в docker-compose (бот или api)
CMD ["python", "-m", "bot.main"]
