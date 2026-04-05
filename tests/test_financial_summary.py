from datetime import date
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from school_admin.auth import hash_password
from school_admin.config import SESSION_SECRET_ENV_VAR, get_session_secret
from school_admin.database import Base, SessionLocal, UPLOADS_DIR, engine
from school_admin.media import DEFAULT_LOGO_URL
from school_admin.migrations import run_migrations
from school_admin.models import Course, Payment, Setting, Student, TransportRoute, User
from school_admin.seed import seed_database
from school_admin.utils import dashboard_metrics, payment_summary
from main import app, calculate_student_fees_and_payments, startup_target_path


@pytest.fixture(scope="module")
def seeded_session():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        run_migrations(session)
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


def test_user_edit_rejects_short_password(seeded_session, client):
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
            "role": "Admin",
            "status": "Active",
            "password": "short",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/users?edit=1&error=password_short"


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


def test_settings_require_valid_school_name_and_post_logout_csrf(seeded_session, client):
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

    settings_page = client.get("/settings")
    settings_csrf_token = extract_csrf_token(settings_page.text)
    invalid_settings_response = client.post(
        "/settings",
        data={
            "csrf_token": settings_csrf_token,
            "school_name": "",
            "school_email": "secure@school.test",
            "phone_number": "+91 9000000000",
            "existing_logo_url": DEFAULT_LOGO_URL,
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
        follow_redirects=False,
    )
    assert invalid_settings_response.status_code == 303
    assert invalid_settings_response.headers["location"] == "/settings?error=school_name_required"

    logout_page = client.get("/dashboard")
    logout_csrf_token = extract_csrf_token(logout_page.text)
    logout_response = client.post(
        "/logout",
        data={"csrf_token": logout_csrf_token},
        follow_redirects=False,
    )
    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/login"

    dashboard_response = client.get("/dashboard", follow_redirects=False)
    assert dashboard_response.status_code == 303
    assert dashboard_response.headers["location"].startswith("/login")


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


def test_finance_summaries_exclude_pending_payments(seeded_session):
    ensure_operational_test_data(seeded_session)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert student is not None
    assert student.course is not None

    baseline_summary = payment_summary(seeded_session)
    baseline_metrics = dashboard_metrics(seeded_session)

    pending_reference = "TEST-PENDING-ONLY"
    existing_pending = seeded_session.scalar(
        select(Payment).where(Payment.reference == pending_reference)
    )
    if existing_pending is None:
        seeded_session.add(
            Payment(
                student_id=student.id,
                service_type="course",
                service_id=student.course.id,
                amount=700.0,
                payment_date=date(2026, 4, 5),
                method="Cash",
                reference=pending_reference,
                status="Pending",
            )
        )
        seeded_session.commit()

    try:
        summary = payment_summary(seeded_session)
        metrics = dashboard_metrics(seeded_session)

        assert summary == baseline_summary
        assert metrics == baseline_metrics
    finally:
        pending_payment = seeded_session.scalar(
            select(Payment).where(Payment.reference == pending_reference)
        )
        if pending_payment is not None:
            seeded_session.delete(pending_payment)
            seeded_session.commit()


def test_notify_guardian_escapes_student_and_school_fields(seeded_session, client):
    ensure_operational_test_data(seeded_session)
    configure_setup_state(seeded_session, setup_completed=True)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    settings = seeded_session.get(Setting, 1)
    assert student is not None
    assert settings is not None

    original_student_name = student.full_name
    original_parent_name = student.parent_name
    original_address = student.address
    original_school_name = settings.school_name

    try:
        student.full_name = '<script>alert("student")</script>'
        student.parent_name = '<img src=x onerror=alert("parent")>'
        student.address = '<b>unsafe</b>'
        settings.school_name = '<script>alert("school")</script>'
        seeded_session.commit()

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

        students_page = client.get("/students")
        notify_csrf_token = extract_csrf_token(students_page.text)
        response = client.post(
            f"/students/{student.id}/notify",
            data={"csrf_token": notify_csrf_token},
        )

        assert response.status_code == 200
        assert '<script>alert("student")</script>' not in response.text
        assert '<script>alert("school")</script>' not in response.text
        assert '&lt;script&gt;alert(&quot;student&quot;)&lt;/script&gt;' in response.text
        assert '&lt;script&gt;alert(&quot;school&quot;)&lt;/script&gt;' in response.text
        assert '&lt;img src=x onerror=alert(&quot;parent&quot;)&gt;' in response.text
        assert '&lt;b&gt;unsafe&lt;/b&gt;' in response.text
    finally:
        student.full_name = original_student_name
        student.parent_name = original_parent_name
        student.address = original_address
        settings.school_name = original_school_name
        seeded_session.commit()


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
            assert settings.developer_name == ""
            assert settings.developer_email == ""
            assert settings.developer_phone == ""
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


def test_payments_keep_service_name_after_catalog_delete(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)

    temp_course = Course(
        name="History Snapshot Course",
        code="HIST-SNAPSHOT",
        fees=2500,
        frequency="Monthly",
        status="Active",
        description="Temporary course for history retention tests.",
    )
    temp_student = Student(
        student_code="SNAP-STU-001",
        full_name="Snapshot Student",
        email="snapshot.student@example.com",
        phone="9999990009",
        parent_name="Snapshot Parent",
        status="Active",
        address="Snapshot Address",
        joined_on=date(2026, 4, 5),
        course=temp_course,
    )
    temp_payment = Payment(
        student=temp_student,
        service_type="course",
        service_name=temp_course.name,
        amount=2500.0,
        payment_date=date(2026, 4, 5),
        method="Cash",
        reference="SNAP-HISTORY-PAYMENT",
        status="Paid",
    )
    temp_payment.service_id = 0
    seeded_session.add_all([temp_course, temp_student, temp_payment])
    seeded_session.flush()
    temp_payment.service_id = temp_course.id
    seeded_session.commit()

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

        courses_page = client.get("/courses")
        delete_csrf_token = extract_csrf_token(courses_page.text)
        delete_response = client.post(
            f"/courses/{temp_course.id}/delete",
            data={"csrf_token": delete_csrf_token},
            follow_redirects=False,
        )
        assert delete_response.status_code == 303

        payments_page = client.get("/payments")
        assert payments_page.status_code == 200
        assert "History Snapshot Course" in payments_page.text

        export_response = client.get("/payments/export")
        assert export_response.status_code == 200
        assert "History Snapshot Course" in export_response.text
    finally:
        payment = seeded_session.scalar(select(Payment).where(Payment.reference == "SNAP-HISTORY-PAYMENT"))
        if payment is not None:
            seeded_session.delete(payment)
        student = seeded_session.scalar(select(Student).where(Student.student_code == "SNAP-STU-001"))
        if student is not None:
            seeded_session.delete(student)
        course = seeded_session.scalar(select(Course).where(Course.code == "HIST-SNAPSHOT"))
        if course is not None:
            seeded_session.delete(course)
        seeded_session.commit()


def test_sqlite_foreign_keys_are_enabled_for_sessions():
    with SessionLocal() as session:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_migration_clears_placeholder_developer_info_for_unconfigured_system():
    db_path = Path("data") / "placeholder-settings-test.db"
    db_path.unlink(missing_ok=True)

    test_engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    test_session_local = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    try:
        with test_engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE settings (
                    id INTEGER PRIMARY KEY,
                    school_name TEXT,
                    school_email TEXT,
                    phone_number TEXT,
                    logo_url TEXT,
                    address TEXT,
                    academic_year TEXT,
                    financial_year TEXT,
                    fee_frequency TEXT,
                    currency TEXT,
                    timezone TEXT,
                    developer_name TEXT,
                    developer_email TEXT,
                    developer_phone TEXT,
                    setup_completed INTEGER
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO settings (
                    id, school_name, school_email, phone_number, logo_url, address,
                    academic_year, financial_year, fee_frequency, currency, timezone,
                    developer_name, developer_email, developer_phone, setup_completed
                ) VALUES (
                    1, 'Private School', 'info@school.com', '+91 9876543210', '/static/logo.svg',
                    '123 Education Street', '2026-2027', '2026-2027', 'Monthly',
                    'INR (Rs)', 'Asia/Kolkata (IST)', 'Pinaki Sarangi', 'pinungr@gmail.com',
                    '7751952860', 0
                )
                """
            )

        with test_session_local() as session:
            run_migrations(session)
            settings = session.get(Setting, 1)
            assert settings is not None
            assert settings.developer_name == ""
            assert settings.developer_email == ""
            assert settings.developer_phone == ""
    finally:
        test_engine.dispose()
        db_path.unlink(missing_ok=True)
