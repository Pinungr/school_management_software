import csv
from datetime import date
import io
from pathlib import Path
import re
from urllib.parse import unquote
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

import launcher as desktop_launcher
import school_admin.utils as app_utils
from school_admin.auth import hash_password, verify_password
from school_admin.config import SESSION_SECRET_ENV_VAR, get_session_secret
from school_admin.database import Base, SessionLocal, UPLOADS_DIR, engine
from school_admin.media import DEFAULT_LOGO_URL
from school_admin.migrations import index_rows, run_migrations
from school_admin.models import Course, Fee, Payment, Section, Setting, Student, TransportRoute, User
from school_admin.routes.students import reminder_message
from school_admin.seed import SUPERADMIN_PASSWORD, SUPERADMIN_USERNAME, seed_database
from school_admin.utils import calculate_student_fees_and_payments, dashboard_metrics, payment_summary
from main import app, startup_target_path


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
    stale_payments = session.scalars(
        select(Payment).where(
            Payment.reference.in_(["ADM-TEST-001", "ADM-CANCEL-001", "ARCHIVE-PAY-001"])
        )
    ).all()
    for payment in stale_payments:
        session.delete(payment)

    stale_students = session.scalars(
        select(Student).where(
            Student.student_code.in_(["ADM-TEST-001", "ADM-CANCEL-001", "ARCHIVE-STU-001"])
        )
    ).all()
    for student in stale_students:
        session.delete(student)

    stale_fees = session.scalars(
        select(Fee).where(Fee.name.in_(["Admission Auto Fee", "Admission Cancel Fee"]))
    ).all()
    for fee in stale_fees:
        session.delete(fee)

    if stale_payments or stale_students or stale_fees:
        session.commit()

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

    course_fee = session.scalar(
        select(Fee).where(Fee.category == "Course", Fee.target_type == "Course", Fee.target_id == course.id)
    )
    if course_fee is None:
        course_fee = Fee(
            name="Test Course Fee",
            category="Course",
            amount=10000,
            frequency="Monthly",
            status="Active",
            target_type="Course",
            target_id=course.id,
            description="Course fee used by automated tests.",
        )
        session.add(course_fee)
        session.flush()

    transport_fee = session.scalar(
        select(
            Fee
        ).where(
            Fee.category == "Transport",
            Fee.target_type == "Transport",
            Fee.target_id == transport_route.id,
        )
    )
    if transport_fee is None:
        transport_fee = Fee(
            name="Test Transport Fee",
            category="Transport",
            amount=1500,
            frequency="Monthly",
            status="Active",
            target_type="Transport",
            target_id=transport_route.id,
            description="Transport fee used by automated tests.",
        )
        session.add(transport_fee)
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
                service_id=transport_fee.id,
                service_name=transport_fee.name,
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


def test_bulk_fee_snapshots_match_single_student_calculation(seeded_session):
    ensure_operational_test_data(seeded_session)
    students = seeded_session.scalars(
        select(Student)
        .where(Student.student_code.in_(["TEST-STU-001", "TEST-STU-002"]))
        .order_by(Student.student_code)
    ).all()
    assert len(students) == 2

    batch_results = app_utils.calculate_fee_snapshots_for_students(seeded_session, students)
    single_results = {
        student.id: calculate_student_fees_and_payments(seeded_session, student)
        for student in students
    }

    assert batch_results == single_results


def test_dashboard_metrics_reuses_cached_snapshot_until_signature_changes(seeded_session, monkeypatch):
    ensure_operational_test_data(seeded_session)
    app_utils.clear_dashboard_metrics_cache()

    signatures = iter([("db-v1", None), ("db-v1", None), ("db-v2", None)])
    original_calculator = app_utils._calculate_dashboard_metrics
    calculator_calls = {"count": 0}

    def fake_signature():
        return next(signatures)

    def tracked_calculator(session):
        calculator_calls["count"] += 1
        return original_calculator(session)

    monkeypatch.setattr(app_utils, "_dashboard_metrics_cache_signature", fake_signature)
    monkeypatch.setattr(app_utils, "_calculate_dashboard_metrics", tracked_calculator)

    try:
        first = dashboard_metrics(seeded_session)
        second = dashboard_metrics(seeded_session)
        third = dashboard_metrics(seeded_session)
    finally:
        app_utils.clear_dashboard_metrics_cache()

    assert calculator_calls["count"] == 2
    assert first == second
    assert third == first


def test_run_migrations_ensures_large_dataset_indexes_exist(seeded_session):
    student_indexes = {row[1] for row in index_rows(seeded_session, "students")}
    payment_indexes = {row[1] for row in index_rows(seeded_session, "payments")}

    assert "ix_students_status_id" in student_indexes
    assert "ix_students_status_full_name" in student_indexes
    assert "ix_payments_status_payment_date" in payment_indexes
    assert "ix_payments_student_payment_date" in payment_indexes
    assert "ix_payments_service_type_payment_date" in payment_indexes


def test_active_lookups_only_load_students_when_requested(seeded_session):
    ensure_operational_test_data(seeded_session)

    default_lookups = app_utils.active_lookups(seeded_session)
    explicit_lookups = app_utils.active_lookups(seeded_session, include_students=True)

    assert "students" not in default_lookups
    assert "students" in explicit_lookups
    assert any(student.student_code == "TEST-STU-001" for student in explicit_lookups["students"])


def test_recurring_course_and_transport_fees_convert_to_monthly_amounts_for_reminders(seeded_session):
    settings = seeded_session.get(Setting, 1)
    assert settings is not None

    course = Course(
        name="Installment Course",
        code="INSTALLMENT-COURSE",
        fees=12000,
        frequency="Yearly",
        status="Active",
        description="Yearly course for monthly conversion test.",
    )
    route = TransportRoute(
        route_name="Installment Route",
        pickup_points="Point C",
        fee_amount=3000,
        frequency="Quarterly",
        status="Active",
    )
    student = Student(
        student_code="INSTALL-STU-001",
        full_name="Installment Student",
        email="installment.student@example.com",
        phone="9999990020",
        parent_name="Installment Parent",
        status="Active",
        address="Installment Address",
        joined_on=date(2026, 1, 1),
        course=course,
        transport_route=route,
    )
    seeded_session.add_all([course, route, student])
    seeded_session.flush()

    course_fee = Fee(
        name="Installment Course Fee",
        category="Course",
        amount=12000,
        frequency="Yearly",
        status="Active",
        target_type="Course",
        target_id=course.id,
    )
    transport_fee = Fee(
        name="Installment Transport Fee",
        category="Transport",
        amount=3000,
        frequency="Quarterly",
        status="Active",
        target_type="Transport",
        target_id=route.id,
    )
    seeded_session.add_all([course_fee, transport_fee])
    seeded_session.commit()

    try:
        fees = calculate_student_fees_and_payments(seeded_session, student)

        assert fees["current_cycle_amount"] == 2000.0
        assert fees["total_fees"] == 8000.0
        assert fees["previous_pending_amount"] == 6000.0
        assert fees["remaining_balance"] == 8000.0

        course_item = next(item for item in fees["fee_items"] if item["name"] == "Installment Course Fee")
        transport_item = next(
            item for item in fees["fee_items"] if item["name"] == "Installment Transport Fee"
        )
        assert float(course_item["current_month_amount"]) == 1000.0
        assert float(transport_item["current_month_amount"]) == 1000.0
        assert float(course_item["due_amount"]) == 4000.0
        assert float(transport_item["due_amount"]) == 4000.0

        message = reminder_message(settings, student, fees)
        assert "This Month's Charges: 2000.00" in message
        assert "Installment Course Fee (monthly from yearly plan): 1000.00" in message
        assert "Installment Transport Fee (monthly from quarterly plan): 1000.00" in message
        assert "Earlier Pending Balance: 6000.00" in message
    finally:
        for model in (course_fee, transport_fee, student, route, course):
            attached = seeded_session.get(type(model), model.id)
            if attached is not None:
                seeded_session.delete(attached)
        seeded_session.commit()


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


def test_payments_filter_supports_student_code_and_name_search(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    student_one = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    student_two = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-002"))
    assert student_one is not None
    assert student_two is not None
    assert student_one.course is not None
    assert student_two.transport_route is not None

    payment_one = seeded_session.scalar(select(Payment).where(Payment.reference == "FILTER-STUDENT-ONE"))
    if payment_one is None:
        payment_one = Payment(
            student_id=student_one.id,
            service_type="course",
            service_id=student_one.course.id,
            amount=2100.0,
            reference="FILTER-STUDENT-ONE",
            status="Paid",
        )
        seeded_session.add(payment_one)

    payment_two = seeded_session.scalar(select(Payment).where(Payment.reference == "FILTER-STUDENT-TWO"))
    if payment_two is None:
        payment_two = Payment(
            student_id=student_two.id,
            service_type="transport",
            service_id=student_two.transport_route.id,
            amount=2200.0,
            reference="FILTER-STUDENT-TWO",
            status="Paid",
        )
        seeded_session.add(payment_two)
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

        filtered_by_code = client.get(f"/payments?student_query={student_one.student_code}")
        assert filtered_by_code.status_code == 200
        assert "FILTER-STUDENT-ONE" in filtered_by_code.text
        assert "FILTER-STUDENT-TWO" not in filtered_by_code.text

        filtered_by_name = client.get("/payments?student_query=Test Student Two")
        assert filtered_by_name.status_code == 200
        assert "FILTER-STUDENT-TWO" in filtered_by_name.text
        assert "FILTER-STUDENT-ONE" not in filtered_by_name.text

        export_response = client.get("/payments/export?student_query=Test Student Two")
        assert export_response.status_code == 200
        assert "FILTER-STUDENT-TWO" in export_response.text
        assert "FILTER-STUDENT-ONE" not in export_response.text
    finally:
        cleanup_one = seeded_session.scalar(select(Payment).where(Payment.reference == "FILTER-STUDENT-ONE"))
        if cleanup_one is not None:
            seeded_session.delete(cleanup_one)
        cleanup_two = seeded_session.scalar(select(Payment).where(Payment.reference == "FILTER-STUDENT-TWO"))
        if cleanup_two is not None:
            seeded_session.delete(cleanup_two)
        seeded_session.commit()


def test_payments_export_returns_csv_attachment_header(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)

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

    export_response = client.get("/payments/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-disposition"] == "attachment; filename=payments.csv"
    assert export_response.text.startswith(
        "Type,Fee Item,Student ID,Student Name,Amount,Date,Method,Status,Reference"
    )


def test_students_page_shows_payment_action_link(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert student is not None

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
    assert students_page.status_code == 200
    assert f"/payments?create=1&create_student_id={student.id}" in students_page.text

    create_payment_page = client.get(f"/payments?create=1&create_student_id={student.id}")
    assert create_payment_page.status_code == 200
    assert f'<option value="{student.id}" selected>' in create_payment_page.text


def test_students_page_paginates_large_search_results(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None

    created_students: list[Student] = []
    for index in range(55):
        student_code = f"PAGED-STU-{index:03d}"
        student = seeded_session.scalar(select(Student).where(Student.student_code == student_code))
        if student is None:
            student = Student(
                student_code=student_code,
                full_name=f"Paged Student {index:03d}",
                email=f"paged.student.{index:03d}@example.com",
                phone=f"900000{index:04d}",
                parent_name=f"Paged Parent {index:03d}",
                status="Active",
                address="Pagination Test Address",
                joined_on=date(2026, 4, 6),
                course_id=course.id,
            )
            seeded_session.add(student)
            created_students.append(student)
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

        page_two = client.get("/students?search=PAGED-STU-&page=2")
        assert page_two.status_code == 200
        assert "Showing 51-55 of 55 records." in page_two.text
        assert "Page 2 of 2." in page_two.text
        assert "PAGED-STU-000" in page_two.text
        assert "PAGED-STU-004" in page_two.text
        assert "PAGED-STU-054" not in page_two.text
        assert "/students?" in page_two.text
        assert "search=PAGED-STU-" in page_two.text
        assert "page=1" in page_two.text
    finally:
        for student in created_students:
            attached_student = seeded_session.scalar(select(Student).where(Student.student_code == student.student_code))
            if attached_student is not None:
                seeded_session.delete(attached_student)
        seeded_session.commit()


def test_students_search_falls_back_to_substring_matches(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)

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

    response = client.get("/students?search=Student Two")
    assert response.status_code == 200
    assert "Test Student Two" in response.text
    assert "Test Student One" not in response.text


def test_students_page_is_read_only_and_points_to_admissions(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)

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
    assert students_page.status_code == 200
    assert "New students are added automatically after admission." in students_page.text
    assert "Add Student" not in students_page.text

    forced_create_page = client.get("/students?create=1")
    assert forced_create_page.status_code == 200
    assert "Create student records from Admissions." in forced_create_page.text
    assert "Save Student" not in forced_create_page.text


def test_admissions_page_creates_student_applies_admission_fee_and_redirects_to_receipt(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None
    existing_payments = seeded_session.scalars(
        select(Payment).where(Payment.reference == "ADM-TEST-001")
    ).all()
    for existing_payment in existing_payments:
        seeded_session.delete(existing_payment)
    if existing_payments:
        seeded_session.commit()
    existing_student = seeded_session.scalar(select(Student).where(Student.student_code == "ADM-TEST-001"))
    if existing_student is not None:
        seeded_session.delete(existing_student)
        seeded_session.commit()
    admission_fee = seeded_session.scalar(select(Fee).where(Fee.name == "Admission Auto Fee"))
    if admission_fee is None:
        admission_fee = Fee(
            name="Admission Auto Fee",
            category="Admission",
            amount=2500,
            frequency="One Time",
            status="Active",
            target_type="General",
            description="Admission fee used by automated tests.",
        )
        seeded_session.add(admission_fee)
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

    admissions_page = client.get("/admissions?create=1")
    assert admissions_page.status_code == 200
    assert "Add Admission" in admissions_page.text
    assert 'action="/students/create" class="form-grid" target="_blank"' in admissions_page.text
    admission_csrf_token = extract_csrf_token(admissions_page.text)

    response = client.post(
        "/students/create",
        data={
            "csrf_token": admission_csrf_token,
            "return_path": "/admissions",
            "student_code": "ADM-TEST-001",
            "full_name": "Admission Test Student",
            "email": "admission.student@example.com",
            "phone": "9999990011",
            "parent_name": "Admission Parent",
            "status": "Active",
            "joined_on": "2026-04-06",
            "course_id": str(course.id),
            "hostel_id": "",
            "transport_id": "",
            "address": "Admission Address",
            "admission_method": "UPI",
            "admission_reference": "ADM-TEST-001",
            "admission_notes": "Created during admission flow test",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    receipt_location = response.headers["location"]
    assert receipt_location.startswith("/payments/")
    assert receipt_location.endswith("/bill")

    created_student = seeded_session.scalar(select(Student).where(Student.student_code == "ADM-TEST-001"))
    assert created_student is not None
    created_payment = seeded_session.scalar(select(Payment).where(Payment.reference == "ADM-TEST-001"))
    assert created_payment is not None
    assert created_payment.student_id == created_student.id
    assert created_payment.status == "Paid"
    assert created_payment.amount == 2500.0
    assert created_payment.service_type == "admission"

    students_page = client.get("/students")
    assert students_page.status_code == 200
    assert "Admission Test Student" in students_page.text

    seeded_session.delete(created_payment)
    seeded_session.delete(created_student)
    cleanup_fee = seeded_session.scalar(select(Fee).where(Fee.name == "Admission Auto Fee"))
    if cleanup_fee is not None:
        seeded_session.delete(cleanup_fee)
    seeded_session.commit()


def test_students_require_course_while_hostel_and_transport_remain_optional(seeded_session, client):
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

    admissions_page = client.get("/admissions?create=1")
    student_csrf_token = extract_csrf_token(admissions_page.text)
    response = client.post(
        "/students/create",
        data={
            "csrf_token": student_csrf_token,
            "return_path": "/admissions",
            "student_code": "NO-COURSE-001",
            "full_name": "No Course Student",
            "email": "nocourse.student@example.com",
            "phone": "9999990040",
            "parent_name": "No Course Parent",
            "status": "Active",
            "joined_on": "2026-04-06",
            "course_id": "",
            "hostel_id": "",
            "transport_id": "",
            "address": "No Course Address",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admissions?create=1&error=missing_fields"


def test_student_promotion_reuses_admission_flow_and_updates_same_student(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)

    stale_payment = seeded_session.scalar(select(Payment).where(Payment.reference == "PROMO-REF-001"))
    if stale_payment is not None:
        seeded_session.delete(stale_payment)

    stale_student = seeded_session.scalar(select(Student).where(Student.student_code == "PROMO-STU-001"))
    if stale_student is not None:
        seeded_session.delete(stale_student)

    stale_sections = seeded_session.scalars(
        select(Section).where(Section.code.in_(["PROMO-A-9001", "PROMO-A-9002"]))
    ).all()
    for section in stale_sections:
        seeded_session.delete(section)

    stale_courses = seeded_session.scalars(
        select(Course).where(Course.code.in_(["PROMO-CLASS-9001", "PROMO-CLASS-9002"]))
    ).all()
    for course in stale_courses:
        seeded_session.delete(course)

    if stale_payment is not None or stale_student is not None or stale_sections or stale_courses:
        seeded_session.commit()

    active_admission_fee = seeded_session.scalar(
        select(Fee).where(Fee.category == "Admission", Fee.status == "Active").order_by(Fee.id)
    )
    created_admission_fee = None
    if active_admission_fee is None:
        created_admission_fee = Fee(
            name="Promotion Admission Fee",
            category="Admission",
            amount=1800,
            frequency="One Time",
            status="Active",
            target_type="General",
            description="Admission fee created for promotion test coverage.",
        )
        seeded_session.add(created_admission_fee)
        seeded_session.flush()

    course_one = Course(
        name="Class 9001",
        code="PROMO-CLASS-9001",
        fees=1000,
        frequency="Monthly",
        status="Active",
        description="Promotion source course.",
    )
    course_two = Course(
        name="Class 9002",
        code="PROMO-CLASS-9002",
        fees=1200,
        frequency="Monthly",
        status="Active",
        description="Promotion destination course.",
    )
    seeded_session.add_all([course_one, course_two])
    seeded_session.flush()

    section_one = Section(
        course_id=course_one.id,
        name="Section A",
        code="PROMO-A-9001",
        class_teacher="Teacher One",
        room_name="Room 1",
        status="Active",
    )
    section_two = Section(
        course_id=course_two.id,
        name="Section A",
        code="PROMO-A-9002",
        class_teacher="Teacher Two",
        room_name="Room 2",
        status="Active",
    )
    seeded_session.add_all([section_one, section_two])
    seeded_session.flush()

    student = Student(
        student_code="PROMO-STU-001",
        full_name="Promotion Student",
        email="promotion.student@example.com",
        phone="9999990050",
        parent_name="Promotion Parent",
        status="Active",
        address="Promotion Address",
        joined_on=date(2026, 4, 1),
        course_id=course_one.id,
        section_id=section_one.id,
    )
    seeded_session.add(student)
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

    promotion_page = client.get(f"/admissions?promote={student.id}")
    assert promotion_page.status_code == 200
    assert f'name="promotion_source_student_id" value="{student.id}"' in promotion_page.text
    assert "Promote Student" in promotion_page.text
    assert f'<option value="{course_two.id}" selected>{course_two.name}</option>' in promotion_page.text

    promotion_csrf_token = extract_csrf_token(promotion_page.text)
    response = client.post(
        "/students/create",
        data={
            "csrf_token": promotion_csrf_token,
            "return_path": "/admissions",
            "promotion_source_student_id": str(student.id),
            "student_code": "PROMO-STU-001",
            "full_name": "Promotion Student",
            "email": "promotion.student@example.com",
            "phone": "9999990050",
            "parent_name": "Promotion Parent",
            "status": "Active",
            "joined_on": "2026-04-07",
            "course_id": str(course_two.id),
            "section_id": str(section_two.id),
            "hostel_id": "",
            "transport_id": "",
            "address": "Promoted Address",
            "admission_method": "Cash",
            "admission_reference": "PROMO-REF-001",
            "admission_notes": "Promoted to the next class",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/payments/")
    assert response.headers["location"].endswith("/bill")

    seeded_session.expire_all()
    updated_student = seeded_session.get(Student, student.id)
    assert updated_student is not None
    assert updated_student.course_id == course_two.id
    assert updated_student.section_id == section_two.id
    assert updated_student.joined_on == date(2026, 4, 7)
    assert updated_student.address == "Promoted Address"

    promoted_students = seeded_session.scalars(
        select(Student).where(Student.student_code == "PROMO-STU-001")
    ).all()
    assert len(promoted_students) == 1

    promotion_payment = seeded_session.scalar(select(Payment).where(Payment.reference == "PROMO-REF-001"))
    assert promotion_payment is not None
    assert promotion_payment.student_id == student.id
    assert promotion_payment.status == "Paid"
    assert promotion_payment.service_type == "admission"

    seeded_session.delete(promotion_payment)
    seeded_session.delete(updated_student)
    seeded_session.delete(section_one)
    seeded_session.delete(section_two)
    seeded_session.delete(course_one)
    seeded_session.delete(course_two)
    if created_admission_fee is not None:
        seeded_session.delete(created_admission_fee)
    seeded_session.commit()


def test_payment_bill_page_renders_for_recorded_payment(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)

    payment = seeded_session.scalar(select(Payment).where(Payment.reference == "TEST-BASE-PAYMENT"))
    assert payment is not None

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

    response = client.get(f"/payments/{payment.id}/bill")
    assert response.status_code == 200
    assert "Payment Receipt" in response.text
    assert "TEST-BASE-PAYMENT" in response.text
    assert "Print Receipt" in response.text
    assert "Back to Payments" in response.text
    assert "<script>window.print();</script>" not in response.text


def test_payments_create_form_uses_new_tab_and_hides_manual_admission_option(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert student is not None

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

    response = client.get(f"/payments?create=1&create_student_id={student.id}")
    assert response.status_code == 200
    assert 'action="/payments/create" class="form-grid" target="_blank"' in response.text
    assert '<option value="admission"' not in response.text
    assert 'The receipt opens in a new tab so the Payments screen stays available.' in response.text


def test_payments_create_page_uses_lightweight_student_picker(seeded_session, client):
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

    response = client.get("/payments?create=1")
    assert response.status_code == 200
    assert "Find Student" in response.text
    assert 'list="payment-student-lookup-options"' in response.text
    assert 'id="payment-student-options"' not in response.text


def test_payment_student_search_endpoint_returns_matching_active_students(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)

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

    response = client.get("/payments/student-search?q=TEST-STU-00")
    assert response.status_code == 200
    payload = response.json()
    labels = [item["label"] for item in payload["results"]]
    assert "TEST-STU-001 - Test Student One" in labels
    assert "TEST-STU-002 - Test Student Two" in labels


def test_payments_page_paginates_filtered_results(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None

    student = seeded_session.scalar(select(Student).where(Student.student_code == "PAGED-PAY-STU"))
    if student is None:
        student = Student(
            student_code="PAGED-PAY-STU",
            full_name="Paged Payment Student",
            email="paged.payment.student@example.com",
            phone="9888800000",
            parent_name="Paged Payment Parent",
            status="Active",
            address="Payment Pagination Address",
            joined_on=date(2026, 4, 6),
            course_id=course.id,
        )
        seeded_session.add(student)
        seeded_session.flush()

    created_refs: list[str] = []
    for index in range(55):
        reference = f"PAGED-PAY-{index:03d}"
        payment = seeded_session.scalar(select(Payment).where(Payment.reference == reference))
        if payment is None:
            payment = Payment(
                student_id=student.id,
                student_code=student.student_code,
                student_name=student.full_name,
                parent_name=student.parent_name or "",
                service_type="other",
                service_id=None,
                service_name="Paged Payment",
                amount=100 + index,
                payment_date=date(2026, 4, 6),
                method="Cash",
                reference=reference,
                status="Paid",
            )
            seeded_session.add(payment)
            created_refs.append(reference)
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

        page_two = client.get("/payments?student_query=PAGED-PAY-STU&page=2")
        assert page_two.status_code == 200
        assert "Showing 51-55 of 55 records." in page_two.text
        assert "Page 2 of 2." in page_two.text
        assert "PAGED-PAY-000" in page_two.text
        assert "PAGED-PAY-004" in page_two.text
        assert "PAGED-PAY-054" not in page_two.text
        assert "/payments?" in page_two.text
        assert "student_query=PAGED-PAY-STU" in page_two.text
        assert "page=1" in page_two.text
    finally:
        for reference in created_refs:
            payment_to_cleanup = seeded_session.scalar(select(Payment).where(Payment.reference == reference))
            if payment_to_cleanup is not None:
                seeded_session.delete(payment_to_cleanup)
        attached_student = seeded_session.scalar(select(Student).where(Student.student_code == "PAGED-PAY-STU"))
        if attached_student is not None:
            seeded_session.delete(attached_student)
        seeded_session.commit()


def test_deleted_student_keeps_payment_history_and_receipt(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None

    student = seeded_session.scalar(select(Student).where(Student.student_code == "ARCHIVE-STU-001"))
    if student is None:
        student = Student(
            student_code="ARCHIVE-STU-001",
            full_name="Archived Receipt Student",
            email="archived.student@example.com",
            phone="9999990042",
            parent_name="Archived Parent",
            status="Active",
            address="Archive Address",
            joined_on=date(2026, 4, 6),
            course_id=course.id,
        )
        seeded_session.add(student)
        seeded_session.flush()

    payment = seeded_session.scalar(select(Payment).where(Payment.reference == "ARCHIVE-PAY-001"))
    if payment is None:
        payment = Payment(
            student_id=student.id,
            service_type="other",
            service_id=None,
            service_name="Archive Test Payment",
            amount=999.0,
            payment_date=date(2026, 4, 6),
            method="Cash",
            reference="ARCHIVE-PAY-001",
            notes="Archive retention test",
            status="Paid",
        )
        seeded_session.add(payment)
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
    delete_csrf_token = extract_csrf_token(students_page.text)
    delete_response = client.post(
        f"/students/{student.id}/delete",
        data={
            "csrf_token": delete_csrf_token,
            "return_path": "/students",
        },
        follow_redirects=False,
    )
    assert delete_response.status_code == 303
    assert delete_response.headers["location"] == "/students"

    seeded_session.expire_all()
    deleted_student = seeded_session.scalar(select(Student).where(Student.student_code == "ARCHIVE-STU-001"))
    archived_payment = seeded_session.scalar(select(Payment).where(Payment.reference == "ARCHIVE-PAY-001"))
    assert deleted_student is None
    assert archived_payment is not None
    assert archived_payment.student_id is None
    assert archived_payment.student_code == "ARCHIVE-STU-001"
    assert archived_payment.student_name == "Archived Receipt Student"
    assert archived_payment.parent_name == "Archived Parent"
    assert archived_payment.snapshot_total_fees > 0
    assert archived_payment.snapshot_remaining_balance > 0

    payments_response = client.get("/payments")
    assert payments_response.status_code == 200
    assert "ARCHIVE-STU-001 - Archived Receipt Student" in payments_response.text

    bill_response = client.get(f"/payments/{archived_payment.id}/bill")
    assert bill_response.status_code == 200
    assert "ARCHIVE-STU-001" in bill_response.text
    assert "Archived Receipt Student" in bill_response.text
    assert "Outstanding Balance" in bill_response.text

    payment_to_cleanup = seeded_session.scalar(select(Payment).where(Payment.reference == "ARCHIVE-PAY-001"))
    if payment_to_cleanup is not None:
        seeded_session.delete(payment_to_cleanup)
        seeded_session.commit()


def test_public_routes_render_without_auth(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)

    home_response = client.get("/", follow_redirects=False)
    assert home_response.status_code == 303
    assert home_response.headers["location"] == "/login"

    login_response = client.get("/login")
    assert login_response.status_code == 200
    assert "Pinaki" in login_response.text


def test_dashboard_disables_cache_and_includes_idle_timeout(seeded_session, client):
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

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "no-store" in dashboard_response.headers["cache-control"].lower()
    assert "no-cache" in dashboard_response.headers["cache-control"].lower()
    assert dashboard_response.headers["pragma"] == "no-cache"
    assert dashboard_response.headers["expires"] == "0"
    assert (
        f'data-session-timeout-ms="{app_utils.SESSION_IDLE_TIMEOUT_SECONDS * 1000}"'
        in dashboard_response.text
    )


def test_session_expires_after_fifteen_minutes_of_inactivity(seeded_session, client, monkeypatch):
    configure_setup_state(seeded_session, setup_completed=True)

    monkeypatch.setattr(app_utils, "current_session_timestamp", lambda: 1_000)
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

    active_response = client.get("/dashboard", follow_redirects=False)
    assert active_response.status_code == 200

    monkeypatch.setattr(
        app_utils,
        "current_session_timestamp",
        lambda: 1_000 + app_utils.SESSION_IDLE_TIMEOUT_SECONDS + 1,
    )
    expired_response = client.get("/dashboard", follow_redirects=False)
    assert expired_response.status_code == 303
    assert expired_response.headers["location"].startswith("/login?next=%2Fdashboard")


def test_dashboard_footer_uses_hardcoded_branding(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    settings = seeded_session.get(Setting, 1)
    assert settings is not None
    settings.developer_name = ""
    settings.developer_email = ""
    settings.developer_phone = ""
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

    dashboard_response = client.get("/dashboard")
    assert dashboard_response.status_code == 200
    assert "Pinaki Sarangi" in dashboard_response.text
    assert "pinungr@gmail.com" in dashboard_response.text
    assert "7751952860" in dashboard_response.text


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


def test_admin_created_users_are_saved_as_clerks(seeded_session, client):
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

    users_page = client.get("/users?create=1")
    users_csrf_token = extract_csrf_token(users_page.text)
    response = client.post(
        "/users/create",
        data={
            "csrf_token": users_csrf_token,
            "full_name": "Clerk User",
            "username": "clerkuser",
            "email": "clerkuser@school.local",
            "password": "ClerkPass@2026",
            "role": "Admin",
            "status": "Active",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/users"

    created_user = seeded_session.scalar(select(User).where(User.username == "clerkuser"))
    assert created_user is not None
    assert created_user.role == "Clerk"

    seeded_session.delete(created_user)
    seeded_session.commit()


def test_clerk_cannot_manage_catalog_records(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    clerk_user = seeded_session.scalar(select(User).where(User.username == "catalogclerk"))
    if clerk_user is None:
        clerk_user = User(
            full_name="Catalog Clerk",
            username="catalogclerk",
            email="catalogclerk@school.local",
            password_hash=hash_password("ClerkPass@2026"),
            role="Clerk",
            status="Active",
        )
        seeded_session.add(clerk_user)
        seeded_session.commit()

    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "identifier": "catalogclerk",
            "password": "ClerkPass@2026",
            "next_path": "/dashboard",
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    fees_page = client.get("/fees?create=1")
    assert fees_page.status_code == 200
    assert "Add Fee" not in fees_page.text
    assert "Save Fee" not in fees_page.text

    fees_csrf_token = extract_csrf_token(fees_page.text)
    response = client.post(
        "/fees/create",
        data={
            "csrf_token": fees_csrf_token,
            "name": "Blocked Clerk Fee",
            "category": "Admission",
            "amount": "500",
            "frequency": "One Time",
            "status": "Active",
            "description": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    assert seeded_session.scalar(select(Fee).where(Fee.name == "Blocked Clerk Fee")) is None


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


def test_settings_backup_and_restore_round_trip_database_and_uploads(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    marker_path = UPLOADS_DIR / "backup-restore-marker.txt"
    original_school_name = ""

    with SessionLocal() as session:
        settings = session.get(Setting, 1)
        assert settings is not None
        original_school_name = settings.school_name

    marker_path.write_bytes(b"backup-marker")

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
        backup_response = client.post(
            "/settings/backup",
            data={"csrf_token": settings_csrf_token},
        )

        assert backup_response.status_code == 200
        assert backup_response.headers["content-disposition"].endswith('.pinaki-backup"')
        backup_bytes = backup_response.content
        assert backup_bytes

        with SessionLocal() as session:
            settings = session.get(Setting, 1)
            assert settings is not None
            settings.school_name = "Changed After Backup"
            session.commit()
        marker_path.unlink(missing_ok=True)

        restore_page = client.get("/settings")
        restore_csrf_token = extract_csrf_token(restore_page.text)
        restore_response = client.post(
            "/settings/restore",
            data={"csrf_token": restore_csrf_token},
            files={"backup_file": ("pinaki-backup.pinaki-backup", backup_bytes, "application/zip")},
            follow_redirects=False,
        )

        assert restore_response.status_code == 303
        assert restore_response.headers["location"] == "/settings?success=restore_completed"

        with SessionLocal() as session:
            restored_settings = session.get(Setting, 1)
            assert restored_settings is not None
            assert restored_settings.school_name == original_school_name
        assert marker_path.read_bytes() == b"backup-marker"
    finally:
        marker_path.unlink(missing_ok=True)


def test_settings_restore_rejects_non_pinaki_backup(seeded_session, client):
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

    fake_backup = io.BytesIO()
    with zipfile.ZipFile(fake_backup, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "metadata.json",
            '{"app_name":"Not Pinaki","format_version":1}',
        )
        archive.writestr("data/school.db", b"not-a-real-database")

    restore_page = client.get("/settings")
    restore_csrf_token = extract_csrf_token(restore_page.text)
    restore_response = client.post(
        "/settings/restore",
        data={"csrf_token": restore_csrf_token},
        files={"backup_file": ("wrong.pinaki-backup", fake_backup.getvalue(), "application/zip")},
        follow_redirects=False,
    )

    assert restore_response.status_code == 303
    assert restore_response.headers["location"] == "/settings?error=invalid_backup_file"


def test_data_repair_page_loads_for_admin(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)

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

    response = client.get("/settings/data-repair?table=students")
    assert response.status_code == 200
    assert "Data Repair" in response.text
    assert "Export Full Database" in response.text
    assert "Import Full Database" in response.text
    assert "Export Students CSV" in response.text


def test_data_repair_can_update_student_record(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None
    student = seeded_session.scalar(select(Student).where(Student.student_code == "REPAIR-STU-001"))
    if student is None:
        student = Student(
            student_code="REPAIR-STU-001",
            full_name="Repair Student",
            email="repair.student@example.com",
            phone="9999990099",
            parent_name="Repair Parent",
            status="Active",
            address="Repair Address",
            joined_on=date(2026, 4, 7),
            course_id=course.id,
        )
        seeded_session.add(student)
        seeded_session.commit()
    assert student is not None

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

    edit_page = client.get(f"/settings/data-repair?table=students&edit={student.id}")
    assert edit_page.status_code == 200
    edit_csrf_token = extract_csrf_token(edit_page.text)

    response = client.post(
        f"/settings/data-repair/students/{student.id}/update",
        data={
            "csrf_token": edit_csrf_token,
            "search": "",
            "student_code": student.student_code,
            "full_name": "Data Repair Student",
            "email": student.email,
            "phone": "8888888888",
            "parent_name": "Data Repair Parent",
            "status": "Active",
            "joined_on": student.joined_on.isoformat(),
            "course_id": str(student.course_id),
            "section_id": str(student.section_id or ""),
            "hostel_id": str(student.hostel_id or ""),
            "transport_id": str(student.transport_id or ""),
            "address": "Updated from data repair",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings/data-repair?table=students&success=row_saved"

    seeded_session.expire_all()
    updated_student = seeded_session.get(Student, student.id)
    assert updated_student is not None
    assert updated_student.full_name == "Data Repair Student"
    assert updated_student.phone == "8888888888"
    assert updated_student.parent_name == "Data Repair Parent"
    assert updated_student.address == "Updated from data repair"
    seeded_session.delete(updated_student)
    seeded_session.commit()


def test_data_repair_can_export_and_import_students_csv(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None
    student = seeded_session.scalar(select(Student).where(Student.student_code == "REPAIR-STU-CSV"))
    if student is None:
        student = Student(
            student_code="REPAIR-STU-CSV",
            full_name="Repair CSV Student",
            email="repair.csv@example.com",
            phone="9999990088",
            parent_name="Repair CSV Parent",
            status="Active",
            address="Repair CSV Address",
            joined_on=date(2026, 4, 8),
            course_id=course.id,
        )
        seeded_session.add(student)
        seeded_session.commit()
    assert student is not None

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

    export_response = client.get("/settings/data-repair/students/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/csv")

    reader = csv.DictReader(io.StringIO(export_response.text))
    rows = list(reader)
    target_row = next(row for row in rows if row["id"] == str(student.id))
    target_row["full_name"] = "CSV Import Student"
    target_row["phone"] = "7777777777"

    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=reader.fieldnames)
    writer.writeheader()
    writer.writerow(target_row)

    data_repair_page = client.get("/settings/data-repair?table=students")
    import_csrf_token = extract_csrf_token(data_repair_page.text)
    import_response = client.post(
        "/settings/data-repair/students/import",
        data={
            "csrf_token": import_csrf_token,
            "search": "",
        },
        files={
            "import_file": ("students.csv", csv_buffer.getvalue(), "text/csv"),
        },
        follow_redirects=False,
    )

    assert import_response.status_code == 303
    assert import_response.headers["location"] == "/settings/data-repair?table=students&success=table_imported"

    seeded_session.expire_all()
    updated_student = seeded_session.get(Student, student.id)
    assert updated_student is not None
    assert updated_student.full_name == "CSV Import Student"
    assert updated_student.phone == "7777777777"
    seeded_session.delete(updated_student)
    seeded_session.commit()


def test_get_logout_clears_the_session(seeded_session, client):
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

    logout_response = client.get("/logout", follow_redirects=False)
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


def test_payment_creation_redirects_to_receipt(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    course_fee = seeded_session.scalar(select(Fee).where(Fee.name == "Test Course Fee"))
    assert student is not None
    assert course_fee is not None

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
            "service_id": str(course_fee.id),
            "amount": "1000",
            "payment_date": "2026-04-05",
            "method": "Cash",
            "reference": "PAYMENT-RECEIPT-TEST",
            "notes": "",
            "status": "Paid",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/payments/")
    assert response.headers["location"].endswith("/bill")

    created_payment = seeded_session.scalar(
        select(Payment).where(Payment.reference == "PAYMENT-RECEIPT-TEST")
    )
    assert created_payment is not None

    seeded_session.delete(created_payment)
    seeded_session.commit()


def test_fees_reject_negative_fee_values(seeded_session, client):
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

    fees_page = client.get("/fees?create=1")
    fee_csrf_token = extract_csrf_token(fees_page.text)
    response = client.post(
        "/fees/create",
        data={
            "csrf_token": fee_csrf_token,
            "name": "Bad Fee",
            "category": "Course",
            "amount": "-10",
            "frequency": "Monthly",
            "target_type": "General",
            "status": "Active",
            "description": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/fees?create=1&error=invalid_amount"


def test_course_fee_requires_linked_course_record(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)

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

    fees_page = client.get("/fees?create=1")
    fee_csrf_token = extract_csrf_token(fees_page.text)
    response = client.post(
        "/fees/create",
        data={
            "csrf_token": fee_csrf_token,
            "name": "Course Link Rule Test",
            "category": "Course",
            "amount": "1500",
            "frequency": "Monthly",
            "target_id": "",
            "status": "Active",
            "description": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/fees?create=1&error=invalid_target"


def test_course_fee_uses_course_table_as_subcategory(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None

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

    fees_page = client.get("/fees?create=1")
    assert "Select course" in fees_page.text
    fee_csrf_token = extract_csrf_token(fees_page.text)
    response = client.post(
        "/fees/create",
        data={
            "csrf_token": fee_csrf_token,
            "name": "Course Subcategory Test",
            "category": "Course",
            "amount": "1800",
            "frequency": "Monthly",
            "target_id": str(course.id),
            "status": "Active",
            "description": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/fees"

    fee = seeded_session.scalar(select(Fee).where(Fee.name == "Course Subcategory Test"))
    assert fee is not None
    assert fee.target_type == "Course"
    assert fee.target_id == course.id

    seeded_session.delete(fee)
    seeded_session.commit()


def test_transport_route_saves_vehicle_and_driver_details(seeded_session, client):
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

    transport_page = client.get("/transport?create=1")
    assert transport_page.status_code == 200
    assert "Vehicle No" in transport_page.text
    assert "Driver Name" in transport_page.text
    assert "Driver Phone" in transport_page.text
    transport_csrf_token = extract_csrf_token(transport_page.text)

    response = client.post(
        "/transport/create",
        data={
            "csrf_token": transport_csrf_token,
            "route_name": "Route Detail Test",
            "vehicle_no": "OD-02-AB-1234",
            "driver_name": "Ramesh Driver",
            "driver_phone": "9876543211",
            "pickup_points": "Stop 1, Stop 2",
            "status": "Active",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/transport"

    route = seeded_session.scalar(
        select(TransportRoute).where(TransportRoute.route_name == "Route Detail Test")
    )
    assert route is not None
    assert route.vehicle_no == "OD-02-AB-1234"
    assert route.driver_name == "Ramesh Driver"
    assert route.driver_phone == "9876543211"

    view_response = client.get(f"/transport?view={route.id}")
    assert view_response.status_code == 200
    assert "OD-02-AB-1234" in view_response.text
    assert "Ramesh Driver" in view_response.text
    assert "9876543211" in view_response.text

    seeded_session.delete(route)
    seeded_session.commit()


def test_sections_can_be_created_under_courses_and_student_search_uses_section(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert course is not None
    assert student is not None

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

    courses_page = client.get("/courses?section_create=1")
    assert courses_page.status_code == 200
    assert "Add Section" in courses_page.text
    section_csrf_token = extract_csrf_token(courses_page.text)

    response = client.post(
        "/sections/create",
        data={
            "csrf_token": section_csrf_token,
            "course_id": str(course.id),
            "name": "Section A",
            "code": "A",
            "class_teacher": "Teacher A",
            "room_name": "Room 101",
            "status": "Active",
            "description": "Primary section for tests",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/courses"

    section = seeded_session.scalar(select(Section).where(Section.name == "Section A"))
    assert section is not None
    assert section.course_id == course.id

    student.section_id = section.id
    seeded_session.commit()

    students_page = client.get("/students?search=Section A")
    assert students_page.status_code == 200
    assert "Test Student One" in students_page.text

    student.section_id = None
    seeded_session.delete(section)
    seeded_session.commit()


def test_section_form_lists_all_courses_even_when_course_table_is_filtered(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    hidden_course = seeded_session.scalar(select(Course).where(Course.code == "FILTER-HIDDEN"))
    if hidden_course is None:
        hidden_course = Course(
            name="Filter Hidden Course",
            code="FILTER-HIDDEN",
            fees=4200,
            frequency="Monthly",
            status="Active",
            description="Used to verify section forms are not tied to the course filter.",
        )
        seeded_session.add(hidden_course)
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

    courses_page = client.get("/courses?search=TEST-COURSE&section_create=1")
    assert courses_page.status_code == 200
    assert "Filter Hidden Course" in courses_page.text


def test_launcher_browser_fallback_keeps_running_instead_of_shutting_down(monkeypatch):
    launcher = desktop_launcher.DesktopLauncher()
    launcher.url = "http://127.0.0.1:8765"

    opened_urls: list[tuple[str, int]] = []
    keep_running_calls: list[bool] = []

    monkeypatch.setattr(desktop_launcher, "find_browser_executable", lambda: None)
    monkeypatch.setattr(desktop_launcher, "startup_target_path", lambda: "/login")
    monkeypatch.setattr(
        desktop_launcher.webbrowser,
        "open",
        lambda url, new=0: opened_urls.append((url, new)),
    )
    monkeypatch.setattr(
        launcher,
        "keep_running_in_browser_fallback",
        lambda: keep_running_calls.append(True),
    )
    monkeypatch.setattr(
        launcher,
        "shutdown",
        lambda: (_ for _ in ()).throw(AssertionError("fallback should not shut down immediately")),
    )

    try:
        launcher.open_app_window()
    finally:
        desktop_launcher.remove_path_safely(launcher.browser_profile_path)

    assert opened_urls == [("http://127.0.0.1:8765/login", 2)]
    assert keep_running_calls == [True]


def test_admission_fees_are_saved_as_one_time_even_if_monthly_is_submitted(seeded_session, client):
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

    fees_page = client.get("/fees?create=1")
    fee_csrf_token = extract_csrf_token(fees_page.text)
    response = client.post(
        "/fees/create",
        data={
            "csrf_token": fee_csrf_token,
            "name": "Admission Fee Rule Test",
            "category": "Admission",
            "amount": "5000",
            "frequency": "Monthly",
            "status": "Active",
            "description": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/fees"

    fee = seeded_session.scalar(select(Fee).where(Fee.name == "Admission Fee Rule Test"))
    assert fee is not None
    assert fee.frequency == "One Time"
    assert fee.target_type == "General"
    assert fee.target_id is None

    seeded_session.delete(fee)
    seeded_session.commit()


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


def test_payments_can_be_cancelled_instead_of_deleted(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    ensure_operational_test_data(seeded_session)
    payment = seeded_session.scalar(select(Payment).where(Payment.reference == "TEST-BASE-PAYMENT"))
    assert payment is not None
    original_status = payment.status

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

    payments_page = client.get("/payments")
    payment_csrf_token = extract_csrf_token(payments_page.text)
    response = client.post(
        f"/payments/{payment.id}/cancel",
        data={"csrf_token": payment_csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/payments"

    seeded_session.refresh(payment)
    assert payment.status == "Cancelled"

    try:
        refreshed_payment = seeded_session.get(Payment, payment.id)
        assert refreshed_payment is not None
    finally:
        payment.status = original_status
        seeded_session.commit()


def test_cancelling_admission_payment_marks_student_inactive(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)
    course = seeded_session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    assert course is not None

    student = seeded_session.scalar(select(Student).where(Student.student_code == "ADM-CANCEL-001"))
    if student is None:
        student = Student(
            student_code="ADM-CANCEL-001",
            full_name="Admission Cancel Student",
            email="admission.cancel@example.com",
            phone="9999990041",
            parent_name="Cancel Parent",
            status="Active",
            address="Cancel Address",
            joined_on=date(2026, 4, 6),
            course_id=course.id,
        )
        seeded_session.add(student)
        seeded_session.flush()

    admission_fee = seeded_session.scalar(select(Fee).where(Fee.name == "Admission Cancel Fee"))
    if admission_fee is None:
        admission_fee = Fee(
            name="Admission Cancel Fee",
            category="Admission",
            amount=2500,
            frequency="One Time",
            status="Active",
            target_type="General",
            description="Admission fee used by cancellation tests.",
        )
        seeded_session.add(admission_fee)
        seeded_session.flush()

    payment = seeded_session.scalar(select(Payment).where(Payment.reference == "ADM-CANCEL-001"))
    if payment is None:
        payment = Payment(
            student_id=student.id,
            service_type="admission",
            service_id=admission_fee.id,
            service_name=admission_fee.name,
            amount=2500.0,
            payment_date=date(2026, 4, 6),
            method="Cash",
            reference="ADM-CANCEL-001",
            status="Paid",
        )
        seeded_session.add(payment)
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

    payments_page = client.get("/payments")
    payment_csrf_token = extract_csrf_token(payments_page.text)
    response = client.post(
        f"/payments/{payment.id}/cancel",
        data={"csrf_token": payment_csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/payments"

    seeded_session.refresh(payment)
    seeded_session.refresh(student)
    assert payment.status == "Cancelled"
    assert student.status == "Inactive"

    payment_to_cleanup = seeded_session.scalar(select(Payment).where(Payment.reference == "ADM-CANCEL-001"))
    if payment_to_cleanup is not None:
        seeded_session.delete(payment_to_cleanup)
    student_to_cleanup = seeded_session.scalar(select(Student).where(Student.student_code == "ADM-CANCEL-001"))
    if student_to_cleanup is not None:
        seeded_session.delete(student_to_cleanup)
    fee_to_cleanup = seeded_session.scalar(select(Fee).where(Fee.name == "Admission Cancel Fee"))
    if fee_to_cleanup is not None:
        seeded_session.delete(fee_to_cleanup)
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


def test_students_page_uses_guardian_contact_labels(seeded_session, client):
    ensure_operational_test_data(seeded_session)
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

    response = client.get("/students")
    assert response.status_code == 200
    assert "Guardian Email" in response.text
    assert "Guardian Phone" in response.text
    assert "Search by student ID, name, section, guardian email, or guardian phone" in response.text


def test_whatsapp_reminder_opens_external_target_and_returns_to_student_view(seeded_session, client, monkeypatch):
    ensure_operational_test_data(seeded_session)
    configure_setup_state(seeded_session, setup_completed=True)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert student is not None
    assert student.course is not None
    opened_urls = []
    monkeypatch.setattr(
        "school_admin.routes.students.webbrowser.open",
        lambda url, new=0: opened_urls.append((url, new)),
    )

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

    response = client.get(f"/students/{student.id}/notify/whatsapp", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/students?view={student.id}"
    assert len(opened_urls) == 1
    assert opened_urls[0][0].startswith("whatsapp://send?phone=")
    assert "".join(character for character in student.phone if character.isdigit()) in opened_urls[0][0]
    assert "Payment%20Reminder" in opened_urls[0][0] or "payment%20reminder" in opened_urls[0][0].lower()


def test_gmail_reminder_opens_external_browser_and_returns_to_student_view(seeded_session, client, monkeypatch):
    ensure_operational_test_data(seeded_session)
    configure_setup_state(seeded_session, setup_completed=True)
    student = seeded_session.scalar(select(Student).where(Student.student_code == "TEST-STU-001"))
    assert student is not None
    opened_urls = []
    monkeypatch.setattr(
        "school_admin.routes.students.webbrowser.open",
        lambda url, new=0: opened_urls.append((url, new)),
    )

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

    response = client.get(f"/students/{student.id}/notify/gmail", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/students?view={student.id}"
    assert len(opened_urls) == 1
    location = unquote(opened_urls[0][0])
    assert location.startswith("https://mail.google.com/mail/?view=cm&fs=1")
    assert f"to={student.email}" in location
    assert "Payment Reminder" in location


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
            recovery_user = session.scalar(select(User).where(User.role == "SuperAdmin").order_by(User.id))
            assert recovery_user is not None
            assert recovery_user.username == SUPERADMIN_USERNAME
            assert recovery_user.status == "Active"
            assert verify_password(SUPERADMIN_PASSWORD, recovery_user.password_hash)
    finally:
        test_engine.dispose()
        db_path.unlink(missing_ok=True)


def test_runtime_browser_profile_is_temporary_and_cleans_legacy_cache(monkeypatch):
    test_root = Path("data") / "launcher-cache-test"
    desktop_launcher.remove_path_safely(test_root)
    test_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(desktop_launcher, "APP_DATA_DIR", test_root)

    legacy_profile_dir = test_root / "browser-profile"
    legacy_profile_dir.mkdir(parents=True, exist_ok=True)
    (legacy_profile_dir / "cache.txt").write_text("legacy-cache", encoding="utf-8")

    try:
        runtime_profile_dir = desktop_launcher.create_runtime_browser_profile()

        assert runtime_profile_dir.exists()
        assert runtime_profile_dir.parent == (test_root / "runtime-browser-profiles").resolve()
        assert not legacy_profile_dir.exists()

        desktop_launcher.remove_path_safely(runtime_profile_dir)
        assert not runtime_profile_dir.exists()
    finally:
        desktop_launcher.remove_path_safely(test_root)


def test_superadmin_is_redirected_to_recovery_and_blocked_from_dashboard(seeded_session, client):
    configure_setup_state(seeded_session, setup_completed=True)

    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "identifier": SUPERADMIN_USERNAME,
            "password": SUPERADMIN_PASSWORD,
            "next_path": "/dashboard",
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/recovery/users"

    recovery_page = client.get("/recovery/users")
    assert recovery_page.status_code == 200
    assert "Recovery User Access" in recovery_page.text

    dashboard_response = client.get("/dashboard", follow_redirects=False)
    assert dashboard_response.status_code == 303
    assert dashboard_response.headers["location"] == "/recovery/users"


def test_superadmin_can_reset_admin_password(seeded_session, client):
    configure_setup_state(
        seeded_session,
        setup_completed=True,
        admin_username="admin",
        admin_password="adminadmin",
    )
    admin_user = seeded_session.scalar(select(User).where(User.role == "Admin").order_by(User.id))
    assert admin_user is not None

    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "identifier": SUPERADMIN_USERNAME,
            "password": SUPERADMIN_PASSWORD,
            "next_path": "/dashboard",
        },
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    recovery_page = client.get("/recovery/users")
    recovery_csrf_token = extract_csrf_token(recovery_page.text)
    reset_response = client.post(
        f"/recovery/users/{admin_user.id}/reset-password",
        data={
            "csrf_token": recovery_csrf_token,
            "new_password": "AdminReset@2026",
        },
        follow_redirects=False,
    )
    assert reset_response.status_code == 303
    assert reset_response.headers["location"] == "/recovery/users?success=1"

    seeded_session.refresh(admin_user)
    assert verify_password("AdminReset@2026", admin_user.password_hash)


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
