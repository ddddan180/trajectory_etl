import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def get_database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("请在项目根目录 .env 中设置 DATABASE_URL")
    return url