from __future__ import annotations

import os
import secrets
from pathlib import Path

from .database import DATA_DIR


SESSION_SECRET_ENV_VAR = "SCHOOLFLOW_SESSION_SECRET"
SESSION_SECRET_FILE = DATA_DIR / "session_secret.txt"


def get_session_secret(secret_file: Path | None = None) -> str:
    configured_secret = os.getenv(SESSION_SECRET_ENV_VAR, "").strip()
    if configured_secret:
        return configured_secret

    secret_path = secret_file or SESSION_SECRET_FILE
    if secret_path.exists():
        stored_secret = secret_path.read_text(encoding="utf-8").strip()
        if stored_secret:
            return stored_secret

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    generated_secret = secrets.token_urlsafe(48)
    secret_path.write_text(generated_secret, encoding="utf-8")
    return generated_secret
