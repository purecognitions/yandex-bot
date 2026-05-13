import os

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ACCESS_CODE: str = os.getenv("ACCESS_CODE", "")
ADMIN_IDS: list[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

DB_PATH: str = os.getenv("DB_PATH", "bot_database.db")
BROADCAST_DELAY: float = float(os.getenv("BROADCAST_DELAY", "0.05"))
USER_QUESTIONS_LIMIT: int = int(os.getenv("USER_QUESTIONS_LIMIT", "10"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Add it to .env")
if not ACCESS_CODE:
    raise RuntimeError("ACCESS_CODE is not set. Add it to .env")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS is empty. Add at least one admin id to .env")
