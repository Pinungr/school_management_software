from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Setting, User

DEFAULT_DEVELOPER_NAME = ""
DEFAULT_DEVELOPER_EMAIL = ""
DEFAULT_DEVELOPER_PHONE = ""


def ensure_admin_placeholder(session: Session) -> None:
    admin_user = session.scalar(select(User).where(User.role == "Admin").order_by(User.id))
    if admin_user is not None:
        return

    session.add(
        User(
            full_name="System Administrator",
            username="admin",
            email="admin@school.local",
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role="Admin",
            status="Inactive",
        )
    )


def seed_database(session: Session) -> None:
    settings = session.scalar(select(Setting).limit(1))
    if settings is None:
        session.add(
            Setting(
                id=1,
                school_name="Private School",
                school_email="info@school.com",
                phone_number="+91 9876543210",
                logo_url="/static/logo.svg",
                address="123 Education Street, City, State",
                academic_year="2026-2027",
                financial_year="2026-2027",
                fee_frequency="Monthly",
                currency="INR (Rs)",
                timezone="Asia/Kolkata (IST)",
                developer_name=DEFAULT_DEVELOPER_NAME,
                developer_email=DEFAULT_DEVELOPER_EMAIL,
                developer_phone=DEFAULT_DEVELOPER_PHONE,
                setup_completed=False,
            )
        )
    else:
        settings.setup_completed = bool(settings.setup_completed)

    ensure_admin_placeholder(session)
    session.commit()
