-- Миграция 009: хранить байты картинки поста в БД вместо временной ссылки Telegram.
-- БД: sfl  |  Запускать под пользователем с правами ALTER TABLE.
--
-- image_url раньше указывал на https://api.telegram.org/file/bot<TOKEN>/... —
-- такая ссылка "протухает" (file_path у Telegram не постоянный) и содержит
-- BOT_TOKEN в открытом виде. Теперь картинка хранится в БД и отдаётся через
-- goblin-api (GET /api/community/posts/{id}/image), image_url переиспользуется
-- под относительный путь к этому эндпоинту.

ALTER TABLE telegram_posts ADD COLUMN IF NOT EXISTS image_data BYTEA;
ALTER TABLE telegram_posts ADD COLUMN IF NOT EXISTS image_content_type TEXT;
