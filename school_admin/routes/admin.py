from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from school_admin.auth import hash_password
from school_admin.backup_restore import BackupRestoreError, create_backup_archive, restore_backup_archive
from school_admin.database import SessionLocal
from school_admin.data_repair import (
    DataRepairError,
    build_data_repair_page,
    export_table_csv,
    get_table_spec,
    import_table_csv,
)
from school_admin.media import delete_uploaded_logo, sanitize_logo_url, store_uploaded_logo, with_logo_cache_bust
from school_admin.models import User
from school_admin.permissions import has_permission
from school_admin.utils import form_with_csrf, get_settings, redirect, render_page, require_admin


router = APIRouter()
LIST_PAGE_SIZE = 10
USER_STATUSES = {"Active", "Inactive"}
FEE_FREQUENCIES = {"Monthly", "Quarterly", "Half-Yearly", "Yearly"}
CURRENCIES = {"INR (Rs)", "USD ($)", "EUR (EUR)"}
TIMEZONES = {"Asia/Kolkata (IST)", "UTC", "Asia/Dubai (GST)"}
DATA_REPAIR_ERROR_MESSAGES = {
    "missing_import_file": "Choose a CSV or backup file before importing.",
    "invalid_import_file": "The selected import file is not valid for this table.",
    "duplicate_or_invalid_data": "The import or edit contains duplicate or invalid values.",
    "record_not_found": "The selected record could not be found.",
    "missing_required_field": "Fill in the required fields before saving.",
    "invalid_numeric_value": "Enter a valid numeric value before saving.",
    "invalid_lookup": "Choose valid linked records for the selected row.",
    "invalid_status": "Choose a valid status before saving.",
    "invalid_method": "Choose a valid payment method before saving.",
    "invalid_frequency": "Choose a valid frequency before saving.",
    "invalid_category": "Choose a valid fee category before saving.",
    "invalid_role": "Choose a valid user role before saving.",
    "invalid_service_type": "Choose a valid payment service type before saving.",
    "last_admin": "Keep at least one active administrator account in the system.",
    "invalid_backup_file": "Choose a valid Pinaki backup file to restore.",
}
DATA_REPAIR_SUCCESS_MESSAGES = {
    "row_saved": "Row updated successfully.",
    "table_imported": "Table imported successfully.",
    "database_imported": "Database backup restored successfully.",
}


def data_repair_redirect(table: str, *, search: str = "", edit: int | None = None, error: str = "", success: str = ""):
    query_items: list[tuple[str, str | int]] = [("table", table)]
    if search.strip():
        query_items.append(("search", search.strip()))
    if edit is not None:
        query_items.append(("edit", edit))
    if error:
        query_items.append(("error", error))
    if success:
        query_items.append(("success", success))
    return redirect(f"/settings/data-repair?{urlencode(query_items)}")


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    search: str = "",
    page: int = 1,
    create: int | None = None,
    edit: int | None = None,
    error: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        statement = select(User).where(User.role != "SuperAdmin").order_by(User.id.desc())
        query = search.strip()
        if query:
            statement = statement.where(
                or_(
                    User.full_name.contains(query),
                    User.username.contains(query),
                    User.email.contains(query),
                    User.role.contains(query),
                )
            )
        
        page = max(page, 1)
        total_items = session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        total_pages = max((total_items + LIST_PAGE_SIZE - 1) // LIST_PAGE_SIZE, 1)
        page = min(page, total_pages)
        
        users = session.scalars(
            statement.limit(LIST_PAGE_SIZE).offset((page - 1) * LIST_PAGE_SIZE)
        ).all()
        
        selected_user = session.get(User, edit) if edit else None
        if selected_user and selected_user.role == "SuperAdmin":
            selected_user = None
            
        pagination_params = {"page": page}
        if query:
            pagination_params["search"] = query

        return render_page(
            request,
            session,
            current_user,
            "users.html",
            "users",
            users=users,
            form_mode="create" if create else ("edit" if edit else None),
            form_user=selected_user,
            search=search,
            error_code=error,
            pagination={
                "page": page,
                "page_size": LIST_PAGE_SIZE,
                "total_items": total_items,
                "total_pages": total_pages,
                "has_previous": page > 1,
                "has_next": page < total_pages,
                "previous_query": urlencode({**pagination_params, "page": page - 1}) if page > 1 else "",
                "next_query": urlencode({**pagination_params, "page": page + 1}) if page < total_pages else "",
                "page_start": ((page - 1) * LIST_PAGE_SIZE) + 1 if total_items else 0,
                "page_end": min(page * LIST_PAGE_SIZE, total_items),
            },
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


@router.get("/settings/data-repair", response_class=HTMLResponse)
async def data_repair_page(
    request: Request,
    table: str = "students",
    search: str = "",
    page: int = 1,
    edit: int | None = None,
    error: str = "",
    success: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        return render_page(
            request,
            session,
            current_user,
            "data_repair.html",
            "settings",
            error_message=DATA_REPAIR_ERROR_MESSAGES.get(error, ""),
            success_message=DATA_REPAIR_SUCCESS_MESSAGES.get(success, ""),
            **build_data_repair_page(
                session,
                table_key=table,
                search=search,
                page=page,
                edit_id=edit,
            ),
        )


@router.post("/settings/data-repair/{table}/{row_id}/update")
async def update_data_repair_row(table: str, row_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        failure_url = f"/settings/data-repair?table={get_table_spec(table).key}&edit={row_id}"
        form, response = await form_with_csrf(request, failure_url)
        if response:
            return response
        search = str(form.get("search", "")).strip()
        form_data = {key: value for key, value in form.items()}
        try:
            from school_admin.data_repair import update_row_from_form

            update_row_from_form(session, table, row_id, form_data)
        except DataRepairError as exc:
            return data_repair_redirect(
                get_table_spec(table).key,
                search=search,
                edit=row_id,
                error=exc.args[0],
            )
    return data_repair_redirect(get_table_spec(table).key, search=search, success="row_saved")


@router.get("/settings/data-repair/{table}/export")
async def export_data_repair_table(table: str, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        file_bytes, filename = export_table_csv(session, table)
    return Response(
        content=file_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/settings/data-repair/{table}/import")
async def import_data_repair_table(table: str, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        failure_url = f"/settings/data-repair?table={get_table_spec(table).key}"
        form, response = await form_with_csrf(request, failure_url)
        if response:
            return response
        search = str(form.get("search", "")).strip()
        import_file = form.get("import_file")
        if not getattr(import_file, "filename", "").strip():
            return data_repair_redirect(get_table_spec(table).key, search=search, error="missing_import_file")
        file_bytes = await import_file.read()
        try:
            import_table_csv(session, table, file_bytes)
        except DataRepairError as exc:
            return data_repair_redirect(get_table_spec(table).key, search=search, error=exc.args[0])
    return data_repair_redirect(get_table_spec(table).key, search=search, success="table_imported")


@router.post("/settings/data-repair/database/export")
async def export_data_repair_database(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/settings/data-repair?table=students")
        if response:
            return response
    archive_bytes, filename = create_backup_archive()
    return Response(
        content=archive_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/settings/data-repair/database/import")
async def import_data_repair_database(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/settings/data-repair?table=students")
        if response:
            return response
        backup_file = form.get("backup_file")
        if not getattr(backup_file, "filename", "").strip():
            return data_repair_redirect("students", error="missing_import_file")
        archive_bytes = await backup_file.read()
    try:
        restore_backup_archive(archive_bytes)
    except BackupRestoreError as exc:
        return data_repair_redirect("students", error=exc.args[0])
    return data_repair_redirect("students", success="database_imported")


@router.post("/settings")
async def update_settings(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        if not has_permission(current_user, "settings.update"):
            return redirect("/dashboard")
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
        settings.logo_url = with_logo_cache_bust(logo_url)
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
        media_type="application/octet-stream",
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
        if not getattr(backup_file, "filename", "").strip():
            return redirect("/settings?error=backup_file_required")
        archive_bytes = await backup_file.read()

    try:
        restore_backup_archive(archive_bytes)
    except BackupRestoreError as exc:
        return redirect(f"/settings?error={exc.args[0]}")

    return redirect("/settings?success=restore_completed")
