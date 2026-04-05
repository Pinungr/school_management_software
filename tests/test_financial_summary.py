from datetime import date
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from school_admin.auth import hash_password
from school_admin.config import SESSION_SECRET_ENV_VAR, get_session_secret
from school_admin.database import Base, SessionLocal, UPLOADS_DIR, engine
from school_admin.media import DEFAULT_LOGO_URL
from school_admin.migrations import run_migrations
from school_admin.models import Course, Payment, Setting, Student, TransportRoute, User
from school_admin.seed import seed_database
from main import app, calculate_student_fees_and_payments, startup_target_path


@pytest.fixture(scope="module")
def seeded_session():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_database(session)
        yield session


@pytest.fixture()
def client():
    return TestClient(app)


def configure_setup_state(
    session,
    *,
    setup_completed: bool,
    admin_username: str = "admin",
    admin_password: str = "adminadmin",
    logo_url: str = "/static/logo.svg",
):
    settings = session.get(Setting, 1)
    assert settings is not None
    admin_user = session.scalar(select(User).where(User.role == "Admin").order_by(User.id))
    assert admin_user is not None

    settings.setup_completed = setup_completed
    settings.logo_url = logo_url
    admin_user.username = admin_username
    admin_user.password_hash = hash_password(admin_password)
    admin_user.status = "Active"
    if admin_user.email in {"", "admin@school.com"}:
        admin_user.email = f"{admin_username}@school.local"
    session.commit()


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def ensure_operational_test_data(session) -> None:
    course = session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    if course is None:
        course = Course(
            name="Test Course",
            code="TEST-COURSE",
            fees=10000,
            frequency="Monthly",
            status="Active",
            description="Course used by automated tests.",
        )
        session.add(course)
        session.flush()

    transport_route = session.scalar(
        select(TransportRoute).where(TransportRoute.route_name == "Test Route")
    )
    if transport_route is None:
        transport_route = TransportRoute(
            route_name="Test Route",
            pickup_points="Point A, Point B",
            fee_amount=1500,
            frequency="Monthly",
            status="Active",
        )
        session.add(transport_route)
        session.flush()

    student_1 = session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    if student_1 is None:
        student_1 = Student(
            student_code="TEST-STU-001",
            full_name="Test Student One",
            email="student.one@example.com",
            phone="9999990001",
            parent_name="Parent One",
            status="Active",
            address="Address One",
            joined_on=date(2026, 4, 1),
            course_id=course.id,
        )
        session.add(student_1)
        session.flush()

    student_2 = session.scalar(select(Student).where(Student.student_code == "TEST-STU-002"))
    if student_2 is None:
        student_2 = Student(
            student_code="TEST-STU-002",
            full_name="Test Student Two",
            email="student.two@example.com",
            phone="9999990002",
            parent_name="Parent Two",
            status="Active",
            address="Address Two",
            joined_on=date(2026, 4, 2),
            course_id=course.id,
            transport_id=transport_route.id,
        )
        session.add(student_2)
        session.flush()

    payment = session.scalar(select(Payment).where(Payment.reference == "TEST-BASE-PAYMENT"))
    if payment is None:
        session.add(
            Payment(
                student_id=student_2.id,
                service_type="transport",
                service_id=transport_route.id,
                amount=1500.0,
                payment_date=date(2026, 4, 5),
                method="UPI",
                reference="TEST-BASE-PAYMENT",
                status="Paid",
            )
        )

    session.commit()


def test_calculate_student_fees_and_payments_for_seeded_student(seeded_session):
    ensure_operational_test_data(seeded_session)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-002"))
    assert student is not None

    fees = calculate_student_fees_and_payments(seeded_session, student)

    assert fees["total_fees"] == 11500.0
    assert fees["paid_amount"] == 1500.0
    assert fees["remaining_balance"] == 10000.0
    assert fees["pending_amount"] == 10000.0


def test_payments_page_and_export_show_service_name(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert student is not None
    assert student.course is not None

    created_payment = seeded_session.scalar(select(Payment).where(Payment.reference == "TEST-SERVICE"))
    if created_payment is None:
        created_payment = Payment(
            student_id=student.id,
            service_type="course",
            service_id=student.course.id,
            amount=1111.0,
            reference="TEST-SERVICE",
            status="Paid",
        )
        seeded_session.add(created_payment)
        seeded_session.commit()

    try:
        login_page = client.get("/login")
        csrf_token = extract_csrf_token(login_page.text)
        client.post(
            "/login",
            data={
                "csrf_token": csrf_token,
                "identifier": "admin",
                "password": "adminadmin",
                "next_path": "/dashboard",
            },
        )

        payments_page = client.get("/payments")
        assert payments_page.status_code == 200
        assert student.course.name in payments_page.text

        export_response = client.get("/payments/export")
        assert export_response.status_code == 200
        assert student.course.name in export_response.text
    finally:
        payment_to_cleanup = seeded_session.scalar(
            select(Payment).where(Payment.reference == "TEST-SERVICE")
        )
        if payment_to_cleanup is not None:
            seeded_session.delete(payment_to_cleanup)
            seeded_session.commit()


def test_public_routes_render_without_auth(client):
    with SessionLocal() as session:
        configure_setup_state(session, setup_completed=True)

    home_response = client.get("/", follow_redirects=False)
    assert home_response.status_code == 303
    assert home_response.headers["location"] == "/login"

    login_response = client.get("/login")
    assert login_response.status_code == 200
    assert "SchoolFlow" in login_response.text


def test_initial_setup_updates_logo_and_admin_account(seeded_session, client):
    settings = seeded_session.get(Setting, 1)
    admin_user = seeded_session.scalar(select(User).where(User.role == "Admin").order_by(User.id))
    assert settings is not None
    assert admin_user is not None

    original_school_name = settings.school_name
    original_school_email = settings.school_email
    original_phone_number = settings.phone_number
    original_address = settings.address
    original_logo = settings.logo_url
    original_setup_completed = settings.setup_completed
    original_full_name = admin_user.full_name
    original_username = admin_user.username
    original_password_hash = admin_user.password_hash
    original_email = admin_user.email

    try:
        configure_setup_state(
            seeded_session,
            setup_completed=False,
            admin_username="admin",
            admin_password="adminadmin",
            logo_url="/static/logo.svg",
        )

        home_response = client.get("/", follow_redirects=False)
        assert home_response.status_code == 303
        assert home_response.headers["location"] == "/setup"

        setup_page = client.get("/setup")
        csrf_token = extract_csrf_token(setup_page.text)
        setup_response = client.post(
            "/setup",
            data={
                "csrf_token": csrf_token,
                "school_name": "Green Valley High School",
                "school_email": "hello@greenvalley.edu",
                "phone_number": "+91 9123456789",
                "address": "42 Learning Avenue",
                "existing_logo_url": "/static/logo.svg",
                "admin_full_name": "Asha Principal",
                "admin_email": "asha@greenvalley.edu",
                "admin_username": "principal",
                "admin_password": "newsecurepass",
                "confirm_password": "newsecurepass",
            },
            files={"logo_file": ("school-logo.png", b"fake-image-bytes", "image/png")},
            follow_redirects=False,
        )
        assert setup_response.status_code == 303
        assert setup_response.headers["location"] == "/login?setup=1"

        seeded_session.refresh(settings)
        seeded_session.refresh(admin_user)
        assert settings.setup_completed is True
        assert settings.school_name == "Green Valley High School"
        assert settings.school_email == "hello@greenvalley.edu"
        assert settings.phone_number == "+91 9123456789"
        assert settings.address == "42 Learning Avenue"
        assert settings.logo_url.startswith("/media/logo-")
        assert admin_user.full_name == "Asha Principal"
        assert admin_user.email == "asha@greenvalley.edu"
        assert admin_user.username == "principal"

        uploaded_logo = UPLOADS_DIR / settings.logo_url.removeprefix("/media/")
        assert uploaded_logo.exists()

        login_page = client.get("/login?setup=1")
        login_csrf_token = extract_csrf_token(login_page.text)
        login_response = client.post(
            "/login",
            data={
                "csrf_token": login_csrf_token,
                "identifier": "principal",
                "password": "newsecurepass",
                "next_path": "/dashboard",
            },
            follow_redirects=False,
        )
        assert login_response.status_code == 303
        assert login_response.headers["location"] == "/dashboard"
    finally:
        if settings.logo_url.startswith("/media/"):
            uploaded_logo = UPLOADS_DIR / settings.logo_url.removeprefix("/media/")
            uploaded_logo.unlink(missing_ok=True)
        settings.school_name = original_school_name
        settings.school_email = original_school_email
        settings.phone_number = original_phone_number
        settings.address = original_address
        settings.logo_url = original_logo
        settings.setup_completed = original_setup_completed
        admin_user.full_name = original_full_name
        admin_user.username = original_username
        admin_user.password_hash = original_password_hash
        admin_user.email = original_email
        seeded_session.commit()


def test_startup_target_path_prefers_setup_until_first_run_finishes():
    with SessionLocal() as session:
        settings = session.get(Setting, 1)
        assert settings is not None
        original_setup_completed = settings.setup_completed

        try:
            settings.setup_completed = False
            session.commit()
            assert startup_target_path() == "/setup"

            settings.setup_completed = True
            session.commit()
            assert startup_target_path() == "/login"
        finally:
            settings.setup_completed = original_setup_completed
            session.commit()


def test_session_secret_persists_and_env_can_override(monkeypatch):
    secret_file = Path("data") / "test-session-secret.txt"

    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.unlink(missing_ok=True)

        monkeypatch.delenv(SESSION_SECRET_ENV_VAR, raising=False)
        generated_secret = get_session_secret(secret_file)

        assert secret_file.exists()
        assert secret_file.read_text(encoding="utf-8").strip() == generated_secret
        assert get_session_secret(secret_file) == generated_secret

        monkeypatch.setenv(SESSION_SECRET_ENV_VAR, "env-secret-value")
        assert get_session_secret(secret_file) == "env-secret-value"
    finally:
        secret_file.unlink(missing_ok=True)


def test_login_rejects_missing_csrf_token(client):
    with SessionLocal() as session:
        configure_setup_state(session, setup_completed=True)

    response = client.post(
        "/login",
        data={"identifier": "admin", "password": "adminadmin", "next_path": "/dashboard"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login?csrf=1"


def test_setup_rejects_non_image_logo_upload(client):
    with SessionLocal() as session:
        configure_setup_state(session, setup_completed=False)

    setup_page = client.get("/setup")
    csrf_token = extract_csrf_token(setup_page.text)

    response = client.post(
        "/setup",
        data={
            "csrf_token": csrf_token,
            "school_name": "Green Valley High School",
            "school_email": "hello@greenvalley.edu",
            "phone_number": "+91 9123456789",
            "address": "42 Learning Avenue",
            "existing_logo_url": "/static/logo.svg",
            "admin_full_name": "Asha Principal",
            "admin_email": "asha@greenvalley.edu",
            "admin_username": "principal",
            "admin_password": "newsecurepass",
            "confirm_password": "newsecurepass",
        },
        files={"logo_file": ("not-an-image.txt", b"plain-text", "text/plain")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/setup?error=invalid_logo_file"


def test_setup_rejects_svg_logo_upload(client):
    with SessionLocal() as session:
        configure_setup_state(session, setup_completed=False)

    setup_page = client.get("/setup")
    csrf_token = extract_csrf_token(setup_page.text)

    response = client.post(
        "/setup",
        data={
            "csrf_token": csrf_token,
            "school_name": "Green Valley High School",
            "school_email": "hello@greenvalley.edu",
            "phone_number": "+91 9123456789",
            "address": "42 Learning Avenue",
            "existing_logo_url": DEFAULT_LOGO_URL,
            "admin_full_name": "Asha Principal",
            "admin_email": "asha@greenvalley.edu",
            "admin_username": "principal",
            "admin_password": "newsecurepass",
            "confirm_password": "newsecurepass",
        },
        files={"logo_file": ("logo.svg", b"<svg></svg>", "image/svg+xml")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/setup?error=invalid_logo_file"


def test_users_page_keeps_last_active_admin_protected(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)

    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "identifier": "admin",
            "password": "adminadmin",
            "next_path": "/dashboard",
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    users_page = client.get("/users?edit=1")
    edit_csrf_token = extract_csrf_token(users_page.text)
    response = client.post(
        "/users/1/edit",
        data={
            "csrf_token": edit_csrf_token,
            "full_name": "System Administrator",
            "username": "admin",
            "email": "admin@school.local",
            "role": "Clerk",
            "status": "Inactive",
            "password": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/users?edit=1&error=last_admin"


def test_settings_rejects_remote_logo_url_and_accepts_uploaded_logo(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    settings = seeded_session.get(Setting, 1)
    assert settings is not None
    original_logo_url = settings.logo_url

    try:
        login_page = client.get("/login")
        csrf_token = extract_csrf_token(login_page.text)
        login_response = client.post(
            "/login",
            data={
                "csrf_token": csrf_token,
                "identifier": "admin",
                "password": "adminadmin",
                "next_path": "/dashboard",
            },
            follow_redirects=False,
        )
        assert login_response.status_code == 303

        settings_page = client.get("/settings")
        settings_csrf_token = extract_csrf_token(settings_page.text)
        response = client.post(
            "/settings",
            data={
                "csrf_token": settings_csrf_token,
                "school_name": "Secure School",
                "school_email": "secure@school.test",
                "phone_number": "+91 9000000000",
                "existing_logo_url": "https://evil.example/logo.png",
                "address": "123 Secure Street",
                "academic_year": "2026-2027",
                "financial_year": "2026-2027",
                "fee_frequency": "Monthly",
                "currency": "INR (Rs)",
                "timezone": "Asia/Kolkata (IST)",
                "developer_name": "",
                "developer_email": "",
                "developer_phone": "",
            },
            files={"logo_file": ("school-logo.png", b"image-bytes", "image/png")},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/settings"

        seeded_session.refresh(settings)
        assert settings.logo_url.startswith("/media/logo-")
        uploaded_logo = UPLOADS_DIR / settings.logo_url.removeprefix("/media/")
        assert uploaded_logo.exists()
    finally:
        seeded_session.refresh(settings)
        if settings.logo_url.startswith("/media/"):
            uploaded_logo = UPLOADS_DIR / settings.logo_url.removeprefix("/media/")
            uploaded_logo.unlink(missing_ok=True)
        settings.logo_url = original_logo_url
        seeded_session.commit()


def test_payments_reject_non_positive_amounts(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert student is not None
    assert student.course is not None

    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "identifier": "admin",
            "password": "adminadmin",
            "next_path": "/dashboard",
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    payments_page = client.get("/payments?create=1")
    payment_csrf_token = extract_csrf_token(payments_page.text)
    response = client.post(
        "/payments/create",
        data={
            "csrf_token": payment_csrf_token,
            "student_id": str(student.id),
            "service_type": "course",
            "service_id": str(student.course.id),
            "amount": "-25",
            "payment_date": "2026-04-05",
            "method": "Cash",
            "reference": "NEGATIVE-TEST",
            "notes": "",
            "status": "Paid",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/payments?create=1&error=invalid_amount"


def test_courses_reject_negative_fee_values(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)

    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "identifier": "admin",
            "password": "adminadmin",
            "next_path": "/dashboard",
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    courses_page = client.get("/courses?create=1")
    course_csrf_token = extract_csrf_token(courses_page.text)
    response = client.post(
        "/courses/create",
        data={
            "csrf_token": course_csrf_token,
            "name": "Bad Course",
            "code": "BAD-COURSE",
            "fees": "-10",
            "frequency": "Monthly",
            "status": "Active",
            "description": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/courses?create=1&error=invalid_amount"


def test_seed_database_creates_setup_state_without_default_clerk_account():
    db_path = Path("data") / "seed-bootstrap-test.db"
    db_path.unlink(missing_ok=True)

    test_engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    test_session_local = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    try:
        Base.metadata.create_all(bind=test_engine)
        with test_session_local() as session:
            seed_database(session)
            settings = session.get(Setting, 1)
            admin_user = session.scalar(select(User).where(User.role == "Admin").order_by(User.id))
            clerk_user = session.scalar(select(User).where(User.role == "Clerk").order_by(User.id))

            assert settings is not None
            assert settings.setup_completed is False
            assert admin_user is not None
            assert admin_user.status == "Inactive"
            assert clerk_user is None
    finally:
        test_engine.dispose()
        db_path.unlink(missing_ok=True)


def test_migrations_backfill_unique_usernames_for_legacy_user_table():
    db_path = Path("data") / "legacy-users-test.db"
    db_path.unlink(missing_ok=True)

    test_engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    test_session_local = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    try:
        with test_engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    email TEXT UNIQUE,
                    password_hash TEXT,
                    role TEXT,
                    status TEXT,
                    created_on DATE
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO users (id, full_name, email, password_hash, role, status, created_on)
                VALUES
                    (1, 'Admin One', 'admin@example.com', 'hash', 'Admin', 'Active', '2026-04-05'),
                    (2, 'Admin Two', 'admin@example.com.invalid', 'hash', 'Admin', 'Active', '2026-04-05'),
                    (3, 'Clerk', '', 'hash', 'Clerk', 'Active', '2026-04-05')
                """
            )

        with test_session_local() as session:
            run_migrations(session)
            rows = session.execute(
                select(User.id, User.username).order_by(User.id)
            ).fetchall()

            assert rows[0][1] == "admin"
            assert rows[1][1].startswith("admin")
            assert rows[1][1] != rows[0][1]
            assert rows[2][1] == "user3"
    finally:
        test_engine.dispose()
        db_path.unlink(missing_ok=True)
