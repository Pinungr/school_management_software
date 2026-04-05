from __future__ import annotations

import csv
import io
from datetime import date, datetime
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from school_admin.auth import hash_password, verify_password
from school_admin.database import Base, SessionLocal, STATIC_DIR, engine
from school_admin.models import Course, Hostel, Payment, Setting, Student, TransportRoute, User
from school_admin.utils import (
    active_lookups,
    calculate_student_fees_and_payments,
    dashboard_metrics,
    get_settings,
    login_redirect,
    MONTH_OPTIONS,
    nav_items_for,
    optional_date,
    optional_float,
    optional_int,
    payment_summary,
    redirect,
    render_page,
    render_public,
    require_admin,
    require_user,
    safe_next_path,
    student_payment_summary,
    years_for_filter,
    lifespan,
)


app = FastAPI(title="School Management System", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key="schoolflow-local-session-secret",
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> RedirectResponse:
    with SessionLocal() as session:
        current_user = get_current_user(session, request)
        return redirect("/dashboard" if current_user else "/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: int | None = None, next: str | None = None):
    with SessionLocal() as session:
        current_user = get_current_user(session, request)
        if current_user:
            return redirect("/dashboard")
        return render_public(
            request,
            "login.html",
            settings=get_settings(session),
            error=bool(error),
            next_path=safe_next_path(next, "/dashboard"),
        )


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    next_path = safe_next_path(str(form.get("next_path", "/dashboard")))
    identifier = str(form.get("identifier", "")).strip().lower()
    password = str(form.get("password", ""))
    with SessionLocal() as session:
        user = session.scalar(
            select(User).where(
                or_(
                    User.username == identifier,
                    User.email == identifier,
                )
            )
        )
        if not user or user.status != "Active" or not verify_password(password, user.password_hash):
            return redirect(f"/login?error=1&next={quote(next_path)}")
        request.session.clear()
        request.session["user_id"] = user.id
    return redirect(next_path)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        return render_page(
            request,
            session,
            current_user,
            "dashboard.html",
            "dashboard",
            metrics=dashboard_metrics(session),
        )


@app.get("/students", response_class=HTMLResponse)
async def students_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
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
        
        # Get all students and calculate their fees/payments
        students_data = []
        for student in session.scalars(statement).all():
            fees_payments = calculate_student_fees_and_payments(session, student)
            students_data.append({
                "student": student,
                "fees_payments": fees_payments
            })
        
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
        )


@app.post("/students/create")
async def create_student(request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        student = Student(
            student_code=str(form.get("student_code", "")).strip(),
            full_name=str(form.get("full_name", "")).strip(),
            email=str(form.get("email", "")).strip(),
            phone=str(form.get("phone", "")).strip(),
            parent_name=str(form.get("parent_name", "")).strip(),
            status=str(form.get("status", "Active")).strip(),
            address=str(form.get("address", "")).strip(),
            joined_on=optional_date(str(form.get("joined_on", "")) or None),
            course_id=optional_int(str(form.get("course_id", ""))),
            hostel_id=optional_int(str(form.get("hostel_id", ""))),
            transport_id=optional_int(str(form.get("transport_id", ""))),
        )
        session.add(student)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect("/students?create=1")
    return redirect("/students")


@app.post("/students/{student_id}/edit")
async def edit_student(student_id: int, request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        student = session.get(Student, student_id)
        if not student:
            return redirect("/students")
        student.student_code = str(form.get("student_code", "")).strip()
        student.full_name = str(form.get("full_name", "")).strip()
        student.email = str(form.get("email", "")).strip()
        student.phone = str(form.get("phone", "")).strip()
        student.parent_name = str(form.get("parent_name", "")).strip()
        student.status = str(form.get("status", "Active")).strip()
        student.address = str(form.get("address", "")).strip()
        student.joined_on = optional_date(str(form.get("joined_on", "")) or None, student.joined_on)
        student.course_id = optional_int(str(form.get("course_id", "")))
        student.hostel_id = optional_int(str(form.get("hostel_id", "")))
        student.transport_id = optional_int(str(form.get("transport_id", "")))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect(f"/students?edit={student_id}")
    return redirect("/students")


@app.post("/students/{student_id}/delete")
async def delete_student(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        student = session.get(Student, student_id)
        if student:
            session.delete(student)
            session.commit()
    return redirect("/students")


@app.post("/students/{student_id}/notify")
async def notify_guardian(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        
        student = session.get(Student, student_id)
        if not student:
            return redirect("/students")
        
        # Calculate fees and payments
        fees_data = calculate_student_fees_and_payments(session, student)
        
        if fees_data["remaining_balance"] <= 0:
            return redirect("/students")
        
        # Get school settings
        settings = session.get(Setting, 1) or Setting()
        
        # Generate notification HTML
        course_row = ""
        if fees_data['course_fee'] > 0:
            course_row = f"""
                        <tr>
                            <td>Course Fee ({student.course.name if student.course else 'N/A'})</td>
                            <td>{fees_data['course_fee']:.2f}</td>
                        </tr>"""
        
        hostel_row = ""
        if fees_data['hostel_fee'] > 0:
            hostel_row = f"""
                        <tr>
                            <td>Hostel Fee ({student.hostel.name if student.hostel else 'N/A'})</td>
                            <td>{fees_data['hostel_fee']:.2f}</td>
                        </tr>"""
        
        transport_row = ""
        if fees_data['transport_fee'] > 0:
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
        
        # For now, return the HTML as a response that can be printed
        # In a real implementation, this could be sent as email or saved as PDF
        return HTMLResponse(content=notification_html, status_code=200)


@app.get("/courses", response_class=HTMLResponse)
async def courses_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        statement = select(Course).order_by(Course.id.desc())
        if search.strip():
            statement = statement.where(
                or_(Course.name.contains(search.strip()), Course.code.contains(search.strip()))
            )
        selected_course = session.get(Course, edit or view) if (edit or view) else None
        return render_page(
            request,
            session,
            current_user,
            "courses.html",
            "courses",
            courses=session.scalars(statement).all(),
            form_mode="create" if create else ("edit" if edit else None),
            form_course=selected_course if edit else None,
            view_course=selected_course if view else None,
            search=search,
        )


@app.post("/courses/create")
async def create_course(request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        session.add(
            Course(
                name=str(form.get("name", "")).strip(),
                code=str(form.get("code", "")).strip(),
                fees=optional_float(str(form.get("fees", ""))),
                frequency=str(form.get("frequency", "Monthly")).strip(),
                status=str(form.get("status", "Active")).strip(),
                description=str(form.get("description", "")).strip(),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect("/courses?create=1")
    return redirect("/courses")


@app.post("/courses/{course_id}/edit")
async def edit_course(course_id: int, request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        course = session.get(Course, course_id)
        if not course:
            return redirect("/courses")
        course.name = str(form.get("name", "")).strip()
        course.code = str(form.get("code", "")).strip()
        course.fees = optional_float(str(form.get("fees", "")))
        course.frequency = str(form.get("frequency", "Monthly")).strip()
        course.status = str(form.get("status", "Active")).strip()
        course.description = str(form.get("description", "")).strip()
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect(f"/courses?edit={course_id}")
    return redirect("/courses")


@app.post("/courses/{course_id}/delete")
async def delete_course(course_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        course = session.get(Course, course_id)
        if course:
            for student in session.scalars(select(Student).where(Student.course_id == course_id)).all():
                student.course_id = None
            session.delete(course)
            session.commit()
    return redirect("/courses")


@app.get("/hostels", response_class=HTMLResponse)
async def hostels_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        statement = select(Hostel).order_by(Hostel.id.desc())
        if search.strip():
            statement = statement.where(
                or_(Hostel.name.contains(search.strip()), Hostel.hostel_type.contains(search.strip()))
            )
        selected_hostel = session.get(Hostel, edit or view) if (edit or view) else None
        return render_page(
            request,
            session,
            current_user,
            "hostels.html",
            "hostels",
            hostels=session.scalars(statement).all(),
            form_mode="create" if create else ("edit" if edit else None),
            form_hostel=selected_hostel if edit else None,
            view_hostel=selected_hostel if view else None,
            search=search,
        )


@app.post("/hostels/create")
async def create_hostel(request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        session.add(
            Hostel(
                name=str(form.get("name", "")).strip(),
                hostel_type=str(form.get("hostel_type", "Boys")).strip(),
                rooms=optional_int(str(form.get("rooms", ""))) or 0,
                fee_amount=optional_float(str(form.get("fee_amount", ""))),
                status=str(form.get("status", "Active")).strip(),
                description=str(form.get("description", "")).strip(),
            )
        )
        session.commit()
    return redirect("/hostels")


@app.post("/hostels/{hostel_id}/edit")
async def edit_hostel(hostel_id: int, request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        hostel = session.get(Hostel, hostel_id)
        if not hostel:
            return redirect("/hostels")
        hostel.name = str(form.get("name", "")).strip()
        hostel.hostel_type = str(form.get("hostel_type", "Boys")).strip()
        hostel.rooms = optional_int(str(form.get("rooms", ""))) or 0
        hostel.fee_amount = optional_float(str(form.get("fee_amount", "")))
        hostel.status = str(form.get("status", "Active")).strip()
        hostel.description = str(form.get("description", "")).strip()
        session.commit()
    return redirect("/hostels")


@app.post("/hostels/{hostel_id}/delete")
async def delete_hostel(hostel_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        hostel = session.get(Hostel, hostel_id)
        if hostel:
            for student in session.scalars(select(Student).where(Student.hostel_id == hostel_id)).all():
                student.hostel_id = None
            session.delete(hostel)
            session.commit()
    return redirect("/hostels")


@app.get("/transport", response_class=HTMLResponse)
async def transport_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        statement = select(TransportRoute).order_by(TransportRoute.id.desc())
        if search.strip():
            statement = statement.where(
                or_(
                    TransportRoute.route_name.contains(search.strip()),
                    TransportRoute.pickup_points.contains(search.strip()),
                )
            )
        selected_route = session.get(TransportRoute, edit or view) if (edit or view) else None
        return render_page(
            request,
            session,
            current_user,
            "transport.html",
            "transport",
            routes=session.scalars(statement).all(),
            form_mode="create" if create else ("edit" if edit else None),
            form_route=selected_route if edit else None,
            view_route=selected_route if view else None,
            search=search,
        )


@app.post("/transport/create")
async def create_route(request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        session.add(
            TransportRoute(
                route_name=str(form.get("route_name", "")).strip(),
                pickup_points=str(form.get("pickup_points", "")).strip(),
                fee_amount=optional_float(str(form.get("fee_amount", ""))),
                frequency=str(form.get("frequency", "Monthly")).strip(),
                status=str(form.get("status", "Active")).strip(),
            )
        )
        session.commit()
    return redirect("/transport")


@app.post("/transport/{route_id}/edit")
async def edit_route(route_id: int, request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        route = session.get(TransportRoute, route_id)
        if not route:
            return redirect("/transport")
        route.route_name = str(form.get("route_name", "")).strip()
        route.pickup_points = str(form.get("pickup_points", "")).strip()
        route.fee_amount = optional_float(str(form.get("fee_amount", "")))
        route.frequency = str(form.get("frequency", "Monthly")).strip()
        route.status = str(form.get("status", "Active")).strip()
        session.commit()
    return redirect("/transport")


@app.post("/transport/{route_id}/delete")
async def delete_route(route_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        route = session.get(TransportRoute, route_id)
        if route:
            for student in session.scalars(select(Student).where(Student.transport_id == route_id)).all():
                student.transport_id = None
            session.delete(route)
            session.commit()
    return redirect("/transport")


@app.get("/payments", response_class=HTMLResponse)
async def payments_page(
    request: Request,
    payment_type: str = "",
    month: str = "",
    year: str = "",
    student_id: str = "",
    payment_status: str = "",
    create: int | None = None,
    edit: int | None = None,
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        statement = select(Payment).options(joinedload(Payment.student)).order_by(
            Payment.payment_date.desc(), Payment.id.desc()
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
        return render_page(
            request,
            session,
            current_user,
            "payments.html",
            "payments",
            payments=session.scalars(statement).all(),
            summary=payment_summary(session),
            lookups=active_lookups(session),
            form_mode="create" if create else ("edit" if edit else None),
            form_payment=selected_payment,
            filters={"payment_type": payment_type, "month": int(month) if month and month.isdigit() else None, "year": int(year) if year and year.isdigit() else None, "student_id": int(student_id) if student_id and student_id.isdigit() else None, "payment_status": payment_status},
            month_options=MONTH_OPTIONS,
            year_options=years_for_filter(),
        )


@app.post("/payments/create")
async def create_payment(request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        service_type = str(form.get("service_type", "course")).strip()
        service_id = optional_int(str(form.get("service_id", "")))
        
        # Validate that the service_id is valid for the service_type and student
        if service_id:
            student_id = int(str(form.get("student_id", "0")))
            student = session.get(Student, student_id)
            if service_type == "course" and student and student.course_id != service_id:
                # Allow payment for any course, not just enrolled one
                pass
            elif service_type == "hostel" and student and student.hostel_id != service_id:
                # Allow payment for any hostel, not just assigned one
                pass
            elif service_type == "transport" and student and student.transport_id != service_id:
                # Allow payment for any transport route, not just assigned one
                pass
        
        session.add(
            Payment(
                student_id=int(str(form.get("student_id", "0"))),
                service_type=service_type,
                service_id=service_id,
                amount=optional_float(str(form.get("amount", ""))),
                payment_date=optional_date(str(form.get("payment_date", "")) or None),
                method=str(form.get("method", "Cash")).strip(),
                reference=str(form.get("reference", "")).strip(),
                notes=str(form.get("notes", "")).strip(),
                status=str(form.get("status", "Paid")).strip(),
            )
        )
        session.commit()
    return redirect("/payments")


@app.post("/payments/{payment_id}/edit")
async def edit_payment(payment_id: int, request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        payment = session.get(Payment, payment_id)
        if not payment:
            return redirect("/payments")
        service_type = str(form.get("service_type", "course")).strip()
        service_id = optional_int(str(form.get("service_id", "")))
        
        payment.student_id = int(str(form.get("student_id", "0")))
        payment.service_type = service_type
        payment.service_id = service_id
        payment.amount = optional_float(str(form.get("amount", "")))
        payment.payment_date = optional_date(str(form.get("payment_date", "")) or None, payment.payment_date)
        payment.method = str(form.get("method", "Cash")).strip()
        payment.reference = str(form.get("reference", "")).strip()
        payment.notes = str(form.get("notes", "")).strip()
        payment.status = str(form.get("status", "Paid")).strip()
        session.commit()
    return redirect("/payments")


@app.post("/payments/{payment_id}/delete")
async def delete_payment(payment_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        payment = session.get(Payment, payment_id)
        if payment:
            session.delete(payment)
            session.commit()
    return redirect("/payments")


@app.get("/payments/export")
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
        statement = select(Payment).options(joinedload(Payment.student)).order_by(
            Payment.payment_date.desc(), Payment.id.desc()
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

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Type", "Service", "Student ID", "Student Name", "Amount", "Date", "Method", "Status", "Reference"])
    for payment in payments:
        # Get service name
        service_name = ""
        if payment.service_id:
            if payment.service_type == "course":
                course = session.get(Course, payment.service_id)
                service_name = course.name if course else "Unknown Course"
            elif payment.service_type == "hostel":
                hostel = session.get(Hostel, payment.service_id)
                service_name = hostel.name if hostel else "Unknown Hostel"
            elif payment.service_type == "transport":
                route = session.get(TransportRoute, payment.service_id)
                service_name = route.route_name if route else "Unknown Route"
        
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


@app.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        statement = select(User).order_by(User.id.desc())
        if search.strip():
            statement = statement.where(
                or_(
                    User.full_name.contains(search.strip()),
                    User.username.contains(search.strip()),
                    User.email.contains(search.strip()),
                    User.role.contains(search.strip()),
                )
            )
        selected_user = session.get(User, edit) if edit else None
        return render_page(
            request,
            session,
            current_user,
            "users.html",
            "users",
            users=session.scalars(statement).all(),
            form_mode="create" if create else ("edit" if edit else None),
            form_user=selected_user,
            search=search,
        )


@app.post("/users/create")
async def create_user(request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        password = str(form.get("password", ""))
        if len(password) < 6:
            return redirect("/users?create=1")
        session.add(
            User(
                full_name=str(form.get("full_name", "")).strip(),
                username=str(form.get("username", "")).strip().lower(),
                email=str(form.get("email", "")).strip().lower(),
                password_hash=hash_password(password),
                role=str(form.get("role", "Clerk")).strip(),
                status=str(form.get("status", "Active")).strip(),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect("/users?create=1")
    return redirect("/users")


@app.post("/users/{user_id}/edit")
async def edit_user(user_id: int, request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        user = session.get(User, user_id)
        if not user:
            return redirect("/users")
        user.full_name = str(form.get("full_name", "")).strip()
        user.username = str(form.get("username", "")).strip().lower()
        user.email = str(form.get("email", "")).strip().lower()
        user.role = str(form.get("role", "Clerk")).strip()
        user.status = str(form.get("status", "Active")).strip()
        password = str(form.get("password", "")).strip()
        if password:
            user.password_hash = hash_password(password)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect(f"/users?edit={user_id}")
    return redirect("/users")


@app.post("/users/{user_id}/delete")
async def delete_user(user_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        if current_user.id == user_id:
            return redirect("/users")
        user = session.get(User, user_id)
        if user:
            session.delete(user)
            session.commit()
    return redirect("/users")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        return render_page(
            request,
            session,
            current_user,
            "settings.html",
            "settings",
        )


@app.post("/settings")
async def update_settings(request: Request):
    form = await request.form()
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        settings = get_settings(session)
        settings.school_name = str(form.get("school_name", "")).strip()
        settings.school_email = str(form.get("school_email", "")).strip()
        settings.phone_number = str(form.get("phone_number", "")).strip()
        settings.logo_url = str(form.get("logo_url", "")).strip()
        settings.address = str(form.get("address", "")).strip()
        settings.academic_year = str(form.get("academic_year", "")).strip()
        settings.financial_year = str(form.get("financial_year", "")).strip()
        settings.fee_frequency = str(form.get("fee_frequency", "Monthly")).strip()
        settings.currency = str(form.get("currency", "INR (Rs)")).strip()
        settings.timezone = str(form.get("timezone", "Asia/Kolkata (IST)")).strip()
        settings.developer_name = str(form.get("developer_name", "")).strip()
        settings.developer_email = str(form.get("developer_email", "")).strip()
        settings.developer_phone = str(form.get("developer_phone", "")).strip()
        session.commit()
    return redirect("/settings")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
