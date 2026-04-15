from __future__ import annotations

from collections import defaultdict
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import FormData
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .branding import DEVELOPER_EMAIL, DEVELOPER_NAME, DEVELOPER_PHONE
from .database import Base, DATABASE_PATH, SessionLocal, TEMPLATES_DIR, engine
from .migrations import run_migrations
from .models import Course, Fee, Hostel, Payment, Section, Setting, Student, TransportRoute, User
from .permissions import has_permission
from .seed import seed_database

NAV_ITEMS = [
    ("dashboard", "Dashboard", "/dashboard"),
    ("admissions", "Admissions", "/admissions"),
    ("students", "Students", "/students"),
    ("fees", "Fees", "/fees"),
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
RECOVERY_NAV_ITEMS = [("recovery", "Recovery", "/recovery/users")]
SUPERADMIN_HOME_PATH = "/recovery/users"
SUPERADMIN_ALLOWED_PREFIXES = ("/recovery/",)

CSRF_SESSION_KEY = "csrf_token"
SESSION_LAST_ACTIVITY_KEY = "last_activity_at"
SESSION_IDLE_TIMEOUT_SECONDS = 15 * 60
FEE_CATEGORIES = ("Admission", "Course", "Hostel", "Transport", "Other")
FEE_TARGET_TYPES = ("General", "Course", "Hostel", "Transport")
FEE_FREQUENCIES = ("One Time", "Monthly", "Quarterly", "Half-Yearly", "Yearly")


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DASHBOARD_METRICS_CACHE_TTL_SECONDS = 15
_DASHBOARD_METRICS_CACHE = {
    "signature": None,
    "computed_at": 0.0,
    "metrics": None,
}

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


def frequency_months(frequency: str | None) -> int:
    normalized_frequency = str(frequency or "One Time").strip()
    return {
        "Monthly": 1,
        "Quarterly": 3,
        "Half-Yearly": 6,
        "Yearly": 12,
    }.get(normalized_frequency, 0)


def monthly_equivalent_amount(amount: float | int | None, frequency: str | None) -> float:
    amount_value = float(amount or 0)
    months = frequency_months(frequency)
    if months <= 1:
        return amount_value
    return amount_value / months

templates.env.filters["money"] = format_money
templates.env.filters["datefmt"] = format_date
templates.env.filters["escapejs"] = escapejs
templates.env.filters["monthly_equivalent"] = monthly_equivalent_amount
templates.env.globals["has_permission"] = has_permission


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


def current_session_timestamp() -> int:
    return int(time.time())


def start_authenticated_session(request: Request, user_id: int) -> None:
    request.session.clear()
    request.session["user_id"] = user_id
    request.session[SESSION_LAST_ACTIVITY_KEY] = current_session_timestamp()


def get_current_user(session: Session, request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    last_activity = request.session.get(SESSION_LAST_ACTIVITY_KEY)
    try:
        last_activity_timestamp = int(last_activity)
    except (TypeError, ValueError):
        request.session.clear()
        return None
    if current_session_timestamp() - last_activity_timestamp > SESSION_IDLE_TIMEOUT_SECONDS:
        request.session.clear()
        return None
    user = session.get(User, user_id)
    if not user or user.status != "Active":
        request.session.clear()
        return None
    request.session[SESSION_LAST_ACTIVITY_KEY] = current_session_timestamp()
    return user


def nav_items_for(user: User | None) -> list[tuple[str, str, str]]:
    if not user:
        return []
    if user.role == "SuperAdmin":
        return RECOVERY_NAV_ITEMS
    if user.role == "Admin":
        return NAV_ITEMS
    return [item for item in NAV_ITEMS if item[0] not in ADMIN_ONLY_PAGES]


def home_path_for_user(user: User | None) -> str:
    if not user:
        return "/dashboard"
    if user.role == "SuperAdmin":
        return SUPERADMIN_HOME_PATH
    return "/dashboard"


def safe_next_path(value: str | None, fallback: str = "/dashboard") -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return fallback
    if value in {"/login", "/logout"}:
        return fallback
    return value


def is_setup_complete(session: Session) -> bool:
    settings = get_settings(session)
    return bool(settings and settings.setup_completed)


def is_terms_accepted(session: Session) -> bool:
    settings = get_settings(session)
    return bool(settings and settings.terms_accepted)


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


def setup_redirect(session: Session | None = None) -> RedirectResponse:
    if session and not is_terms_accepted(session):
        return redirect("/setup/terms")
    return redirect("/setup")


def login_redirect(session: Session, request: Request) -> RedirectResponse:
    if not is_setup_complete(session):
        return setup_redirect(session)
    return redirect(f"/login?next={quote(request.url.path, safe='')}")


def require_user(session: Session, request: Request) -> tuple[User | None, RedirectResponse | None]:
    if not is_setup_complete(session):
        return None, setup_redirect(session)
    current_user = get_current_user(session, request)
    if not current_user:
        return None, login_redirect(session, request)
    if current_user.role == "SuperAdmin" and not any(
        request.url.path.startswith(prefix) for prefix in SUPERADMIN_ALLOWED_PREFIXES
    ):
        return None, redirect(SUPERADMIN_HOME_PATH)
    return current_user, None


def require_admin(session: Session, request: Request) -> tuple[User | None, RedirectResponse | None]:
    current_user, response = require_user(session, request)
    if response:
        return None, response
    if current_user.role != "Admin":
        return None, redirect(home_path_for_user(current_user))
    return current_user, None


def require_superadmin(session: Session, request: Request) -> tuple[User | None, RedirectResponse | None]:
    current_user, response = require_user(session, request)
    if response:
        return None, response
    if current_user.role != "SuperAdmin":
        return None, redirect(home_path_for_user(current_user))
    return current_user, None


def render_public(request: Request, template_name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(
        name=template_name,
        request=request,
        context={
            "csrf_token": get_csrf_token(request),
            "today": date.today(),
            "branding": {
                "developer_name": DEVELOPER_NAME,
                "developer_email": DEVELOPER_EMAIL,
                "developer_phone": DEVELOPER_PHONE,
            },
            "session_timeout_ms": SESSION_IDLE_TIMEOUT_SECONDS * 1000,
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
            "branding": {
                "developer_name": DEVELOPER_NAME,
                "developer_email": DEVELOPER_EMAIL,
                "developer_phone": DEVELOPER_PHONE,
            },
            "session_timeout_ms": SESSION_IDLE_TIMEOUT_SECONDS * 1000,
            **context,
        },
    )


def get_settings(session: Session) -> Setting:
    return session.get(Setting, 1)


def month_difference(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 0
    return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)


def fee_cycle_count(start_date: date, frequency: str, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    if as_of < start_date:
        return 0
    normalized_frequency = str(frequency or "One Time").strip()
    if normalized_frequency == "One Time":
        return 1
    return month_difference(start_date, as_of) + 1


def current_month_amount(
    amount: float | int | None,
    frequency: str | None,
    start_date: date,
    as_of: date | None = None,
) -> float:
    as_of = as_of or date.today()
    if as_of < start_date:
        return 0.0
    normalized_frequency = str(frequency or "One Time").strip()
    if normalized_frequency == "One Time":
        return float(amount or 0) if month_difference(start_date, as_of) == 0 else 0.0
    return monthly_equivalent_amount(amount, frequency)


def is_one_time_fee(fee: Fee) -> bool:
    if str(fee.frequency or "").strip() == "One Time":
        return True
    return normalize_fee_category(fee.category) == "Admission"


def is_due_this_cycle(start_date: date, frequency: str, as_of: date | None = None) -> bool:
    as_of = as_of or date.today()
    if as_of < start_date:
        return False
    interval_months = frequency_months(frequency)
    if interval_months <= 0:
        return month_difference(start_date, as_of) == 0
    elapsed_months = month_difference(start_date, as_of)
    return elapsed_months % interval_months == 0


def cycle_index_for_frequency(start_date: date, frequency: str, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    if as_of < start_date:
        return 0
    interval_months = frequency_months(frequency)
    elapsed_months = month_difference(start_date, as_of)
    if interval_months <= 0:
        return 1
    return (elapsed_months // interval_months) + 1


def fee_applies_to_student(fee: Fee, student: Student) -> bool:
    target_type = str(fee.target_type or "General").strip()
    if target_type == "General":
        return True
    if target_type == "Course":
        return student.course_id == fee.target_id
    if target_type == "Hostel":
        return student.hostel_id == fee.target_id
    if target_type == "Transport":
        return student.transport_id == fee.target_id
    return False


def legacy_fee_items_for_student(student: Student, fees: list[Fee]) -> list[dict[str, float | int | str]]:
    fee_keys = {(fee.category, fee.target_type, fee.target_id) for fee in fees}
    legacy_items: list[dict[str, float | int | str]] = []
    if student.course and ("Course", "Course", student.course_id) not in fee_keys and student.course.fees:
        course_frequency = student.course.frequency or "Monthly"
        monthly_amount = current_month_amount(student.course.fees, course_frequency, student.joined_on)
        legacy_items.append(
            {
                "id": 0,
                "name": f"{student.course.name} Course Fee",
                "category": "Course",
                "frequency": course_frequency,
                "cycles_due": fee_cycle_count(student.joined_on, course_frequency),
                "unit_amount": float(student.course.fees or 0),
                "monthly_amount": monthly_amount,
                "current_month_amount": monthly_amount,
                "due_amount": monthly_amount * fee_cycle_count(student.joined_on, course_frequency),
                "remaining_amount": 0.0,
                "target_type": "Course",
                "target_name": student.course.name,
            }
        )
    if student.hostel and ("Hostel", "Hostel", student.hostel_id) not in fee_keys and student.hostel.fee_amount:
        hostel_frequency = "Monthly"
        monthly_amount = current_month_amount(student.hostel.fee_amount, hostel_frequency, student.joined_on)
        legacy_items.append(
            {
                "id": 0,
                "name": f"{student.hostel.name} Hostel Fee",
                "category": "Hostel",
                "frequency": hostel_frequency,
                "cycles_due": fee_cycle_count(student.joined_on, hostel_frequency),
                "unit_amount": float(student.hostel.fee_amount or 0),
                "monthly_amount": monthly_amount,
                "current_month_amount": monthly_amount,
                "due_amount": monthly_amount * fee_cycle_count(student.joined_on, hostel_frequency),
                "remaining_amount": 0.0,
                "target_type": "Hostel",
                "target_name": student.hostel.name,
            }
        )
    if (
        student.transport_route
        and ("Transport", "Transport", student.transport_id) not in fee_keys
        and student.transport_route.fee_amount
    ):
        frequency = student.transport_route.frequency or "Monthly"
        monthly_amount = current_month_amount(student.transport_route.fee_amount, frequency, student.joined_on)
        legacy_items.append(
            {
                "id": 0,
                "name": f"{student.transport_route.route_name} Transport Fee",
                "category": "Transport",
                "frequency": frequency,
                "cycles_due": fee_cycle_count(student.joined_on, frequency),
                "unit_amount": float(student.transport_route.fee_amount or 0),
                "monthly_amount": monthly_amount,
                "current_month_amount": monthly_amount,
                "due_amount": monthly_amount * fee_cycle_count(student.joined_on, frequency),
                "remaining_amount": 0.0,
                "target_type": "Transport",
                "target_name": student.transport_route.route_name,
            }
        )
    return legacy_items


def applicable_fees_for_student(
    session: Session,
    student: Student,
    *,
    category: str = "",
    include_inactive: bool = False,
) -> list[Fee]:
    statement = select(Fee).order_by(Fee.category, Fee.name, Fee.id)
    if not include_inactive:
        statement = statement.where(Fee.status == "Active")
    if category.strip():
        statement = statement.where(Fee.category == category.strip().title())
    fees = session.scalars(statement).all()
    return [fee for fee in fees if fee_applies_to_student(fee, student)]


def fee_target_display_name(session: Session, fee: Fee) -> str:
    target_type = str(fee.target_type or "General").strip()
    if target_type == "General" or fee.target_id is None:
        return "All Students"
    if target_type == "Course":
        course = session.get(Course, fee.target_id)
        return course.name if course else "Unknown Course"
    if target_type == "Hostel":
        hostel = session.get(Hostel, fee.target_id)
        return hostel.name if hostel else "Unknown Hostel"
    if target_type == "Transport":
        route = session.get(TransportRoute, fee.target_id)
        return route.route_name if route else "Unknown Route"
    return "Unknown"


def fee_target_display_name_for_student(fee: Fee, student: Student) -> str:
    target_type = str(fee.target_type or "General").strip()
    if target_type == "General" or fee.target_id is None:
        return "All Students"
    if target_type == "Course":
        return student.course.name if student.course and student.course_id == fee.target_id else "Unknown Course"
    if target_type == "Hostel":
        return student.hostel.name if student.hostel and student.hostel_id == fee.target_id else "Unknown Hostel"
    if target_type == "Transport":
        return (
            student.transport_route.route_name
            if student.transport_route and student.transport_id == fee.target_id
            else "Unknown Route"
        )
    return "Unknown"


def normalize_payment_type(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_fee_category(value: str | None) -> str:
    normalized = str(value or "").strip().title()
    if normalized == "General":
        return "Other"
    if normalized in FEE_CATEGORIES:
        return normalized
    return "Other"


def build_fee_index(fees: list[Fee]) -> dict[str, object]:
    positions = {fee.id: index for index, fee in enumerate(fees)}
    fees_by_target_type: dict[str, dict[int, list[Fee]]] = {
        "Course": defaultdict(list),
        "Hostel": defaultdict(list),
        "Transport": defaultdict(list),
    }
    general_fees: list[Fee] = []

    for fee in fees:
        target_type = str(fee.target_type or "General").strip()
        if target_type == "General" or fee.target_id is None:
            general_fees.append(fee)
            continue
        target_bucket = fees_by_target_type.get(target_type)
        if target_bucket is not None:
            target_bucket[fee.target_id].append(fee)

    return {
        "positions": positions,
        "general": general_fees,
        "by_target_type": fees_by_target_type,
    }


def applicable_fees_for_student_from_index(
    student: Student,
    fee_index: dict[str, object],
    *,
    category: str = "",
) -> list[Fee]:
    fee_positions = fee_index["positions"]
    fees_by_target_type = fee_index["by_target_type"]
    normalized_category = category.strip().title()

    matched_fees = list(fee_index["general"])
    if student.course_id is not None:
        matched_fees.extend(fees_by_target_type["Course"].get(student.course_id, []))
    if student.hostel_id is not None:
        matched_fees.extend(fees_by_target_type["Hostel"].get(student.hostel_id, []))
    if student.transport_id is not None:
        matched_fees.extend(fees_by_target_type["Transport"].get(student.transport_id, []))

    if normalized_category:
        matched_fees = [fee for fee in matched_fees if fee.category == normalized_category]

    return sorted(matched_fees, key=lambda fee: fee_positions.get(fee.id, 0))


def paid_payment_totals_by_student(session: Session, student_ids: list[int]) -> dict[int, float]:
    if not student_ids:
        return {}

    rows = session.execute(
        select(Payment.student_id, func.coalesce(func.sum(Payment.amount), 0.0))
        .where(
            Payment.student_id.in_(student_ids),
            Payment.status == "Paid",
        )
        .group_by(Payment.student_id)
    ).all()
    return {int(student_id): float(total or 0.0) for student_id, total in rows}


def paid_payment_totals_by_fee(session: Session, student_id: int) -> dict[tuple[int, str], float]:
    rows = session.execute(
        select(Payment.service_id, Payment.service_type, func.coalesce(func.sum(Payment.amount), 0.0))
        .where(
            Payment.student_id == student_id,
            Payment.status == "Paid",
            Payment.service_id.is_not(None),
        )
        .group_by(Payment.service_id, Payment.service_type)
    ).all()
    return {
        (int(service_id), normalize_payment_type(service_type)): float(total or 0.0)
        for service_id, service_type, total in rows
        if service_id is not None
    }


def calculate_student_due_breakdown(
    session: Session,
    student: Student,
    as_of: date | None = None,
) -> dict[str, float | list[dict[str, object]]]:
    # We leverage the exact same comprehensive calculation logic used by the UI
    fees_data = calculate_student_fees_and_payments(session, student)
    
    due_items: list[dict[str, object]] = []
    
    for item in fees_data.get("fee_items", []):
        due_amount = float(item.get("remaining_amount", 0.0))
        
        # Only bill what is actually remaining due from the cascading calculation
        if due_amount <= 0:
            continue
            
        due_items.append(
            {
                "fee_id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("category"),
                "frequency": item.get("frequency"),
                "is_one_time": item.get("frequency") == "One-time",
                "amount": due_amount,
                "target_name": item.get("target_name"),
            }
        )
        
    total_due = sum(float(item["amount"]) for item in due_items)
    return {
        "total_due": total_due,
        "breakdown": due_items,
    }


def calculate_student_fees_and_payments_from_data(
    student: Student,
    fees: list[Fee],
    paid_amount: float = 0.0,
) -> dict[str, float]:
    fee_items: list[dict[str, float | int | str]] = []
    category_totals = {
        "Admission": 0.0,
        "Course": 0.0,
        "Hostel": 0.0,
        "Transport": 0.0,
        "Other": 0.0,
    }
    current_cycle_amount = 0.0

    for fee in fees:
        cycle_count = fee_cycle_count(student.joined_on, fee.frequency)
        current_cycle_fee = current_month_amount(fee.amount, fee.frequency, student.joined_on)
        due_amount = current_cycle_fee * cycle_count
        normalized_category = normalize_fee_category(fee.category)
        category_totals[normalized_category] = category_totals.get(normalized_category, 0.0) + due_amount
        current_cycle_amount += current_cycle_fee
        fee_items.append(
            {
                "id": fee.id,
                "name": fee.name,
                "category": normalized_category,
                "frequency": fee.frequency,
                "cycles_due": cycle_count,
                "unit_amount": float(fee.amount or 0),
                "monthly_amount": monthly_equivalent_amount(fee.amount, fee.frequency),
                "current_month_amount": current_cycle_fee,
                "due_amount": due_amount,
                "remaining_amount": due_amount,
                "target_type": fee.target_type,
                "target_name": fee_target_display_name_for_student(fee, student),
            }
        )

    fee_items.extend(legacy_fee_items_for_student(student, fees))
    total_fees = sum(float(item["due_amount"]) for item in fee_items)
    category_totals = {
        "Admission": 0.0,
        "Course": 0.0,
        "Hostel": 0.0,
        "Transport": 0.0,
        "Other": 0.0,
    }
    current_cycle_amount = 0.0
    for item in fee_items:
        normalized_category = normalize_fee_category(str(item["category"]))
        category_totals[normalized_category] = category_totals.get(normalized_category, 0.0) + float(item["due_amount"])
        current_cycle_amount += float(item["current_month_amount"])

    remaining_paid = float(paid_amount or 0.0)
    for item in fee_items:
        due_amount = float(item["due_amount"])
        covered = min(due_amount, remaining_paid)
        item["remaining_amount"] = due_amount - covered
        remaining_paid -= covered

    remaining_balance = total_fees - float(paid_amount or 0.0)
    previous_pending_amount = max(remaining_balance - current_cycle_amount, 0.0)
    return {
        "total_fees": total_fees,
        "course_fee": category_totals["Course"],
        "hostel_fee": category_totals["Hostel"],
        "transport_fee": category_totals["Transport"],
        "admission_fee": category_totals["Admission"],
        "other_fee": category_totals["Other"],
        "current_cycle_amount": current_cycle_amount,
        "previous_pending_amount": previous_pending_amount,
        "paid_amount": float(paid_amount or 0.0),
        "pending_amount": max(remaining_balance, 0.0),
        "remaining_balance": remaining_balance,
        "fee_items": fee_items,
    }


def calculate_fee_snapshots_for_students(
    session: Session,
    students: list[Student],
) -> dict[int, dict[str, float]]:
    if not students:
        return {}

    active_fees = session.scalars(
        select(Fee).where(Fee.status == "Active").order_by(Fee.category, Fee.name, Fee.id)
    ).all()
    fee_index = build_fee_index(active_fees)
    paid_amounts = paid_payment_totals_by_student(session, [student.id for student in students])

    return {
        student.id: calculate_student_fees_and_payments_from_data(
            student,
            applicable_fees_for_student_from_index(student, fee_index),
            paid_amounts.get(student.id, 0.0),
        )
        for student in students
    }


def _file_signature(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _dashboard_metrics_cache_signature() -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    wal_path = DATABASE_PATH.with_name(f"{DATABASE_PATH.name}-wal")
    return (_file_signature(DATABASE_PATH), _file_signature(wal_path))


def clear_dashboard_metrics_cache() -> None:
    _DASHBOARD_METRICS_CACHE["signature"] = None
    _DASHBOARD_METRICS_CACHE["computed_at"] = 0.0
    _DASHBOARD_METRICS_CACHE["metrics"] = None


def _calculate_dashboard_metrics(session: Session) -> dict[str, float | int]:
    total_students = session.scalar(
        select(func.count()).select_from(Student).where(Student.status == "Active")
    ) or 0
    active_courses = session.scalar(
        select(func.count()).select_from(Course).where(Course.status == "Active")
    ) or 0
    total_collected = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.status == "Paid")
    ) or 0.0
    pending_by_category = {
        "Admission": 0.0,
        "Course": 0.0,
        "Hostel": 0.0,
        "Transport": 0.0,
        "Other": 0.0,
    }
    active_students = session.scalars(
        select(Student)
        .options(
            joinedload(Student.course),
            joinedload(Student.hostel),
            joinedload(Student.transport_route),
        )
        .where(Student.status == "Active")
        .order_by(Student.id)
    ).all()
    fee_snapshots = calculate_fee_snapshots_for_students(session, active_students)
    for student in active_students:
        fees_data = fee_snapshots.get(student.id, {})
        for item in fees_data["fee_items"]:
            pending_by_category[normalize_fee_category(str(item["category"]))] += max(item["remaining_amount"], 0.0)

    return {
        "total_students": total_students,
        "active_courses": active_courses,
        "total_collected": total_collected,
        "pending_total": sum(pending_by_category.values()),
        "pending_admission": pending_by_category["Admission"],
        "pending_course": pending_by_category["Course"],
        "pending_hostel": pending_by_category["Hostel"],
        "pending_transport": pending_by_category["Transport"],
        "pending_other": pending_by_category["Other"],
    }


def dashboard_metrics(session: Session) -> dict[str, float | int]:
    cache_signature = _dashboard_metrics_cache_signature()
    current_time = time.time()
    cached_signature = _DASHBOARD_METRICS_CACHE["signature"]
    cached_metrics = _DASHBOARD_METRICS_CACHE["metrics"]
    cached_at = float(_DASHBOARD_METRICS_CACHE["computed_at"])

    if (
        cached_metrics is not None
        and cached_signature == cache_signature
        and (current_time - cached_at) < DASHBOARD_METRICS_CACHE_TTL_SECONDS
    ):
        return dict(cached_metrics)

    metrics = _calculate_dashboard_metrics(session)
    _DASHBOARD_METRICS_CACHE["signature"] = cache_signature
    _DASHBOARD_METRICS_CACHE["computed_at"] = current_time
    _DASHBOARD_METRICS_CACHE["metrics"] = dict(metrics)
    return dict(metrics)


def payment_summary(session: Session) -> dict[str, float]:
    summary = {
        "total": session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(Payment.status == "Paid")
        )
        or 0.0,
    }
    for payment_type in ("admission", "course", "hostel", "transport", "other"):
        summary[payment_type] = session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.service_type == payment_type,
                Payment.status == "Paid",
            )
        ) or 0.0
    return summary


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
    fees = applicable_fees_for_student(session, student)
    payments = student_payment_summary(session, student.id)
    return calculate_student_fees_and_payments_from_data(student, fees, payments["paid"])


def active_lookups(session: Session, *, include_students: bool = False) -> dict[str, list]:
    lookups = {
        "fees": session.scalars(select(Fee).where(Fee.status == "Active").order_by(Fee.name)).all(),
        "courses": session.scalars(
            select(Course).where(Course.status == "Active").order_by(Course.name)
        ).all(),
        "sections": session.scalars(
            select(Section).where(Section.status == "Active").order_by(Section.name)
        ).all(),
        "hostels": session.scalars(
            select(Hostel).where(Hostel.status == "Active").order_by(Hostel.name)
        ).all(),
        "transport_routes": session.scalars(
            select(TransportRoute)
            .where(TransportRoute.status == "Active")
            .order_by(TransportRoute.route_name)
        ).all(),
    }
    if include_students:
        lookups["students"] = session.scalars(
            select(Student).where(Student.status == "Active").order_by(Student.full_name)
        ).all()
    return lookups


def payment_service_maps(session: Session) -> dict[str, dict[int, str]]:
    service_maps: dict[str, dict[int, str]] = {}
    for fee in session.scalars(select(Fee).order_by(Fee.category, Fee.name)).all():
        service_maps.setdefault(fee.category.lower(), {})[fee.id] = fee.name
    service_maps["__legacy_course__"] = {
        course.id: course.name for course in session.scalars(select(Course).order_by(Course.name)).all()
    }
    service_maps["__legacy_hostel__"] = {
        hostel.id: hostel.name for hostel in session.scalars(select(Hostel).order_by(Hostel.name)).all()
    }
    service_maps["__legacy_transport__"] = {
        route.id: route.route_name
        for route in session.scalars(select(TransportRoute).order_by(TransportRoute.route_name)).all()
    }
    return service_maps


def payment_service_name(
    payment: Payment, service_maps: dict[str, dict[int, str]]
) -> str:
    if str(payment.service_name or "").strip():
        return payment.service_name
    if payment.service_id is None:
        return ""
    service_name = service_maps.get(normalize_payment_type(payment.service_type), {}).get(
        payment.service_id
    )
    if service_name:
        return service_name
    if normalize_payment_type(payment.service_type) == "course":
        course = service_maps.get("__legacy_course__", {}).get(payment.service_id)
        if course:
            return course
    if normalize_payment_type(payment.service_type) == "hostel":
        hostel = service_maps.get("__legacy_hostel__", {}).get(payment.service_id)
        if hostel:
            return hostel
    if normalize_payment_type(payment.service_type) == "transport":
        route = service_maps.get("__legacy_transport__", {}).get(payment.service_id)
        if route:
            return route
    return f"Service ID: {payment.service_id}"


def validate_service_for_type(
    session: Session,
    service_type: str,
    service_id: int | None,
    *,
    student: Student | None = None,
) -> bool:
    if service_id is None:
        return False
    fee = session.get(Fee, service_id)
    if fee is not None:
        if normalize_payment_type(fee.category) != normalize_payment_type(service_type):
            return False
        if student is not None and not fee_applies_to_student(fee, student):
            return False
        return True

    if student is None:
        return False
    normalized_service_type = normalize_payment_type(service_type)
    if normalized_service_type == "course":
        return student.course_id == service_id and student.course is not None
    if normalized_service_type == "hostel":
        return student.hostel_id == service_id and student.hostel is not None
    if normalized_service_type == "transport":
        return student.transport_id == service_id and student.transport_route is not None
    return False


def years_for_filter() -> list[int]:
    current = date.today().year
    return list(range(current - 3, current + 3))
