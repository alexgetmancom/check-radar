import os
from pathlib import Path

# Чтение из переменных окружения с фолбеком для локальной разработки
BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "дефолтный_токен")
ALLOWED_USERS_RAW: str = os.environ.get("ALLOWED_USERS", "7629366167,1260959328")
ALLOWED_USERS: set[int] = {int(uid.strip()) for uid in ALLOWED_USERS_RAW.split(",") if uid.strip()}

TG_API_URL: str = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Базовые пути на Pathlib
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DB_FILE: str = str(BASE_DIR / "data" / "receipts.db")
CREDENTIALS_FILE: str = str(BASE_DIR / "credentials.json")

BASE_URL: str = "https://lkdr.nalog.ru/api"
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BOT_INSTANCE = None
EVENT_LOOP = None
