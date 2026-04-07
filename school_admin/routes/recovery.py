from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select

from school_admin.auth import hash_password
from school_admin.database import SessionLocal
from school_admin.models import User
from school_admin.utils import form_with_csrf, redirect, render_page, require_superadmin


router = APIRouter()
RECOVERY_ERROR_MESSAGES = {
    "missing_password": "Enter a new password before saving.",
    "password_short": "Use a password with at least 8 characters.",
    "invalid_user": "Choose a valid user account to reset.",
}


@router.get("/recovery/users", response_class=HTMLResponse)
async def recovery_users_page(request: Request, search: str = "", error: str = "", success: int | None = None):
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
        return render_page(
            request,
            session,
            current_user,
            "recovery_users.html",
            "recovery",
            users=session.scalars(statement).all(),
            search=search,
            error_message=RECOVERY_ERROR_MESSAGES.get(error, ""),
            success=bool(success),
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
