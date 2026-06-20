FROM python:3.13-slim

WORKDIR /app

# Зависимости отдельным слоем для кэша
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код
COPY shared/ ./shared/
COPY bot/ ./bot/
COPY api/ ./api/

# Команда переопределяется в docker-compose (бот или api)
CMD ["python", "-m", "bot.main"]
