from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import FormData
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, TEMPLATES_DIR, engine
from .migrations import run_migrations
from .models import Course, Hostel, Payment, Setting, Student, TransportRoute, User
from .seed import seed_database

NAV_ITEMS = [
    ("dashboard", "Dashboard", "/dashboard"),
    ("students", "Students", "/students"),
    ("courses", "Courses", "/courses"),
    ("hostels", "Hostels", "/hostels"),
    ("transport", "Transport", "/transport"),
    ("payments", "Payments", "/payments"),
    ("users", "Users", "/users"),
    ("settings", "Settings", "/settings"),
]

ADMIN_ONLY_PAGES = {"users", "settings"}

MONTH_OPTIONS = [
    (1, "Jan"),
    (2, "Feb"),
    (3, "Mar"),
    (4, "Apr"),
    (5, "May"),
    (6, "Jun"),
    (7, "Jul"),
    (8, "Aug"),
    (9, "Sep"),
    (10, "Oct"),
    (11, "Nov"),
    (12, "Dec"),
]

CSRF_SESSION_KEY = "csrf_token"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def format_money(value: float | int | None) -> str:
    amount = float(value or 0)
    return f"Rs {amount:,.0f}" if amount.is_integer() else f"Rs {amount:,.2f}"


def format_date(value: date | None) -> str:
    return value.strftime("%d %b %Y") if value else "-"


def escapejs(value: object | None) -> str:
    if value is None:
        return ""
    escaped = str(value)
    escaped = escaped.replace("\\", "\\\\")
    escaped = escaped.replace("\n", "\\n")
    escaped = escaped.replace("\r", "\\r")
    escaped = escaped.replace("\u2028", "\\u2028")
    escaped = escaped.replace("\u2029", "\\u2029")
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace("'", "\\'")
    escaped = escaped.replace("</", "<\\/")
    return escaped

templates.env.filters["money"] = format_money
templates.env.filters["datefmt"] = format_date
templates.env.filters["escapejs"] = escapejs


@asynccontextmanager
async def lifespan(_: object):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        run_migrations(session)
        seed_database(session)
    yield


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


def optional_int(value: str | None) -> int | None:
    if value in (None, "", "None"):
        return None
    return int(value)


def optional_float(value: str | None) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def optional_date(value: str | None, fallback: date | None = None) -> date:
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return fallback or date.today()


def get_current_user(session: Session, request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = session.get(User, user_id)
    if not user or user.status != "Active":
        request.session.clear()
        return None
    return user


def nav_items_for(user: User | None) -> list[tuple[str, str, str]]:
    if not user:
        return []
    if user.role == "Admin":
        return NAV_ITEMS
    return [item for item in NAV_ITEMS if item[0] not in ADMIN_ONLY_PAGES]


def safe_next_path(value: str | None, fallback: str = "/dashboard") -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return fallback
    if value in {"/login", "/logout"}:
        return fallback
    return value


def is_setup_complete(session: Session) -> bool:
    settings = get_settings(session)
    return bool(settings and settings.setup_completed)


def get_csrf_token(request: Request) -> str:
    token = str(request.session.get(CSRF_SESSION_KEY, "")).strip()
    if token:
        return token

    token = secrets.token_urlsafe(32)
    request.session[CSRF_SESSION_KEY] = token
    return token


def is_valid_csrf_token(request: Request, submitted_token: object | None) -> bool:
    expected_token = str(request.session.get(CSRF_SESSION_KEY, "")).strip()
    provided_token = str(submitted_token or "").strip()
    return bool(expected_token and provided_token) and secrets.compare_digest(
        expected_token,
        provided_token,
    )


async def form_with_csrf(
    request: Request,
    failure_url: str,
) -> tuple[FormData | None, RedirectResponse | None]:
    form = await request.form()
    if not is_valid_csrf_token(request, form.get("csrf_token")):
        return None, redirect(failure_url)
    return form, None


def setup_redirect() -> RedirectResponse:
    return redirect("/setup")


def login_redirect(session: Session, request: Request) -> RedirectResponse:
    if not is_setup_complete(session):
        return setup_redirect()
    return redirect(f"/login?next={quote(request.url.path)}")


def require_user(session: Session, request: Request) -> tuple[User | None, RedirectResponse | None]:
    if not is_setup_complete(session):
        return None, setup_redirect()
    current_user = get_current_user(session, request)
    if not current_user:
        return None, login_redirect(session, request)
    return current_user, None


def require_admin(session: Session, request: Request) -> tuple[User | None, RedirectResponse | None]:
    current_user, response = require_user(session, request)
    if response:
        return None, response
    if current_user.role != "Admin":
        return None, redirect("/dashboard")
    return current_user, None


def render_public(request: Request, template_name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(
        name=template_name,
        request=request,
        context={
            "csrf_token": get_csrf_token(request),
            "today": date.today(),
            **context,
        },
    )


def render_page(
    request: Request,
    session: Session,
    current_user: User,
    template_name: str,
    active_page: str,
    **context,
) -> HTMLResponse:
    return templates.TemplateResponse(
        name=template_name,
        request=request,
        context={
            "nav_items": nav_items_for(current_user),
            "active_page": active_page,
            "csrf_token": get_csrf_token(request),
            "today": date.today(),
            "settings": get_settings(session),
            "current_user": current_user,
            **context,
        },
    )


def get_settings(session: Session) -> Setting:
    return session.get(Setting, 1)


def dashboard_metrics(session: Session) -> dict[str, float | int]:
    total_students = session.scalar(
        select(func.count()).select_from(Student).where(Student.status == "Active")
    ) or 0
    active_courses = session.scalar(
        select(func.count()).select_from(Course).where(Course.status == "Active")
    ) or 0
    total_collected = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.status == "Paid")
    ) or 0.0

    course_collected = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.service_type == "course",
            Payment.status == "Paid",
        )
    ) or 0.0
    hostel_collected = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.service_type == "hostel",
            Payment.status == "Paid",
        )
    ) or 0.0
    transport_collected = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.service_type == "transport",
            Payment.status == "Paid",
        )
    ) or 0.0

    expected_course = session.scalar(
        select(func.coalesce(func.sum(Course.fees), 0.0))
        .select_from(Student)
        .join(Course, Student.course_id == Course.id)
        .where(Student.status == "Active", Course.status == "Active")
    ) or 0.0
    expected_hostel = session.scalar(
        select(func.coalesce(func.sum(Hostel.fee_amount), 0.0))
        .select_from(Student)
        .join(Hostel, Student.hostel_id == Hostel.id)
        .where(Student.status == "Active", Hostel.status == "Active")
    ) or 0.0
    expected_transport = session.scalar(
        select(func.coalesce(func.sum(TransportRoute.fee_amount), 0.0))
        .select_from(Student)
        .join(TransportRoute, Student.transport_id == TransportRoute.id)
        .where(Student.status == "Active", TransportRoute.status == "Active")
    ) or 0.0

    pending_course = max(expected_course - course_collected, 0.0)
    pending_hostel = max(expected_hostel - hostel_collected, 0.0)
    pending_transport = max(expected_transport - transport_collected, 0.0)

    return {
        "total_students": total_students,
        "active_courses": active_courses,
        "total_collected": total_collected,
        "pending_total": pending_course + pending_hostel + pending_transport,
        "pending_course": pending_course,
        "pending_hostel": pending_hostel,
        "pending_transport": pending_transport,
    }


def payment_summary(session: Session) -> dict[str, float]:
    return {
        "total": session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.status == "Paid")
        )
        or 0.0,
        "course": session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.service_type == "course",
                Payment.status == "Paid",
            )
        )
        or 0.0,
        "hostel": session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.service_type == "hostel",
                Payment.status == "Paid",
            )
        )
        or 0.0,
        "transport": session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.service_type == "transport",
                Payment.status == "Paid",
            )
        )
        or 0.0,
    }


def student_payment_summary(session: Session, student_id: int) -> dict[str, float]:
    paid_amount = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            (Payment.student_id == student_id) & (Payment.status == "Paid")
        )
    ) or 0.0
    pending_amount = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            (Payment.student_id == student_id) & (Payment.status == "Pending")
        )
    ) or 0.0
    return {
        "paid": paid_amount,
        "pending": pending_amount,
        "total": paid_amount + pending_amount,
    }


def calculate_student_fees_and_payments(session: Session, student: Student) -> dict[str, float]:
    total_fees = 0.0
    course_fee = 0.0
    hostel_fee = 0.0
    transport_fee = 0.0

    if student.course:
        course_fee = student.course.fees
        total_fees += course_fee

    if student.hostel:
        hostel_fee = student.hostel.fee_amount
        total_fees += hostel_fee

    if student.transport_route:
        transport_fee = student.transport_route.fee_amount
        total_fees += transport_fee

    payments = student_payment_summary(session, student.id)
    remaining_balance = total_fees - payments["paid"]

    return {
        "total_fees": total_fees,
        "course_fee": course_fee,
        "hostel_fee": hostel_fee,
        "transport_fee": transport_fee,
        "paid_amount": payments["paid"],
        "pending_amount": max(remaining_balance, 0.0),
        "remaining_balance": remaining_balance,
    }


def active_lookups(session: Session) -> dict[str, list]:
    return {
        "courses": session.scalars(
            select(Course).where(Course.status == "Active").order_by(Course.name)
        ).all(),
        "hostels": session.scalars(
            select(Hostel).where(Hostel.status == "Active").order_by(Hostel.name)
        ).all(),
        "transport_routes": session.scalars(
            select(TransportRoute)
            .where(TransportRoute.status == "Active")
            .order_by(TransportRoute.route_name)
        ).all(),
        "students": session.scalars(
            select(Student).where(Student.status == "Active").order_by(Student.full_name)
        ).all(),
    }


def payment_service_maps(session: Session) -> dict[str, dict[int, str]]:
    return {
        "course": {
            course.id: course.name
            for course in session.scalars(select(Course).order_by(Course.name)).all()
        },
        "hostel": {
            hostel.id: hostel.name
            for hostel in session.scalars(select(Hostel).order_by(Hostel.name)).all()
        },
        "transport": {
            route.id: route.route_name
            for route in session.scalars(
                select(TransportRoute).order_by(TransportRoute.route_name)
            ).all()
        },
    }


def payment_service_name(
    payment: Payment, service_maps: dict[str, dict[int, str]]
) -> str:
    if str(payment.service_name or "").strip():
        return payment.service_name
    if payment.service_id is None:
        return ""
    return service_maps.get(payment.service_type, {}).get(
        payment.service_id, f"Service ID: {payment.service_id}"
    )


def validate_service_for_type(session: Session, service_type: str, service_id: int | None) -> bool:
    if service_id is None:
        return True
    if service_type == "course":
        return session.get(Course, service_id) is not None
    if service_type == "hostel":
        return session.get(Hostel, service_id) is not None
    if service_type == "transport":
        return session.get(TransportRoute, service_id) is not None
    return False


def years_for_filter() -> list[int]:
    current = date.today().year
    return list(range(current - 3, current + 3))
