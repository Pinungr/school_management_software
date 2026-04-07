from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from school_admin.auth import hash_password
from school_admin.backup_restore import BackupRestoreError, create_backup_archive, restore_backup_archive
from school_admin.database import SessionLocal
from school_admin.media import delete_uploaded_logo, sanitize_logo_url, store_uploaded_logo
from school_admin.models import User
from school_admin.utils import form_with_csrf, get_settings, redirect, render_page, require_admin


router = APIRouter()
USER_STATUSES = {"Active", "Inactive"}
FEE_FREQUENCIES = {"Monthly", "Quarterly", "Half-Yearly", "Yearly"}
CURRENCIES = {"INR (Rs)", "USD ($)", "EUR (EUR)"}
TIMEZONES = {"Asia/Kolkata (IST)", "UTC", "Asia/Dubai (GST)"}


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
    error: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        statement = select(User).where(User.role != "SuperAdmin").order_by(User.id.desc())
        if search.strip():
            statement = statement.where(
                or_(
                    User.full_name.contains(search.strip()),
                    User.username.contains(search.strip()),
                    User.email.contains(search.strip()),
                    User.role.contains(search.strip()),
                )
            )
        selected_user = session.get(User, edit) if edit else None
        if selected_user and selected_user.role == "SuperAdmin":
            selected_user = None
        return render_page(
            request,
            session,
            current_user,
            "users.html",
            "users",
            users=session.scalars(statement).all(),
            form_mode="create" if create else ("edit" if edit else None),
            form_user=selected_user,
            search=search,
            error_code=error,
        )


@router.post("/users/create")
async def create_user(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/users")
        if response:
            return response
        full_name = str(form.get("full_name", "")).strip()
        username = str(form.get("username", "")).strip().lower()
        email = str(form.get("email", "")).strip().lower()
        password = str(form.get("password", ""))
        status = str(form.get("status", "Active")).strip()
        if not full_name or not username or not email:
            return redirect("/users?create=1&error=missing_fields")
        if len(password) < 8:
            return redirect("/users?create=1&error=password_short")
        if status not in USER_STATUSES:
            return redirect("/users?create=1&error=invalid_status")
        session.add(
            User(
                full_name=full_name,
                username=username,
                email=email,
                password_hash=hash_password(password),
                role="Clerk",
                status=status,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect("/users?create=1&error=duplicate")
    return redirect("/users")


@router.post("/users/{user_id}/edit")
async def edit_user(user_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/users")
        if response:
            return response
        user = session.get(User, user_id)
        if not user or user.role == "SuperAdmin":
            return redirect("/users")
        full_name = str(form.get("full_name", "")).strip()
        username = str(form.get("username", "")).strip().lower()
        email = str(form.get("email", "")).strip().lower()
        status = str(form.get("status", "Active")).strip()
        if not full_name or not username or not email:
            return redirect(f"/users?edit={user_id}&error=missing_fields")
        if status not in USER_STATUSES:
            return redirect(f"/users?edit={user_id}&error=invalid_status")
        active_admin_count = session.scalar(
            select(func.count()).select_from(User).where(
                User.role == "Admin",
                User.status == "Active",
            )
        ) or 0
        removing_last_active_admin = (
            user.role == "Admin"
            and user.status == "Active"
            and status != "Active"
            and active_admin_count <= 1
        )
        if removing_last_active_admin:
            return redirect(f"/users?edit={user_id}&error=last_admin")
        user.full_name = full_name
        user.username = username
        user.email = email
        user.role = "Admin" if user.role == "Admin" else "Clerk"
        user.status = status
        password = str(form.get("password", "")).strip()
        if password:
            if len(password) < 8:
                return redirect(f"/users?edit={user_id}&error=password_short")
            user.password_hash = hash_password(password)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect(f"/users?edit={user_id}&error=duplicate")
    return redirect("/users")


@router.post("/users/{user_id}/delete")
async def delete_user(user_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/users")
        if response:
            return response
        if current_user.id == user_id:
            return redirect("/users")
        user = session.get(User, user_id)
        if user and user.role == "SuperAdmin":
            return redirect("/users")
        active_admin_count = session.scalar(
            select(func.count()).select_from(User).where(
                User.role == "Admin",
                User.status == "Active",
            )
        ) or 0
        if user and user.role == "Admin" and user.status == "Active" and active_admin_count <= 1:
            return redirect("/users?error=last_admin")
        if user:
            session.delete(user)
            session.commit()
    return redirect("/users")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, error: str = "", success: str = ""):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        return render_page(
            request,
            session,
            current_user,
            "settings.html",
            "settings",
            error_code=error,
            success_code=success,
        )


@router.post("/settings")
async def update_settings(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/settings")
        if response:
            return response
        settings = get_settings(session)
        school_name = str(form.get("school_name", "")).strip()
        fee_frequency = str(form.get("fee_frequency", "Monthly")).strip()
        currency = str(form.get("currency", "INR (Rs)")).strip()
        timezone = str(form.get("timezone", "Asia/Kolkata (IST)")).strip()
        if not school_name:
            return redirect("/settings?error=school_name_required")
        if fee_frequency not in FEE_FREQUENCIES:
            return redirect("/settings?error=invalid_fee_frequency")
        if currency not in CURRENCIES:
            return redirect("/settings?error=invalid_currency")
        if timezone not in TIMEZONES:
            return redirect("/settings?error=invalid_timezone")
        existing_logo_url = sanitize_logo_url(form.get("existing_logo_url"), settings.logo_url)
        logo_url = existing_logo_url
        logo_file = form.get("logo_file")
        if isinstance(logo_file, UploadFile) or getattr(logo_file, "filename", "").strip():
            try:
                logo_url = await store_uploaded_logo(logo_file)
            except ValueError:
                return redirect("/settings?error=invalid_logo_file")
            if logo_url != existing_logo_url:
                delete_uploaded_logo(existing_logo_url)
        settings.school_name = school_name
        settings.school_email = str(form.get("school_email", "")).strip()
        settings.phone_number = str(form.get("phone_number", "")).strip()
        settings.logo_url = logo_url
        settings.address = str(form.get("address", "")).strip()
        settings.academic_year = str(form.get("academic_year", "")).strip()
        settings.financial_year = str(form.get("financial_year", "")).strip()
        settings.fee_frequency = fee_frequency
        settings.currency = currency
        settings.timezone = timezone
        session.commit()
    return redirect("/settings")


@router.post("/settings/backup")
async def backup_settings(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/settings")
        if response:
            return response

    archive_bytes, filename = create_backup_archive()
    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/settings/restore")
async def restore_settings_backup(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/settings")
        if response:
            return response
        backup_file = form.get("backup_file")
        if not isinstance(backup_file, UploadFile) and not getattr(backup_file, "filename", "").strip():
            return redirect("/settings?error=backup_file_required")
        archive_bytes = await backup_file.read()

    try:
        restore_backup_archive(archive_bytes)
    except BackupRestoreError as exc:
        return redirect(f"/settings?error={exc.args[0]}")

    return redirect("/settings?success=restore_completed")
