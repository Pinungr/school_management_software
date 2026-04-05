from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from school_admin.database import SessionLocal
from school_admin.models import Course, Hostel, Setting, Student, TransportRoute
from school_admin.utils import (
    active_lookups,
    calculate_student_fees_and_payments,
    form_with_csrf,
    optional_date,
    optional_int,
    redirect,
    render_page,
    require_user,
    student_payment_summary,
)


router = APIRouter()
STUDENT_STATUSES = {"Active", "Inactive"}
STUDENT_ERROR_MESSAGES = {
    "missing_fields": "Fill in the student code, full name, email, and phone before saving.",
    "invalid_status": "Choose a valid status for the student record.",
    "invalid_lookup": "Choose valid course, hostel, and transport values from the current lists.",
    "invalid_joined_on": "Enter a valid join date for the student.",
    "duplicate": "That student code is already in use.",
}


@router.get("/students", response_class=HTMLResponse)
async def students_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
    error: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        statement = (
            select(Student)
            .options(
                joinedload(Student.course),
                joinedload(Student.hostel),
                joinedload(Student.transport_route),
            )
            .order_by(Student.id.desc())
        )
        if search.strip():
            statement = statement.where(
                or_(
                    Student.student_code.contains(search.strip()),
                    Student.full_name.contains(search.strip()),
                    Student.email.contains(search.strip()),
                )
            )
        selected_student = session.get(Student, edit or view) if (edit or view) else None
        student_payment_summary_data = (
            student_payment_summary(session, selected_student.id) if selected_student else {}
        )
        selected_student_fees = {}
        if selected_student:
            selected_student_fees = calculate_student_fees_and_payments(session, selected_student)

        students_data = []
        for student in session.scalars(statement).all():
            fees_payments = calculate_student_fees_and_payments(session, student)
            students_data.append({"student": student, "fees_payments": fees_payments})

        return render_page(
            request,
            session,
            current_user,
            "students.html",
            "students",
            students_data=students_data,
            form_mode="create" if create else ("edit" if edit else None),
            form_student=selected_student if edit else None,
            view_student=selected_student if view else None,
            view_student_payments=student_payment_summary_data,
            view_student_fees=selected_student_fees,
            search=search,
            lookups=active_lookups(session),
            error_message=STUDENT_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/students/create")
async def create_student(request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/students")
        if response:
            return response
        student_code = str(form.get("student_code", "")).strip()
        full_name = str(form.get("full_name", "")).strip()
        email = str(form.get("email", "")).strip()
        phone = str(form.get("phone", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not student_code or not full_name or not email or not phone:
            return redirect("/students?create=1&error=missing_fields")
        if status not in STUDENT_STATUSES:
            return redirect("/students?create=1&error=invalid_status")
        try:
            joined_on = optional_date(str(form.get("joined_on", "")) or None)
        except ValueError:
            return redirect("/students?create=1&error=invalid_joined_on")
        course_id = optional_int(str(form.get("course_id", "")))
        hostel_id = optional_int(str(form.get("hostel_id", "")))
        transport_id = optional_int(str(form.get("transport_id", "")))
        if (
            (course_id is not None and session.get(Course, course_id) is None)
            or (hostel_id is not None and session.get(Hostel, hostel_id) is None)
            or (transport_id is not None and session.get(TransportRoute, transport_id) is None)
        ):
            return redirect("/students?create=1&error=invalid_lookup")
        student = Student(
            student_code=student_code,
            full_name=full_name,
            email=email,
            phone=phone,
            parent_name=str(form.get("parent_name", "")).strip(),
            status=status,
            address=str(form.get("address", "")).strip(),
            joined_on=joined_on,
            course_id=course_id,
            hostel_id=hostel_id,
            transport_id=transport_id,
        )
        session.add(student)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect("/students?create=1&error=duplicate")
    return redirect("/students")


@router.post("/students/{student_id}/edit")
async def edit_student(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/students")
        if response:
            return response
        student = session.get(Student, student_id)
        if not student:
            return redirect("/students")
        student_code = str(form.get("student_code", "")).strip()
        full_name = str(form.get("full_name", "")).strip()
        email = str(form.get("email", "")).strip()
        phone = str(form.get("phone", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not student_code or not full_name or not email or not phone:
            return redirect(f"/students?edit={student_id}&error=missing_fields")
        if status not in STUDENT_STATUSES:
            return redirect(f"/students?edit={student_id}&error=invalid_status")
        try:
            joined_on = optional_date(str(form.get("joined_on", "")) or None, student.joined_on)
        except ValueError:
            return redirect(f"/students?edit={student_id}&error=invalid_joined_on")
        course_id = optional_int(str(form.get("course_id", "")))
        hostel_id = optional_int(str(form.get("hostel_id", "")))
        transport_id = optional_int(str(form.get("transport_id", "")))
        if (
            (course_id is not None and session.get(Course, course_id) is None)
            or (hostel_id is not None and session.get(Hostel, hostel_id) is None)
            or (transport_id is not None and session.get(TransportRoute, transport_id) is None)
        ):
            return redirect(f"/students?edit={student_id}&error=invalid_lookup")
        student.student_code = student_code
        student.full_name = full_name
        student.email = email
        student.phone = phone
        student.parent_name = str(form.get("parent_name", "")).strip()
        student.status = status
        student.address = str(form.get("address", "")).strip()
        student.joined_on = joined_on
        student.course_id = course_id
        student.hostel_id = hostel_id
        student.transport_id = transport_id
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect(f"/students?edit={student_id}&error=duplicate")
    return redirect("/students")


@router.post("/students/{student_id}/delete")
async def delete_student(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/students")
        if response:
            return response
        student = session.get(Student, student_id)
        if student:
            session.delete(student)
            session.commit()
    return redirect("/students")


@router.post("/students/{student_id}/notify")
async def notify_guardian(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/students")
        if response:
            return response

        student = session.get(Student, student_id)
        if not student:
            return redirect("/students")

        fees_data = calculate_student_fees_and_payments(session, student)
        if fees_data["remaining_balance"] <= 0:
            return redirect("/students")

        settings = session.get(Setting, 1) or Setting()

        course_row = ""
        if fees_data["course_fee"] > 0:
            course_row = f"""
                        <tr>
                            <td>Course Fee ({student.course.name if student.course else 'N/A'})</td>
                            <td>{fees_data['course_fee']:.2f}</td>
                        </tr>"""

        hostel_row = ""
        if fees_data["hostel_fee"] > 0:
            hostel_row = f"""
                        <tr>
                            <td>Hostel Fee ({student.hostel.name if student.hostel else 'N/A'})</td>
                            <td>{fees_data['hostel_fee']:.2f}</td>
                        </tr>"""

        transport_row = ""
        if fees_data["transport_fee"] > 0:
            transport_row = f"""
                        <tr>
                            <td>Transport Fee ({student.transport_route.route_name if student.transport_route else 'N/A'})</td>
                            <td>{fees_data['transport_fee']:.2f}</td>
                        </tr>"""

        notification_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Payment Reminder - {settings.school_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .header {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }}
                .school-info {{ margin-bottom: 30px; }}
                .student-info {{ margin-bottom: 30px; }}
                .fee-breakdown {{ margin: 30px 0; }}
                .fee-table {{ width: 100%; border-collapse: collapse; }}
                .fee-table th, .fee-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                .fee-table th {{ background-color: #f2f2f2; }}
                .total-row {{ font-weight: bold; }}
                .balance {{ color: #d9534f; font-size: 18px; }}
                .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{settings.school_name}</h1>
                <p>{settings.address}</p>
                <p>Phone: {settings.phone_number} | Email: {settings.school_email}</p>
            </div>

            <div class="school-info">
                <p><strong>Date:</strong> {date.today().strftime('%B %d, %Y')}</p>
            </div>

            <div class="student-info">
                <h2>Payment Reminder Notice</h2>
                <p><strong>Student Name:</strong> {student.full_name}</p>
                <p><strong>Student Code:</strong> {student.student_code}</p>
                <p><strong>Parent/Guardian:</strong> {student.parent_name or 'N/A'}</p>
                <p><strong>Address:</strong> {student.address or 'N/A'}</p>
                <p><strong>Phone:</strong> {student.phone}</p>
                <p><strong>Email:</strong> {student.email}</p>
            </div>

            <div class="fee-breakdown">
                <h3>Fee Breakdown</h3>
                <table class="fee-table">
                    <thead>
                        <tr>
                            <th>Service</th>
                            <th>Amount ({settings.currency})</th>
                        </tr>
                    </thead>
                    <tbody>
                        {course_row}
                        {hostel_row}
                        {transport_row}
                        <tr class="total-row">
                            <td>Total Fees</td>
                            <td>{fees_data['total_fees']:.2f}</td>
                        </tr>
                        <tr>
                            <td>Amount Paid</td>
                            <td>{fees_data['paid_amount']:.2f}</td>
                        </tr>
                        <tr class="total-row">
                            <td>Outstanding Balance</td>
                            <td class="balance">{fees_data['remaining_balance']:.2f}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div>
                <p>Dear {student.parent_name or 'Parent/Guardian'},</p>

                <p>This is to inform you that there is an outstanding balance of <strong>{settings.currency} {fees_data['remaining_balance']:.2f}</strong>
                for your ward {student.full_name} (Student Code: {student.student_code}) for the academic year {settings.academic_year}.</p>

                <p>Please arrange to clear the outstanding amount at the earliest to avoid any disruption in services.
                Payment can be made through cash, bank transfer, or other accepted payment methods.</p>

                <p>For any queries or assistance, please contact the school administration at {settings.phone_number} or {settings.school_email}.</p>

                <p>Thank you for your attention to this matter.</p>

                <p>Best regards,<br>
                {settings.school_name}<br>
                {settings.address}<br>
                Phone: {settings.phone_number}<br>
                Email: {settings.school_email}</p>
            </div>

            <div class="footer">
                <p><em>This is an auto-generated notification from the School Management System.</em></p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=notification_html, status_code=200)
