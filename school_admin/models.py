from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


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
    fee_amount: Mapped[float] = mapped_column(Float, default=0)
    frequency: Mapped[str] = mapped_column(String(30), default="Monthly")
    status: Mapped[str] = mapped_column(String(20), default="Active")

    students: Mapped[list["Student"]] = relationship(back_populates="transport_route")


class Student(Base):
    __tablename__ = "students"

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
    hostel_id: Mapped[int | None] = mapped_column(ForeignKey("hostels.id"), nullable=True)
    transport_id: Mapped[int | None] = mapped_column(
        ForeignKey("transport_routes.id"), nullable=True
    )

    course: Mapped[Course | None] = relationship(back_populates="students")
    hostel: Mapped[Hostel | None] = relationship(back_populates="students")
    transport_route: Mapped[TransportRoute | None] = relationship(back_populates="students")
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    service_type: Mapped[str] = mapped_column(String(30), default="course")
    amount: Mapped[float] = mapped_column(Float, default=0)
    payment_date: Mapped[date] = mapped_column(Date, default=date.today)
    method: Mapped[str] = mapped_column(String(30), default="Cash")
    reference: Mapped[str] = mapped_column(String(60), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="Paid")

    student: Mapped[Student] = relationship(back_populates="payments")
