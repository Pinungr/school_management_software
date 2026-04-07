from __future__ import annotations

import socket
import threading
import time
import webbrowser

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from school_admin.config import get_session_secret
from school_admin.database import STATIC_DIR, UPLOADS_DIR, SessionLocal
from school_admin.routes.admin import router as admin_router
from school_admin.routes.auth import router as auth_router
from school_admin.routes.catalog import router as catalog_router
from school_admin.routes.core import router as core_router
from school_admin.routes.payments import router as payments_router
from school_admin.routes.recovery import router as recovery_router
from school_admin.routes.students import router as students_router
from school_admin.utils import (
    SESSION_IDLE_TIMEOUT_SECONDS,
    calculate_student_fees_and_payments,
    is_setup_complete,
    lifespan,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


app = FastAPI(title="Pinaki", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    session_cookie="schoolflow_session",
    same_site="lax",
    max_age=SESSION_IDLE_TIMEOUT_SECONDS,
)


@app.middleware("http")
async def disable_response_caching(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/media", StaticFiles(directory=str(UPLOADS_DIR)), name="media")

app.include_router(core_router)
app.include_router(auth_router)
app.include_router(recovery_router)
app.include_router(students_router)
app.include_router(catalog_router)
app.include_router(payments_router)
app.include_router(admin_router)


def startup_target_path() -> str:
    with SessionLocal() as session:
        return "/setup" if not is_setup_complete(session) else "/login"


def wait_for_server(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.2)
    return False


def open_browser_when_ready(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    if wait_for_server(host, port):
        webbrowser.open(f"http://{host}:{port}{startup_target_path()}", new=2)


if __name__ == "__main__":
    import uvicorn

    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    uvicorn.run("main:app", host=DEFAULT_HOST, port=DEFAULT_PORT, reload=False)
