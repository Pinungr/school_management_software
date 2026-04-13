from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from school_admin.database import SessionLocal
from school_admin.utils import (
    dashboard_metrics,
    form_with_csrf,
    get_current_user,
    home_path_for_user,
    is_setup_complete,
    redirect,
    render_page,
    require_user,
    setup_redirect,
)


router = APIRouter()


def logout_and_redirect(request: Request) -> RedirectResponse:
    request.session.clear()
    return redirect("/login")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> RedirectResponse:
    with SessionLocal() as session:
        if not is_setup_complete(session):
            return setup_redirect(session)
        current_user = get_current_user(session, request)
        return redirect(home_path_for_user(current_user) if current_user else "/login")


@router.get("/logout")
async def logout_page(request: Request):
    return logout_and_redirect(request)


@router.post("/logout")
async def logout(request: Request):
    _, response = await form_with_csrf(request, "/dashboard")
    if response:
        return response
    return logout_and_redirect(request)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        return render_page(
            request,
            session,
            current_user,
            "dashboard.html",
            "dashboard",
            metrics=dashboard_metrics(session),
        )
