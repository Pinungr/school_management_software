from __future__ import annotations

from urllib.parse import urlencode
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select

from school_admin.auth import hash_password
from school_admin.database import SessionLocal
from school_admin.models import User
from school_admin.utils import form_with_csrf, redirect, render_page, require_superadmin


router = APIRouter()
LIST_PAGE_SIZE = 10
RECOVERY_ERROR_MESSAGES = {
    "missing_password": "Enter a new password before saving.",
    "password_short": "Use a password with at least 8 characters.",
    "invalid_user": "Choose a valid user account to reset.",
}


@router.get("/recovery/users", response_class=HTMLResponse)
async def recovery_users_page(
    request: Request,
    search: str = "",
    page: int = 1,
    error: str = "",
    success: int | None = None,
):
    with SessionLocal() as session:
        current_user, response = require_superadmin(session, request)
        if response:
            return response
        statement = (
            select(User)
            .where(User.role != "SuperAdmin")
            .order_by(User.role.asc(), User.full_name.asc(), User.id.asc())
        )
        if search.strip():
            query = search.strip()
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

        pagination_params = {"page": page}
        if search.strip():
            pagination_params["search"] = search.strip()
        if success:
            pagination_params["success"] = success

        return render_page(
            request,
            session,
            current_user,
            "recovery_users.html",
            "recovery",
            users=users,
            search=search,
            error_message=RECOVERY_ERROR_MESSAGES.get(error, ""),
            success=bool(success),
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


@router.post("/recovery/users/{user_id}/reset-password")
async def reset_user_password(user_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_superadmin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/recovery/users")
        if response:
            return response
        user = session.get(User, user_id)
        if not user or user.role == "SuperAdmin":
            return redirect("/recovery/users?error=invalid_user")
        new_password = str(form.get("new_password", ""))
        if not new_password:
            return redirect("/recovery/users?error=missing_password")
        if len(new_password) < 8:
            return redirect("/recovery/users?error=password_short")
        user.password_hash = hash_password(new_password)
        session.commit()
    return redirect("/recovery/users?success=1")


@router.post("/recovery/users/{user_id}/toggle-status")
async def toggle_user_status(user_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_superadmin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/recovery/users")
        if response:
            return response
        user = session.get(User, user_id)
        if not user or user.role == "SuperAdmin":
            return redirect("/recovery/users?error=invalid_user")

        # Toggle status
        if user.status == "Active":
            user.status = "Inactive"
        else:
            user.status = "Active"

        session.commit()
    return redirect("/recovery/users?success=1")
