import pytest
from sqlalchemy import select

from school_admin.database import Base, SessionLocal, engine
from school_admin.seed import seed_database
from school_admin.models import Student
from main import calculate_student_fees_and_payments


@pytest.fixture(scope="module")
def seeded_session():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_database(session)
        yield session


def test_calculate_student_fees_and_payments_for_seeded_student(seeded_session):
    student = seeded_session.scalar(select(Student).where(Student.student_code == "STU002"))
    assert student is not None

    fees = calculate_student_fees_and_payments(seeded_session, student)

    assert fees["total_fees"] == 10000.0
    assert fees["paid_amount"] == 1500.0
    assert fees["remaining_balance"] == 8500.0
    assert fees["pending_amount"] == 8500.0
