FROM python:3.13-slim

WORKDIR /app

# Зависимости отдельным слоем для кэша
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код
COPY shared/ ./shared/
COPY bot/ ./bot/
COPY jobs/ ./jobs/
COPY migrations/ ./migrations/

# Не root: при RCE в зависимостях у процесса не будет прав root в контейнере
RUN useradd --system --no-create-home app
USER app

CMD ["python", "-m", "bot.main"]
