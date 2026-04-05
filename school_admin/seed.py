from __future__ import annotations

from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Course, Hostel, Payment, Setting, Student, TransportRoute, User

DEFAULT_DEVELOPER_NAME = "Pinaki Sarangi"
DEFAULT_DEVELOPER_EMAIL = "pinungr@gmail.com"
DEFAULT_DEVELOPER_PHONE = "7751952860"


def ensure_user_schema(session: Session) -> None:
    table_exists = session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    ).first()
    if not table_exists:
        return

    columns = {
        row[1] for row in session.execute(text("PRAGMA table_info(users)")).fetchall()
    }
    if "username" not in columns:
        session.execute(text("ALTER TABLE users ADD COLUMN username TEXT"))
        session.commit()


def ensure_settings_schema(session: Session) -> None:
    table_exists = session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
    ).first()
    if not table_exists:
        return

    columns = {
        row[1] for row in session.execute(text("PRAGMA table_info(settings)")).fetchall()
    }
    for column_name, column_type in (
        ("developer_name", "TEXT"),
        ("developer_email", "TEXT"),
        ("developer_phone", "TEXT"),
    ):
        if column_name not in columns:
            session.execute(text(f"ALTER TABLE settings ADD COLUMN {column_name} {column_type}"))
            session.commit()


def seed_database(session: Session) -> None:
    ensure_user_schema(session)
    ensure_settings_schema(session)

    admin_user = session.scalar(
        select(User).where((User.username == "admin") | (User.email == "admin@school.com"))
    )
    if admin_user is None:
        session.add(
            User(
                full_name="System Administrator",
                username="admin",
                email="admin@school.com",
                password_hash=hash_password("adminadmin"),
                role="Admin",
                status="Active",
            )
        )
    else:
        admin_user.full_name = "System Administrator"
        admin_user.username = "admin"
        admin_user.email = "admin@school.com"
        admin_user.password_hash = hash_password("adminadmin")
        admin_user.role = "Admin"
        admin_user.status = "Active"

    clerk_user = session.scalar(
        select(User).where((User.username == "clark") | (User.email == "clerk@school.com"))
    )
    if clerk_user is None:
        session.add(
            User(
                full_name="Office Clerk",
                username="clark",
                email="clerk@school.com",
                password_hash=hash_password("clarkclark"),
                role="Clerk",
                status="Active",
            )
        )
    else:
        clerk_user.full_name = "Office Clerk"
        clerk_user.username = "clark"
        clerk_user.email = "clerk@school.com"
        clerk_user.password_hash = hash_password("clarkclark")
        clerk_user.role = "Clerk"
        clerk_user.status = "Active"

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
            )
        )
    else:
        if not settings.developer_name:
            settings.developer_name = DEFAULT_DEVELOPER_NAME
        if not settings.developer_email:
            settings.developer_email = DEFAULT_DEVELOPER_EMAIL
        if not settings.developer_phone:
            settings.developer_phone = DEFAULT_DEVELOPER_PHONE

    if session.scalar(select(Course).limit(1)) is None:
        session.add_all(
            [
                Course(
                    name="Class 12",
                    code="12TH",
                    fees=10000,
                    frequency="Monthly",
                    status="Active",
                    description="Senior secondary science and commerce batches.",
                ),
                Course(
                    name="Class 10",
                    code="10TH",
                    fees=8500,
                    frequency="Monthly",
                    status="Active",
                    description="Board preparation program.",
                ),
                Course(
                    name="Robotics Lab",
                    code="ROBO",
                    fees=2500,
                    frequency="Quarterly",
                    status="Inactive",
                    description="Optional practical enrichment module.",
                ),
            ]
        )
        session.flush()

    if session.scalar(select(Hostel).limit(1)) is None:
        session.add_all(
            [
                Hostel(
                    name="North Block",
                    hostel_type="Boys",
                    rooms=40,
                    fee_amount=3000,
                    status="Active",
                    description="Shared accommodation with study hall.",
                ),
                Hostel(
                    name="Rose Residency",
                    hostel_type="Girls",
                    rooms=32,
                    fee_amount=3200,
                    status="Active",
                    description="Meals, study time, and evening supervision.",
                ),
            ]
        )
        session.flush()

    if session.scalar(select(TransportRoute).limit(1)) is None:
        session.add_all(
            [
                TransportRoute(
                    route_name="City Center Route",
                    pickup_points="Market Square, Clock Tower, City Center",
                    fee_amount=1800,
                    frequency="Monthly",
                    status="Active",
                ),
                TransportRoute(
                    route_name="East Zone Route",
                    pickup_points="Lake View, Green Park, East Gate",
                    fee_amount=1500,
                    frequency="Monthly",
                    status="Active",
                ),
            ]
        )
        session.flush()

    if session.scalar(select(Student).limit(1)) is None:
        course_12 = session.scalar(select(Course).where(Course.code == "12TH"))
        course_10 = session.scalar(select(Course).where(Course.code == "10TH"))
        north_block = session.scalar(select(Hostel).where(Hostel.name == "North Block"))
        city_route = session.scalar(
            select(TransportRoute).where(TransportRoute.route_name == "City Center Route")
        )
        east_route = session.scalar(
            select(TransportRoute).where(TransportRoute.route_name == "East Zone Route")
        )
        session.add_all(
            [
                Student(
                    student_code="STU001",
                    full_name="Rajesh Kumar",
                    email="student@school.com",
                    phone="7978966065",
                    parent_name="Ramesh Kumar",
                    status="Active",
                    address="Shivaji Nagar, Kolkata",
                    joined_on=date(2026, 4, 1),
                    course=course_12,
                    hostel=north_block,
                    transport_route=city_route,
                ),
                Student(
                    student_code="STU002",
                    full_name="Raka",
                    email="raka@gmail.com",
                    phone="9123401234",
                    parent_name="Anita Saha",
                    status="Active",
                    address="Salt Lake, Kolkata",
                    joined_on=date(2026, 4, 3),
                    course=course_10,
                    transport_route=east_route,
                ),
            ]
        )
        session.flush()

    if session.scalar(select(Payment).limit(1)) is None:
        student_1 = session.scalar(select(Student).where(Student.student_code == "STU001"))
        student_2 = session.scalar(select(Student).where(Student.student_code == "STU002"))
        today = date.today()
        session.add_all(
            [
                Payment(
                    student=student_1,
                    service_type="course",
                    amount=3000,
                    payment_date=today,
                    method="Cash",
                    reference="RCPT-1001",
                    notes="April installment",
                ),
                Payment(
                    student=student_2,
                    service_type="transport",
                    amount=1500,
                    payment_date=today,
                    method="UPI",
                    reference="RCPT-1002",
                    notes="Transport payment",
                ),
                Payment(
                    student=student_1,
                    service_type="course",
                    amount=800,
                    payment_date=today,
                    method="Card",
                    reference="RCPT-1003",
                    notes="Lab and materials",
                ),
            ]
        )

    session.commit()
