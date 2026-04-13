from __future__ import annotations

import csv
import io
import tempfile
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from school_admin.database import SessionLocal
from school_admin.models import Fee, Payment, Setting, Student
from school_admin.utils import (
    MONTH_OPTIONS,
    applicable_fees_for_student,
    calculate_student_fees_and_payments,
    form_with_csrf,
    optional_date,
    optional_float,
    optional_int,
    payment_service_maps,
    payment_service_name,
    payment_summary,
    redirect,
    render_page,
    require_permission,
    require_user,
    validate_service_for_type,
    years_for_filter,
)


router = APIRouter()
LIST_PAGE_SIZE = 10
EXPORT_BATCH_SIZE = 250
MANUAL_PAYMENT_TYPES = ("course", "hostel", "transport", "other")
PAYMENT_TYPES = set(MANUAL_PAYMENT_TYPES)
PAYMENT_STATUSES = {"Paid", "Pending", "Cancelled"}
PAYMENT_METHODS = {"Cash", "UPI", "Card", "Bank Transfer"}
PAYMENT_ERROR_MESSAGES = {
    "invalid_student": "Choose a valid student before saving a payment.",
    "invalid_type": "Choose a valid payment type.",
    "invalid_service": "Choose a valid fee item for the selected student and payment type.",
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


def resolve_service_name(session, service_type: str, service_id: int | None, student: Student | None = None) -> str:
    if service_id is None:
        return ""
    fee = session.get(Fee, service_id)
    if fee:
        return fee.name
    if service_type == "course" and student and student.course_id == service_id and student.course:
        return student.course.name
    if service_type == "hostel" and student and student.hostel_id == service_id and student.hostel:
        return student.hostel.name
    if service_type == "transport" and student and student.transport_id == service_id and student.transport_route:
        return student.transport_route.route_name
    return ""


def apply_student_snapshot(payment: Payment, student: Student | None) -> None:
    payment.student_code = str(student.student_code or "") if student else ""
    payment.student_name = str(student.full_name or "") if student else ""
    payment.parent_name = str(student.parent_name or "") if student else ""


def apply_receipt_snapshot(session, payment: Payment, student: Student | None) -> None:
    if student is not None:
        fees_data = calculate_student_fees_and_payments(session, student)
    else:
        fees_data = {
            "total_fees": 0.0,
            "paid_amount": float(payment.amount or 0),
            "current_cycle_amount": 0.0,
            "previous_pending_amount": 0.0,
            "remaining_balance": 0.0,
        }
    payment.snapshot_total_fees = float(fees_data["total_fees"] or 0)
    payment.snapshot_paid_amount = float(fees_data["paid_amount"] or 0)
    payment.snapshot_current_cycle_amount = float(fees_data["current_cycle_amount"] or 0)
    payment.snapshot_previous_pending_amount = float(fees_data["previous_pending_amount"] or 0)
    payment.snapshot_remaining_balance = float(fees_data["remaining_balance"] or 0)


def apply_payment_filters(
    statement,
    *,
    payment_type: str = "",
    month: str = "",
    year: str = "",
    student_id: str = "",
    student_query: str = "",
    payment_status: str = "",
):
    if payment_type:
        statement = statement.where(Payment.service_type == payment_type)
    if month and month.isdigit():
        statement = statement.where(func.strftime("%m", Payment.payment_date) == f"{int(month):02d}")
    if year and year.isdigit():
        statement = statement.where(func.strftime("%Y", Payment.payment_date) == year)
    if student_id and student_id.isdigit():
        statement = statement.where(Payment.student_id == int(student_id))
    if student_query.strip():
        query = student_query.strip()
        statement = statement.where(
            or_(
                Payment.student_code.contains(query),
                Payment.student_name.contains(query),
                Payment.student.has(
                    or_(
                        Student.student_code.contains(query),
                        Student.full_name.contains(query),
                    )
                ),
            )
        )
    if payment_status:
        statement = statement.where(Payment.status == payment_status)
    return statement


def payment_form_students(
    selected_payment: Payment | None,
    preselected_student: Student | None,
) -> list[Student]:
    students: list[Student] = []
    for candidate in (
        selected_payment.student if selected_payment else None,
        preselected_student,
    ):
        if candidate and not any(existing.id == candidate.id for existing in students):
            students.append(candidate)
    return students


def build_payment_export_file(
    *,
    payment_type: str = "",
    month: str = "",
    year: str = "",
    student_id: str = "",
    student_query: str = "",
    payment_status: str = "",
):
    export_file = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    text_buffer = io.TextIOWrapper(export_file, encoding="utf-8", newline="")
    with SessionLocal() as session:
        statement = (
            select(
                Payment,
                Student.student_code.label("active_student_code"),
                Student.full_name.label("active_student_name"),
            )
            .outerjoin(Student, Payment.student_id == Student.id)
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
        )
        statement = apply_payment_filters(
            statement,
            payment_type=payment_type,
            month=month,
            year=year,
            student_id=student_id,
            student_query=student_query,
            payment_status=payment_status,
        )
        service_maps = payment_service_maps(session)
        writer = csv.writer(text_buffer)
        writer.writerow(
            ["Type", "Fee Item", "Student ID", "Student Name", "Amount", "Date", "Method", "Status", "Reference"]
        )
        text_buffer.flush()

        offset = 0
        while True:
            rows = session.execute(statement.limit(EXPORT_BATCH_SIZE).offset(offset)).all()
            if not rows:
                break

            for payment, active_student_code, active_student_name in rows:
                service_name = payment_service_name(payment, service_maps)
                writer.writerow(
                    [
                        payment.service_type.title(),
                        service_name,
                        active_student_code or payment.student_code,
                        active_student_name or payment.student_name,
                        f"{payment.amount:.2f}",
                        payment.payment_date.isoformat(),
                        payment.method,
                        payment.status,
                        payment.reference,
                    ]
                )

            offset += len(rows)
            text_buffer.flush()

    text_buffer.detach()
    export_file.seek(0)
    return export_file


def file_chunks(file_obj, chunk_size: int = 8192):
    try:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        file_obj.close()


@router.get("/payments", response_class=HTMLResponse)
async def payments_page(
    request: Request,
    payment_type: str = "",
    month: str = "",
    year: str = "",
    student_id: str = "",
    student_query: str = "",
    payment_status: str = "",
    page: int = 1,
    create_student_id: str = "",
    create: int | None = None,
    edit: int | None = None,
    error: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_permission(session, request, "payment.view")
        if response:
            return response
        can_manage_payments = has_permission(current_user, "payment.manage")
        statement = (
            select(Payment)
            .options(joinedload(Payment.student))
            .order_by(Payment.payment_date.desc(), Payment.id.desc())
        )
        statement = apply_payment_filters(
            statement,
            payment_type=payment_type,
            month=month,
            year=year,
            student_id=student_id,
            student_query=student_query,
            payment_status=payment_status,
        )
        page = max(page, 1)
        total_payments = session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        total_pages = max((total_payments + LIST_PAGE_SIZE - 1) // LIST_PAGE_SIZE, 1)
        page = min(page, total_pages)
        selected_payment = session.get(Payment, edit) if edit else None
        if selected_payment and selected_payment.service_type == "admission":
            selected_payment = None
            edit = None
        preselected_student = (
            session.get(Student, int(create_student_id))
            if create and create_student_id.isdigit()
            else None
        )
        form_students = payment_form_students(selected_payment, preselected_student)
        form_student = selected_payment.student if selected_payment else preselected_student
        form_available_fees = applicable_fees_for_student(
            session,
            form_student,
            category=(selected_payment.service_type if selected_payment else payment_type),
        ) if form_student else []
        payments = session.scalars(
            statement.limit(LIST_PAGE_SIZE).offset((page - 1) * LIST_PAGE_SIZE)
        ).all()
        service_maps = payment_service_maps(session)
        export_query_string = urlencode(
            {
                key: value
                for key, value in {
                    "payment_type": payment_type,
                    "student_id": student_id,
                    "student_query": student_query,
                    "payment_status": payment_status,
                    "month": month,
                    "year": year,
                }.items()
                if str(value).strip()
            }
        )
        pagination_base = {
            key: value
            for key, value in {
                "payment_type": payment_type,
                "month": month,
                "year": year,
                "student_id": student_id,
                "student_query": student_query.strip(),
                "payment_status": payment_status,
            }.items()
            if str(value).strip()
        }
        page_start = ((page - 1) * LIST_PAGE_SIZE) + 1 if total_payments else 0
        page_end = min(page * LIST_PAGE_SIZE, total_payments)
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
            lookups={
                "fees": session.scalars(
                    select(Fee).where(Fee.status == "Active").order_by(Fee.name)
                ).all(),
            },
            manual_payment_types=MANUAL_PAYMENT_TYPES,
            form_students=form_students,
            form_mode="create" if create else ("edit" if edit else None),
            form_payment=selected_payment,
            form_student_id=(
                selected_payment.student_id
                if selected_payment
                else (preselected_student.id if preselected_student else None)
            ),
            form_service_id=selected_payment.service_id if selected_payment else None,
            form_available_fees=form_available_fees,
            filters={
                "payment_type": payment_type,
                "month": int(month) if month and month.isdigit() else None,
                "year": int(year) if year and year.isdigit() else None,
                "student_id": int(student_id) if student_id and student_id.isdigit() else None,
                "student_query": student_query.strip(),
                "payment_status": payment_status,
            },
            month_options=MONTH_OPTIONS,
            year_options=years_for_filter(),
            error_message=PAYMENT_ERROR_MESSAGES.get(error, ""),
            export_query_string=export_query_string,
            pagination={
                "page": page,
                "page_size": LIST_PAGE_SIZE,
                "total_items": total_payments,
                "total_pages": total_pages,
                "has_previous": page > 1,
                "has_next": page < total_pages,
                "previous_query": urlencode({**pagination_base, "page": page - 1}) if page > 1 else "",
                "next_query": urlencode({**pagination_base, "page": page + 1}) if page < total_pages else "",
                "page_start": page_start,
                "page_end": page_end,
            },
        )


@router.get("/payments/student-search")
async def payment_student_search(request: Request, q: str = ""):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return JSONResponse({"results": []}, status_code=401)
        query = q.strip()
        if not query:
            return JSONResponse({"results": []})
        students = session.scalars(
            select(Student)
            .where(
                Student.status == "Active",
                or_(
                    Student.student_code.contains(query),
                    Student.full_name.contains(query),
                ),
            )
            .order_by(Student.full_name, Student.student_code)
            .limit(25)
        ).all()
        return JSONResponse(
            {
                "results": [
                    {
                        "id": student.id,
                        "label": f"{student.student_code} - {student.full_name}",
                        "student_code": student.student_code,
                        "full_name": student.full_name,
                        "course_id": student.course_id,
                        "hostel_id": student.hostel_id,
                        "transport_id": student.transport_id,
                    }
                    for student in students
                ]
            }
        )


@router.post("/payments/create")
async def create_payment(request: Request):
    with SessionLocal() as session:
        current_user, response = require_permission(session, request, "payment.manage")
        if response:
            return response
        form, response = await form_with_csrf(request, "/payments")
        if response:
            return response
        service_type = str(form.get("service_type", "course")).strip().lower()
        if service_type not in PAYMENT_TYPES:
            return redirect("/payments?create=1&error=invalid_type")
        student_id = optional_int(str(form.get("student_id", "")))
        student = session.get(Student, student_id) if student_id is not None else None
        if student is None:
            return redirect("/payments?create=1&error=invalid_student")
        service_id = optional_int(str(form.get("service_id", "")))
        if not validate_service_for_type(session, service_type, service_id, student=student):
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

        payment = Payment(
            student_id=student_id,
            service_type=service_type,
            service_id=service_id,
            service_name=resolve_service_name(session, service_type, service_id, student),
            amount=amount,
            payment_date=payment_date,
            method=method,
            reference=str(form.get("reference", "")).strip(),
            notes=str(form.get("notes", "")).strip(),
            status=status,
        )
        apply_student_snapshot(payment, student)
        apply_receipt_snapshot(session, payment, student)
        session.add(payment)
        session.flush()
        payment_id = payment.id
        session.commit()
    return redirect(f"/payments/{payment_id}/bill")


@router.post("/payments/{payment_id}/edit")
async def edit_payment(payment_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_permission(session, request, "payment.manage")
        if response:
            return response
        form, response = await form_with_csrf(request, "/payments")
        if response:
            return response
        payment = session.get(Payment, payment_id)
        if not payment:
            return redirect("/payments")
        if payment.service_type == "admission":
            return redirect("/payments")
        service_type = str(form.get("service_type", "course")).strip().lower()
        if service_type not in PAYMENT_TYPES:
            return redirect(f"/payments?edit={payment_id}&error=invalid_type")
        student_id = optional_int(str(form.get("student_id", "")))
        student = session.get(Student, student_id) if student_id is not None else None
        if student is None:
            return redirect(f"/payments?edit={payment_id}&error=invalid_student")
        service_id = optional_int(str(form.get("service_id", "")))
        if not validate_service_for_type(session, service_type, service_id, student=student):
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
        apply_student_snapshot(payment, student)
        payment.service_type = service_type
        payment.service_id = service_id
        payment.service_name = resolve_service_name(session, service_type, service_id, student)
        payment.amount = amount
        payment.payment_date = payment_date
        payment.method = method
        payment.reference = str(form.get("reference", "")).strip()
        payment.notes = str(form.get("notes", "")).strip()
        payment.status = status
        apply_receipt_snapshot(session, payment, student)
        session.commit()
    return redirect("/payments")


def cancel_payment_record(payment: Payment) -> None:
    payment.status = "Cancelled"
    if payment.service_type == "admission" and payment.student is not None:
        payment.student.status = "Inactive"


@router.post("/payments/{payment_id}/cancel")
async def cancel_payment(payment_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_permission(session, request, "payment.manage")
        if response:
            return response
        _, response = await form_with_csrf(request, "/payments")
        if response:
            return response
        payment = session.scalar(
            select(Payment)
            .options(joinedload(Payment.student))
            .where(Payment.id == payment_id)
        )
        if payment:
            cancel_payment_record(payment)
            session.commit()
    return redirect("/payments")


@router.post("/payments/{payment_id}/delete")
async def delete_payment(payment_id: int, request: Request):
    return await cancel_payment(payment_id, request)


@router.get("/payments/{payment_id}/bill", response_class=HTMLResponse)
async def payment_bill(payment_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        payment = session.scalar(
            select(Payment)
            .where(Payment.id == payment_id)
        )
        if payment is None:
            return redirect("/payments")

        settings = session.get(Setting, 1) or Setting()
        
        # ALWAYS use snapshot data stored in the payment record to ensure historical correctness
        fees_data = {
            "total_fees": float(payment.snapshot_total_fees or 0),
            "paid_amount": float(payment.snapshot_paid_amount or 0),
            "current_cycle_amount": float(payment.snapshot_current_cycle_amount or 0),
            "previous_pending_amount": float(payment.snapshot_previous_pending_amount or 0),
            "remaining_balance": float(payment.snapshot_remaining_balance or 0),
        }

        payment_label = payment.service_name or payment.service_type.title()
        if payment.status == "Paid":
            bill_title = "Payment Receipt"
            status_color = "#1f8a4d"
        elif payment.status == "Cancelled":
            bill_title = "Cancelled Payment"
            status_color = "#b91c1c"
        else:
            bill_title = "Payment Bill"
            status_color = "#b7791f"

        bill_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{bill_title} - {escape_text(payment.reference or f"PAY-{payment.id}")}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2937; }}
                .toolbar {{ display: flex; gap: 12px; margin-bottom: 24px; }}
                .toolbar button, .toolbar a {{
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    padding: 10px 16px;
                    border-radius: 8px;
                    border: 1px solid #d1d5db;
                    background: #ffffff;
                    color: #111827;
                    text-decoration: none;
                    cursor: pointer;
                    font-size: 14px;
                }}
                .toolbar button.primary {{ background: #111827; border-color: #111827; color: #ffffff; }}
                .header {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #111827; padding-bottom: 16px; margin-bottom: 24px; }}
                .title {{ color: {status_color}; margin: 0; }}
                .meta, .student, .summary {{ margin-bottom: 24px; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ border: 1px solid #d1d5db; padding: 10px; text-align: left; }}
                th {{ background: #f3f4f6; }}
                .totals td {{ font-weight: bold; }}
                @media print {{
                    .toolbar {{ display: none; }}
                    body {{ margin: 20px; }}
                }}
            </style>
        </head>
        <body>
            <div class="toolbar">
                <button class="primary" type="button" onclick="printReceipt()">Print Receipt</button>
                <button type="button" onclick="closeReceipt()">Close Receipt</button>
                <a href="/payments">Back to Payments</a>
            </div>
            <div class="header">
                <div>
                    <h1 class="title">{bill_title}</h1>
                    <p><strong>{escape_text(settings.school_name or "School")}</strong></p>
                    <p>{escape_text(settings.address or "")}</p>
                    <p>{escape_text(settings.phone_number or "")} | {escape_text(settings.school_email or "")}</p>
                </div>
                <div>
                    <p><strong>Bill No:</strong> {escape_text(payment.reference or f"PAY-{payment.id}")}</p>
                    <p><strong>Date:</strong> {payment.payment_date.strftime("%d %b %Y")}</p>
                    <p><strong>Status:</strong> {escape_text(payment.status)}</p>
                </div>
            </div>

            <div class="student">
                <h3>Student Details</h3>
                <p><strong>Student:</strong> {escape_text(payment.student_name or "Deleted student")}</p>
                <p><strong>Student ID:</strong> {escape_text(payment.student_code or "Archived record")}</p>
                <p><strong>Guardian:</strong> {escape_text(payment.parent_name or "N/A")}</p>
            </div>

            <div class="summary">
                <h3>Payment Details</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Fee Item</th>
                            <th>Type</th>
                            <th>Method</th>
                            <th>Amount</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>{escape_text(payment_label)}</td>
                            <td>{escape_text(payment.service_type.title())}</td>
                            <td>{escape_text(payment.method)}</td>
                            <td>{format_amount(payment.amount, settings.currency)}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div class="summary">
                <h3>Student Balance Snapshot</h3>
                <table>
                    <tbody>
                        <tr><td>Total Fees Due</td><td>{format_amount(fees_data['total_fees'], settings.currency)}</td></tr>
                        <tr><td>Total Paid</td><td>{format_amount(fees_data['paid_amount'], settings.currency)}</td></tr>
                        <tr><td>This Month's Charges</td><td>{format_amount(fees_data['current_cycle_amount'], settings.currency)}</td></tr>
                        <tr><td>Earlier Pending Balance</td><td>{format_amount(fees_data['previous_pending_amount'], settings.currency)}</td></tr>
                        <tr class="totals"><td>Outstanding Balance</td><td>{format_amount(fees_data['remaining_balance'], settings.currency)}</td></tr>
                    </tbody>
                </table>
            </div>

            <p><strong>Notes:</strong> {escape_text(payment.notes or "-")}</p>
            <script>
                function printReceipt() {{
                    window.print();
                }}

                function closeReceipt() {{
                    window.close();
                    window.location.replace("/payments");
                }}

                window.addEventListener("afterprint", () => {{
                    if (window.opener) {{
                        window.close();
                    }}
                }});
            </script>
        </body>
        </html>
        """
        return HTMLResponse(content=bill_html, status_code=200)



@router.get("/payments/export")
async def export_payments(
    request: Request,
    payment_type: str = "",
    month: str = "",
    year: str = "",
    student_id: str = "",
    student_query: str = "",
    payment_status: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_permission(session, request, "payment.view")
        if response:
            return response
    export_file = build_payment_export_file(
        payment_type=payment_type,
        month=month,
        year=year,
        student_id=student_id,
        student_query=student_query,
        payment_status=payment_status,
    )
    return StreamingResponse(
        file_chunks(export_file),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )


def escape_text(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_amount(value: float, currency: str | None) -> str:
    prefix = (currency or "Rs").strip()
    return f"{prefix} {float(value or 0):,.2f}"
