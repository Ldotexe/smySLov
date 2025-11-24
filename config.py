import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
DB_URL = os.getenv("DB_URL", "postgresql+asyncpg://postgres:password@localhost:5432/postgres")