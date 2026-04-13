from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class FeeType(str, Enum):
    ADMISSION = "ADMISSION"
    TUITION = "TUITION"
    TRANSPORT = "TRANSPORT"


class FeeFrequency(str, Enum):
    MONTHLY = "Monthly"
    YEARLY = "Yearly"


def fee_type_for_category(category: str | None) -> FeeType:
    normalized_category = str(category or "").strip().title()
    if normalized_category == "Admission":
        return FeeType.ADMISSION
    if normalized_category == "Transport":
        return FeeType.TRANSPORT
    return FeeType.TUITION


def normalize_fee_type(value: object | None, *, category: str | None = None) -> FeeType:
    if isinstance(value, FeeType):
        return value

    normalized_value = str(value or "").strip().upper()
    if normalized_value in {item.value for item in FeeType}:
        return FeeType(normalized_value)
    if normalized_value == "ADMISSION":
        return FeeType.ADMISSION
    if normalized_value == "TRANSPORT":
        return FeeType.TRANSPORT
    if normalized_value in {"TUITION", "COURSE", "HOSTEL", "OTHER", "GENERAL"}:
        return FeeType.TUITION
    if category is not None:
        return fee_type_for_category(category)
    return FeeType.TUITION


def normalize_fee_frequency(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, FeeFrequency):
        return value.value

    normalized_value = str(value).strip().lower()
    if not normalized_value or normalized_value in {"one time", "one-time", "onetime", "none"}:
        return None
    if normalized_value in {"yearly", "annual", "annually"}:
        return FeeFrequency.YEARLY.value
    return FeeFrequency.MONTHLY.value


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    school_name: Mapped[str] = mapped_column(String(120), default="Private School")
    school_email: Mapped[str] = mapped_column(String(120), default="info@school.com")
    phone_number: Mapped[str] = mapped_column(String(40), default="+91 9876543210")
    logo_url: Mapped[str] = mapped_column(String(255), default="/static/logo.svg")
    address: Mapped[str] = mapped_column(Text, default="123 Education Street, City, State")
    academic_year: Mapped[str] = mapped_column(String(40), default="2026-2027")
    financial_year: Mapped[str] = mapped_column(String(40), default="2026-2027")
    fee_frequency: Mapped[str] = mapped_column(String(30), default="Monthly")
    currency: Mapped[str] = mapped_column(String(30), default="INR (Rs)")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Kolkata (IST)")
    developer_name: Mapped[str] = mapped_column(String(120), default="")
    developer_email: Mapped[str] = mapped_column(String(120), default="")
    developer_phone: Mapped[str] = mapped_column(String(40), default="")
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    terms_accepted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(60), unique=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="Clerk")
    status: Mapped[str] = mapped_column(String(20), default="Active")
    created_on: Mapped[date] = mapped_column(Date, default=date.today)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(30), unique=True)
    fees: Mapped[float] = mapped_column(Float, default=0)
    frequency: Mapped[str] = mapped_column(String(30), default="Monthly")
    status: Mapped[str] = mapped_column(String(20), default="Active")
    description: Mapped[str] = mapped_column(Text, default="")

    students: Mapped[list["Student"]] = relationship(back_populates="course")
    sections: Mapped[list["Section"]] = relationship(back_populates="course")


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(30), default="")
    class_teacher: Mapped[str] = mapped_column(String(120), default="")
    room_name: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="Active")
    description: Mapped[str] = mapped_column(Text, default="")

    course: Mapped[Course] = relationship(back_populates="sections")
    students: Mapped[list["Student"]] = relationship(back_populates="section")


class Hostel(Base):
    __tablename__ = "hostels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    hostel_type: Mapped[str] = mapped_column(String(40), default="Boys")
    rooms: Mapped[int] = mapped_column(Integer, default=0)
    fee_amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="Active")
    description: Mapped[str] = mapped_column(Text, default="")

    students: Mapped[list["Student"]] = relationship(back_populates="hostel")


class TransportRoute(Base):
    __tablename__ = "transport_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_name: Mapped[str] = mapped_column(String(120))
    pickup_points: Mapped[str] = mapped_column(Text, default="")
    vehicle_no: Mapped[str] = mapped_column(String(40), default="")
    driver_name: Mapped[str] = mapped_column(String(120), default="")
    driver_phone: Mapped[str] = mapped_column(String(30), default="")
    fee_amount: Mapped[float] = mapped_column(Float, default=0)
    frequency: Mapped[str] = mapped_column(String(30), default="Monthly")
    status: Mapped[str] = mapped_column(String(20), default="Active")

    students: Mapped[list["Student"]] = relationship(back_populates="transport_route")


class Fee(Base):
    __tablename__ = "fees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30), default="Other")
    type: Mapped[str] = mapped_column(String(30), default=FeeType.TUITION.value)
    is_one_time: Mapped[bool] = mapped_column(Boolean, default=False)
    amount: Mapped[float] = mapped_column(Float, default=0)
    frequency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Active")
    target_type: Mapped[str] = mapped_column(String(30), default="General")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")


def apply_fee_business_rules(fee: Fee) -> None:
    normalized_type = normalize_fee_type(fee.type, category=fee.category)
    fee.type = normalized_type.value
    if normalized_type == FeeType.ADMISSION:
        fee.is_one_time = True
        fee.frequency = None
        return
    if normalized_type == FeeType.TUITION:
        fee.is_one_time = False
        fee.frequency = normalize_fee_frequency(fee.frequency) or FeeFrequency.MONTHLY.value
        return

    fee.is_one_time = False
    fee.frequency = normalize_fee_frequency(fee.frequency) or FeeFrequency.MONTHLY.value


@event.listens_for(Fee, "before_insert")
def _fee_before_insert(_mapper, _connection, target: Fee) -> None:
    apply_fee_business_rules(target)


@event.listens_for(Fee, "before_update")
def _fee_before_update(_mapper, _connection, target: Fee) -> None:
    apply_fee_business_rules(target)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        Index("ix_students_status_id", "status", "id"),
        Index("ix_students_status_full_name", "status", "full_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_code: Mapped[str] = mapped_column(String(30), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30))
    parent_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="Active")
    address: Mapped[str] = mapped_column(Text, default="")
    joined_on: Mapped[date] = mapped_column(Date, default=date.today)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.id"), nullable=True)
    hostel_id: Mapped[int | None] = mapped_column(ForeignKey("hostels.id"), nullable=True)
    transport_id: Mapped[int | None] = mapped_column(
        ForeignKey("transport_routes.id"), nullable=True
    )

    course: Mapped[Course | None] = relationship(back_populates="students")
    section: Mapped[Section | None] = relationship(back_populates="students")
    hostel: Mapped[Hostel | None] = relationship(back_populates="students")
    transport_route: Mapped[TransportRoute | None] = relationship(back_populates="students")
    payments: Mapped[list["Payment"]] = relationship(back_populates="student")
    payment_transactions: Mapped[list["PaymentTransaction"]] = relationship(back_populates="student")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_status_payment_date", "status", "payment_date", "id"),
        Index("ix_payments_student_payment_date", "student_id", "payment_date", "id"),
        Index("ix_payments_service_type_payment_date", "service_type", "payment_date", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"), nullable=True)
    student_code: Mapped[str] = mapped_column(String(30), default="")
    student_name: Mapped[str] = mapped_column(String(120), default="")
    parent_name: Mapped[str] = mapped_column(String(120), default="")
    snapshot_total_fees: Mapped[float] = mapped_column(Float, default=0)
    snapshot_paid_amount: Mapped[float] = mapped_column(Float, default=0)
    snapshot_current_cycle_amount: Mapped[float] = mapped_column(Float, default=0)
    snapshot_previous_pending_amount: Mapped[float] = mapped_column(Float, default=0)
    snapshot_remaining_balance: Mapped[float] = mapped_column(Float, default=0)
    service_type: Mapped[str] = mapped_column(String(30), default="course")
    service_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ID of the specific service
    service_name: Mapped[str] = mapped_column(String(120), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    payment_date: Mapped[date] = mapped_column(Date, default=date.today)
    method: Mapped[str] = mapped_column(String(30), default="Cash")
    reference: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="Paid")

    student: Mapped[Student | None] = relationship(back_populates="payments")


class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        Index("ix_payment_transactions_student_id", "student_id"),
        Index("ix_payment_transactions_fee_id", "fee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    fee_id: Mapped[int] = mapped_column(ForeignKey("fees.id"))

    amount_paid: Mapped[float] = mapped_column(Float, CheckConstraint("amount_paid > 0"))
    payment_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    payment_mode: Mapped[str] = mapped_column(String(20))  # CASH, UPI, BANK, CARD
    reference_id: Mapped[str | None] = mapped_column(String(60), nullable=True)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student: Mapped[Student] = relationship(back_populates="payment_transactions")
    fee: Mapped[Fee] = relationship()
    receipt: Mapped[Receipt | None] = relationship(back_populates="payment", uselist=False)


@event.listens_for(PaymentTransaction, "before_update")
def prevent_payment_update(mapper, connection, target):
    raise RuntimeError("Payment transactions are immutable and cannot be updated.")


@event.listens_for(PaymentTransaction, "before_delete")
def prevent_payment_delete(mapper, connection, target):
    raise RuntimeError("Payment transactions are immutable and cannot be deleted.")


class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment_transactions.id"), unique=True)

    amount_paid: Mapped[float] = mapped_column(Float)
    payment_date: Mapped[datetime] = mapped_column(DateTime)

    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    student: Mapped[Student] = relationship()
    payment: Mapped[PaymentTransaction] = relationship(back_populates="receipt")


@event.listens_for(Receipt, "before_update")
def prevent_receipt_update(mapper, connection, target):
    raise RuntimeError("Receipts are immutable and cannot be updated.")


@event.listens_for(Receipt, "before_delete")
def prevent_receipt_delete(mapper, connection, target):
    raise RuntimeError("Receipts are immutable and cannot be deleted.")
