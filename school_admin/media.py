from __future__ import annotations

from pathlib import Path
import time
from uuid import uuid4

from fastapi import UploadFile

from .database import UPLOADS_DIR


ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024
DEFAULT_LOGO_URL = "/static/logo.svg"


def sanitize_logo_url(logo_url: str | None, fallback: str = DEFAULT_LOGO_URL) -> str:
    value = str(logo_url or "").strip()
    if not value:
        return fallback
    if value.startswith("/static/") or value.startswith("/media/"):
        return value
    return fallback


def with_logo_cache_bust(logo_url: str | None, *, stamp: int | None = None) -> str:
    normalized_logo_url = sanitize_logo_url(logo_url)
    if not normalized_logo_url.startswith("/static/") and not normalized_logo_url.startswith("/media/"):
        return normalized_logo_url
    base_logo_url = normalized_logo_url.split("?", 1)[0]
    cache_stamp = int(stamp if stamp is not None else time.time())
    return f"{base_logo_url}?v={cache_stamp}"


async def store_uploaded_logo(upload: UploadFile) -> str:
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in ALLOWED_LOGO_EXTENSIONS:
        raise ValueError("invalid_logo_file")

    content_type = (upload.content_type or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ValueError("invalid_logo_file")

    content = await upload.read()
    if not content or len(content) > MAX_LOGO_BYTES:
        raise ValueError("invalid_logo_file")

    filename = f"logo-{uuid4().hex}{extension}"
    destination = UPLOADS_DIR / filename
    destination.write_bytes(content)
    return f"/media/{filename}"


def delete_uploaded_logo(logo_url: str) -> None:
    normalized_logo_url = sanitize_logo_url(logo_url)
    if not normalized_logo_url.startswith("/media/"):
        return
    (UPLOADS_DIR / normalized_logo_url.removeprefix("/media/")).unlink(missing_ok=True)
