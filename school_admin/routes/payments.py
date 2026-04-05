from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from school_admin.database import SessionLocal
from school_admin.models import Course, Hostel, Payment, Student, TransportRoute
from school_admin.utils import (
    MONTH_OPTIONS,
    active_lookups,
    form_with_csrf,
    optional_date,
    optional_float,
    optional_int,
    payment_service_maps,
    payment_service_name,
    payment_summary,
    redirect,
    render_page,
    require_user,
    validate_service_for_type,
    years_for_filter,
)


router = APIRouter()
PAYMENT_TYPES = {"course", "hostel", "transport"}
PAYMENT_STATUSES = {"Paid", "Pending"}
PAYMENT_METHODS = {"Cash", "UPI", "Card", "Bank Transfer"}
PAYMENT_ERROR_MESSAGES = {
    "invalid_student": "Choose a valid student before saving a payment.",
    "invalid_type": "Choose a valid payment type.",
    "invalid_service": "Choose a valid service for the selected payment type.",
    "invalid_amount": "Enter a valid payment amount greater than zero.",
    "invalid_status": "Choose a valid payment status.",
    "invalid_method": "Choose a valid payment method.",
    "invalid_date": "Enter a valid payment date.",
}


def positive_float(value: str) -> float | None:
    try:
        amount = optional_float(value)
    except ValueError:
        return None
    return amount if amount > 0 else None


def resolve_service_name(session, service_type: str, service_id: int | None) -> str:
    if service_id is None:
        return ""
    if service_type == "course":
        course = session.get(Course, service_id)
        return course.name if course else ""
    if service_type == "hostel":
        hostel = session.get(Hostel, service_id)
        return hostel.name if hostel else ""
    if service_type == "transport":
        route = session.get(TransportRoute, service_id)
        return route.route_name if route else ""
    return ""


@router.get("/payments", response_class=HTMLResponse)
async def payments_page(
    request: Request,
    payment_type: str = "",
    month: str = "",
    year: str = "",
    student_id: str = "",
    payment_status: str = "",
    create: int | None = None,
    edit: int | None = None,
    error: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        statement = (
            select(Payment)
            .options(joinedload(Payment.student))
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
        )
        if payment_type:
            statement = statement.where(Payment.service_type == payment_type)
        if month and month.isdigit():
            statement = statement.where(func.strftime("%m", Payment.payment_date) == f"{int(month):02d}")
        if year and year.isdigit():
            statement = statement.where(func.strftime("%Y", Payment.payment_date) == year)
        if student_id and student_id.isdigit():
            statement = statement.where(Payment.student_id == int(student_id))
        if payment_status:
            statement = statement.where(Payment.status == payment_status)
        selected_payment = session.get(Payment, edit) if edit else None
        payments = session.scalars(statement).all()
        service_maps = payment_service_maps(session)
        return render_page(
            request,
            session,
            current_user,
            "payments.html",
            "payments",
            payments=payments,
            payment_service_names={
                payment.id: payment_service_name(payment, service_maps) for payment in payments
            },
            summary=payment_summary(session),
            lookups=active_lookups(session),
            form_mode="create" if create else ("edit" if edit else None),
            form_payment=selected_payment,
            filters={
                "payment_type": payment_type,
                "month": int(month) if month and month.isdigit() else None,
                "year": int(year) if year and year.isdigit() else None,
                "student_id": int(student_id) if student_id and student_id.isdigit() else None,
                "payment_status": payment_status,
            },
            month_options=MONTH_OPTIONS,
            year_options=years_for_filter(),
            error_message=PAYMENT_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/payments/create")
async def create_payment(request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/payments")
        if response:
            return response
        service_type = str(form.get("service_type", "course")).strip()
        if service_type not in PAYMENT_TYPES:
            return redirect("/payments?create=1&error=invalid_type")
        student_id = optional_int(str(form.get("student_id", "")))
        if student_id is None or session.get(Student, student_id) is None:
            return redirect("/payments?create=1&error=invalid_student")
        service_id = optional_int(str(form.get("service_id", "")))
        if not validate_service_for_type(session, service_type, service_id):
            return redirect("/payments?create=1&error=invalid_service")
        amount = positive_float(str(form.get("amount", "")))
        if amount is None:
            return redirect("/payments?create=1&error=invalid_amount")
        try:
            payment_date = optional_date(str(form.get("payment_date", "")) or None)
        except ValueError:
            return redirect("/payments?create=1&error=invalid_date")
        method = str(form.get("method", "Cash")).strip()
        status = str(form.get("status", "Paid")).strip()
        if method not in PAYMENT_METHODS:
            return redirect("/payments?create=1&error=invalid_method")
        if status not in PAYMENT_STATUSES:
            return redirect("/payments?create=1&error=invalid_status")

        session.add(
            Payment(
                student_id=student_id,
                service_type=service_type,
                service_id=service_id,
                service_name=resolve_service_name(session, service_type, service_id),
                amount=amount,
                payment_date=payment_date,
                method=method,
                reference=str(form.get("reference", "")).strip(),
                notes=str(form.get("notes", "")).strip(),
                status=status,
            )
        )
        session.commit()
    return redirect("/payments")


@router.post("/payments/{payment_id}/edit")
async def edit_payment(payment_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/payments")
        if response:
            return response
        payment = session.get(Payment, payment_id)
        if not payment:
            return redirect("/payments")
        service_type = str(form.get("service_type", "course")).strip()
        if service_type not in PAYMENT_TYPES:
            return redirect(f"/payments?edit={payment_id}&error=invalid_type")
        student_id = optional_int(str(form.get("student_id", "")))
        if student_id is None or session.get(Student, student_id) is None:
            return redirect(f"/payments?edit={payment_id}&error=invalid_student")
        service_id = optional_int(str(form.get("service_id", "")))
        if not validate_service_for_type(session, service_type, service_id):
            return redirect(f"/payments?edit={payment_id}&error=invalid_service")
        amount = positive_float(str(form.get("amount", "")))
        if amount is None:
            return redirect(f"/payments?edit={payment_id}&error=invalid_amount")
        try:
            payment_date = optional_date(str(form.get("payment_date", "")) or None, payment.payment_date)
        except ValueError:
            return redirect(f"/payments?edit={payment_id}&error=invalid_date")
        method = str(form.get("method", "Cash")).strip()
        status = str(form.get("status", "Paid")).strip()
        if method not in PAYMENT_METHODS:
            return redirect(f"/payments?edit={payment_id}&error=invalid_method")
        if status not in PAYMENT_STATUSES:
            return redirect(f"/payments?edit={payment_id}&error=invalid_status")

        payment.student_id = student_id
        payment.service_type = service_type
        payment.service_id = service_id
        payment.service_name = resolve_service_name(session, service_type, service_id)
        payment.amount = amount
        payment.payment_date = payment_date
        payment.method = method
        payment.reference = str(form.get("reference", "")).strip()
        payment.notes = str(form.get("notes", "")).strip()
        payment.status = status
        session.commit()
    return redirect("/payments")


@router.post("/payments/{payment_id}/delete")
async def delete_payment(payment_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/payments")
        if response:
            return response
        payment = session.get(Payment, payment_id)
        if payment:
            session.delete(payment)
            session.commit()
    return redirect("/payments")


@router.get("/payments/export")
async def export_payments(
    request: Request,
    payment_type: str = "",
    month: str = "",
    year: str = "",
    student_id: str = "",
    payment_status: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        statement = (
            select(Payment)
            .options(joinedload(Payment.student))
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
        )
        if payment_type:
            statement = statement.where(Payment.service_type == payment_type)
        if month and month.isdigit():
            statement = statement.where(func.strftime("%m", Payment.payment_date) == f"{int(month):02d}")
        if year and year.isdigit():
            statement = statement.where(func.strftime("%Y", Payment.payment_date) == year)
        if student_id and student_id.isdigit():
            statement = statement.where(Payment.student_id == int(student_id))
        if payment_status:
            statement = statement.where(Payment.status == payment_status)
        payments = session.scalars(statement).all()
        service_maps = payment_service_maps(session)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Type", "Service", "Student ID", "Student Name", "Amount", "Date", "Method", "Status", "Reference"])
    for payment in payments:
        service_name = payment_service_name(payment, service_maps)
        writer.writerow(
            [
                payment.service_type.title(),
                service_name,
                payment.student.student_code,
                payment.student.full_name,
                f"{payment.amount:.2f}",
                payment.payment_date.isoformat(),
                payment.method,
                payment.status,
                payment.reference,
            ]
        )
    return StreamingResponse(
        io.BytesIO(buffer.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )
