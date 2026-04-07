from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


APP_NAME = "Pinaki"
LEGACY_APP_DATA_DIR_NAMES = ("SchoolFlow",)


if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    RESOURCE_DIR = Path(__file__).resolve().parent.parent

BASE_DIR = RESOURCE_DIR
TEMPLATES_DIR = RESOURCE_DIR / "templates"
STATIC_DIR = RESOURCE_DIR / "static"

def resolve_app_data_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return BASE_DIR

    local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    preferred_dir = local_app_data / APP_NAME
    if preferred_dir.exists():
        return preferred_dir

    for legacy_name in LEGACY_APP_DATA_DIR_NAMES:
        legacy_dir = local_app_data / legacy_name
        if legacy_dir.exists():
            return legacy_dir

    return preferred_dir


APP_DATA_DIR = resolve_app_data_dir()

DATA_DIR = APP_DATA_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR = APP_DATA_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH = DATA_DIR / "school.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
