from __future__ import annotations

from datetime import date
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select

from school_admin.auth import hash_password, verify_password
from school_admin.database import SessionLocal
from school_admin.media import (
    DEFAULT_LOGO_URL,
    delete_uploaded_logo,
    sanitize_logo_url,
    store_uploaded_logo,
)
from school_admin.models import User
from school_admin.utils import (
    form_with_csrf,
    get_current_user,
    get_settings,
    home_path_for_user,
    is_setup_complete,
    redirect,
    render_public,
    safe_next_path,
    start_authenticated_session,
    setup_redirect,
    is_terms_accepted,
)


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: int | None = None,
    csrf: int | None = None,
    next: str | None = None,
    setup: int | None = None,
):
    with SessionLocal() as session:
        if not is_setup_complete(session):
            return setup_redirect(session)
        current_user = get_current_user(session, request)
        if current_user:
            return redirect(home_path_for_user(current_user))
        return render_public(
            request,
            "login.html",
            settings=get_settings(session),
            error=bool(error),
            csrf_error=bool(csrf),
            setup_success=bool(setup),
            next_path=safe_next_path(next, "/dashboard"),
        )


@router.post("/login")
async def login_submit(request: Request):
    form, response = await form_with_csrf(request, "/login?csrf=1")
    if response:
        return response
    next_path = safe_next_path(str(form.get("next_path", "/dashboard")))
    identifier = str(form.get("identifier", "")).strip().lower()
    password = str(form.get("password", ""))
    with SessionLocal() as session:
        if not is_setup_complete(session):
            return setup_redirect()
        user = session.scalar(
            select(User).where(
                or_(
                    User.username == identifier,
                    User.email == identifier,
                )
            )
        )
        if not user or user.status != "Active" or not verify_password(password, user.password_hash):
            return redirect(f"/login?error=1&next={quote(next_path)}")
        start_authenticated_session(request, user.id)
    return redirect(home_path_for_user(user) if user.role == "SuperAdmin" else next_path)


@router.get("/setup/terms", response_class=HTMLResponse)
async def setup_terms_page(request: Request, error: str = ""):
    with SessionLocal() as session:
        if is_terms_accepted(session):
            return setup_redirect(session)
        return render_public(request, "setup_terms.html", error_code=error)


@router.post("/setup/terms")
async def setup_terms_submit(request: Request):
    form, response = await form_with_csrf(request, "/setup/terms")
    if response:
        return response
    if not form.get("accept_terms"):
        return redirect("/setup/terms?error=accept_required")
    with SessionLocal() as session:
        settings = get_settings(session)
        settings.terms_accepted = True
        settings.terms_accepted_at = date.today()
        session.commit()
    return redirect("/setup")


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, error: str = ""):
    with SessionLocal() as session:
        if not is_terms_accepted(session):
            return setup_redirect(session)
        if is_setup_complete(session):
            current_user = get_current_user(session, request)
            return redirect(home_path_for_user(current_user) if current_user else "/login")
        settings = get_settings(session)
        admin_user = session.scalar(select(User).where(User.role == "Admin").order_by(User.id))
        return render_public(
            request,
            "setup.html",
            settings=settings,
            error_code=error,
            admin_full_name=(admin_user.full_name if admin_user else "System Administrator"),
            admin_email=(admin_user.email if admin_user else ""),
            admin_username=(admin_user.username if admin_user else "admin"),
        )


@router.post("/setup")
async def setup_submit(request: Request):
    form, response = await form_with_csrf(request, "/setup?error=csrf")
    if response:
        return response
    with SessionLocal() as session:
        if not is_terms_accepted(session):
            return setup_redirect(session)
        if is_setup_complete(session):
            current_user = get_current_user(session, request)
            return redirect(home_path_for_user(current_user) if current_user else "/login")

        settings = get_settings(session)
        school_name = str(form.get("school_name", "")).strip()
        school_email = str(form.get("school_email", "")).strip().lower()
        phone_number = str(form.get("phone_number", "")).strip()
        address = str(form.get("address", "")).strip()
        existing_logo_url = sanitize_logo_url(
            form.get("existing_logo_url"),
            fallback=sanitize_logo_url(settings.logo_url, DEFAULT_LOGO_URL),
        )
        logo_url = existing_logo_url
        logo_file = form.get("logo_file")
        admin_full_name = str(form.get("admin_full_name", "")).strip()
        admin_email = str(form.get("admin_email", "")).strip().lower()
        admin_username = str(form.get("admin_username", "")).strip().lower()
        admin_password = str(form.get("admin_password", ""))
        confirm_password = str(form.get("confirm_password", ""))

        if not school_name:
            return redirect("/setup?error=school_name_required")
        if not admin_username:
            return redirect("/setup?error=username_required")
        if not admin_full_name:
            return redirect("/setup?error=full_name_required")
        if not admin_email:
            return redirect("/setup?error=email_required")
        if len(admin_password) < 8:
            return redirect("/setup?error=password_short")
        if admin_password != confirm_password:
            return redirect("/setup?error=password_mismatch")
        if isinstance(logo_file, UploadFile) or getattr(logo_file, "filename", "").strip():
            try:
                logo_url = await store_uploaded_logo(logo_file)
            except ValueError:
                return redirect("/setup?error=invalid_logo_file")
            if logo_url != existing_logo_url:
                delete_uploaded_logo(existing_logo_url)

        admin_user = session.scalar(select(User).where(User.role == "Admin").order_by(User.id))
        if admin_user is None:
            admin_user = User(
                full_name="System Administrator",
                username="admin",
                email="admin@school.local",
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role="Admin",
                status="Active",
            )
            session.add(admin_user)
            session.flush()

        username_conflict = session.scalar(
            select(User).where((User.username == admin_username) & (User.id != admin_user.id))
        )
        if username_conflict:
            return redirect("/setup?error=username_taken")
        email_conflict = session.scalar(
            select(User).where((User.email == admin_email) & (User.id != admin_user.id))
        )
        if email_conflict:
            return redirect("/setup?error=email_taken")

        settings.school_name = school_name
        settings.school_email = school_email or settings.school_email
        settings.phone_number = phone_number or settings.phone_number
        settings.address = address or settings.address
        settings.logo_url = logo_url
        settings.setup_completed = True
        admin_user.full_name = admin_full_name
        admin_user.username = admin_username
        admin_user.email = admin_email
        admin_user.password_hash = hash_password(admin_password)
        admin_user.status = "Active"

        session.commit()
        request.session.clear()
    return redirect("/login?setup=1")
