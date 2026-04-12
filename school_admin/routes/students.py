from __future__ import annotations

import re
import threading
import webbrowser
from datetime import date
from html import escape
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from school_admin.database import SessionLocal
from school_admin.models import Course, Fee, Hostel, Payment, Section, Setting, Student, TransportRoute
from school_admin.utils import (
    active_lookups,
    applicable_fees_for_student,
    calculate_fee_snapshots_for_students,
    calculate_student_fees_and_payments,
    form_with_csrf,
    optional_date,
    optional_int,
    redirect,
    render_page,
    require_user,
    student_payment_summary,
)
from school_admin.routes.payments import apply_receipt_snapshot


router = APIRouter()
LIST_PAGE_SIZE = 10
STUDENT_STATUSES = {"Active", "Inactive"}
ADMISSION_PAYMENT_METHODS = {"Cash", "UPI", "Card", "Bank Transfer"}
STUDENT_ERROR_MESSAGES = {
    "missing_fields": "Fill in the student code, full name, guardian email, guardian phone, and course before saving.",
    "invalid_status": "Choose a valid status for the student record.",
    "invalid_lookup": "Choose valid course, section, hostel, and transport values from the current lists.",
    "invalid_joined_on": "Enter a valid join date for the student.",
    "duplicate": "That student code is already in use.",
    "invalid_method": "Choose a valid admission payment method.",
    "students_read_only": "Create student records from Admissions. The student list is filled automatically after admission.",
    "missing_admission_fee": "Set up at least one active admission fee in Fees before creating a new admission or changing a student's course.",
    "missing_guardian_phone": "Add the guardian phone number before opening WhatsApp.",
    "missing_guardian_email": "Add the guardian email address before opening Gmail.",
    "promotion_student_missing": "The selected student record for promotion could not be found.",
    "promotion_course_unavailable": "No higher active course is available for this student.",
}
ALLOWED_RETURN_PATHS = {"/students", "/admissions"}


def sanitized_return_path(value: str | None, fallback: str = "/students") -> str:
    candidate = str(value or "").strip()
    return candidate if candidate in ALLOWED_RETURN_PATHS else fallback


def natural_course_sort_key(value: str) -> tuple[object, ...]:
    pieces = re.split(r"(\d+)", str(value or "").strip().lower())
    return tuple(int(piece) if piece.isdigit() else piece for piece in pieces)


def ordered_courses(courses: list[Course]) -> list[Course]:
    return sorted(
        courses,
        key=lambda course: (
            natural_course_sort_key(course.name),
            natural_course_sort_key(course.code),
            course.id,
        ),
    )


def next_course_map(courses: list[Course]) -> dict[int, Course]:
    ordered = ordered_courses(courses)
    return {
        ordered[index].id: ordered[index + 1]
        for index in range(len(ordered) - 1)
    }


def matching_promoted_section(
    sections: list[Section],
    source_section: Section | None,
    next_course: Course | None,
) -> Section | None:
    if source_section is None or next_course is None:
        return None
    candidate_sections = [section for section in sections if section.course_id == next_course.id]
    for section in candidate_sections:
        if section.name == source_section.name:
            return section
    for section in candidate_sections:
        if section.code and section.code == source_section.code:
            return section
    return None


def build_promotion_form_student(
    student: Student,
    next_course: Course,
    next_section: Section | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        student_code=student.student_code,
        full_name=student.full_name,
        email=student.email,
        phone=student.phone,
        parent_name=student.parent_name,
        status=student.status,
        address=student.address,
        joined_on=date.today(),
        course_id=next_course.id,
        section_id=next_section.id if next_section else None,
        hostel_id=student.hostel_id,
        transport_id=student.transport_id,
    )


def student_form_redirect_url(
    return_path: str,
    error: str,
    *,
    promotion_source_student_id: int | None = None,
) -> str:
    query: list[tuple[str, str | int]] = []
    if promotion_source_student_id is not None:
        query.append(("promote", promotion_source_student_id))
    else:
        query.append(("create", 1))
    query.append(("error", error))
    return f"{return_path}?{urlencode(query)}"


def student_workspace_labels(active_page: str) -> dict[str, str]:
    if active_page == "admissions":
        return {
            "page_title": "Admissions Management",
            "page_description": "Capture admissions using the same student record flow. Every admission is added to the student list automatically.",
            "create_button_label": "Add Admission",
            "form_title_create": "Add Admission",
            "form_title_edit": "Edit Admission",
            "form_description": "Capture admission details and create the linked student record.",
            "list_title": "Admission Records",
            "list_description": "Search, review, and manage admitted students with guardian contact details, course, and section.",
            "record_label": "Admission",
        }
    return {
        "page_title": "Students Management",
        "page_description": "Review student records created from the admissions screen. New students are added automatically after admission.",
        "create_button_label": "Add Student",
        "form_title_create": "Add Student",
        "form_title_edit": "Edit Student",
        "form_description": "Store complete student profile information.",
        "list_title": "Student Records",
        "list_description": "Search, review, and manage student profiles with guardian contact details, course, and section.",
        "record_label": "Student",
    }


def reminder_breakdown_lines(student: Student, fees_data: dict[str, float]) -> list[str]:
    lines: list[str] = []
    for item in fees_data["fee_items"]:
        current_month_amount = float(item["current_month_amount"])
        if current_month_amount <= 0:
            continue
        item_name = str(item["name"])
        frequency = str(item["frequency"])
        if frequency in {"Quarterly", "Half-Yearly", "Yearly"}:
            item_name = f"{item_name} (monthly from {frequency.lower()} plan)"
        lines.append(f"{item_name}: {current_month_amount:.2f}")
    lines.append(f"This Month's Charges: {fees_data['current_cycle_amount']:.2f}")
    if fees_data["previous_pending_amount"] > 0:
        lines.append(f"Earlier Pending Balance: {fees_data['previous_pending_amount']:.2f}")
    lines.append(f"Amount Paid So Far: {fees_data['paid_amount']:.2f}")
    lines.append(f"Outstanding Balance: {fees_data['remaining_balance']:.2f}")
    return lines


def reminder_subject(settings: Setting, student: Student) -> str:
    school_name = settings.school_name or "School"
    return f"Payment Reminder - {school_name} - {student.student_code}"


def reminder_message(settings: Setting, student: Student, fees_data: dict[str, float]) -> str:
    school_name = settings.school_name or "School"
    school_phone = settings.phone_number or ""
    school_email = settings.school_email or ""
    academic_year = settings.academic_year or ""
    currency = settings.currency or "INR"
    parent_name = student.parent_name or "Parent/Guardian"

    lines = [
        f"Dear {parent_name},",
        "",
        (
            f"This is a payment reminder from {school_name} for {student.full_name} "
            f"({student.student_code}) for the academic year {academic_year}."
        ),
        "",
        "The amount below shows this month's charges and any unpaid earlier balance.",
        "",
        *reminder_breakdown_lines(student, fees_data),
        "",
        f"Please arrange payment of {currency} {fees_data['remaining_balance']:.2f} at the earliest.",
    ]
    if school_phone or school_email:
        lines.extend(
            [
                "",
                f"For support, contact {school_name} on {school_phone} or {school_email}.",
            ]
        )
    lines.extend(["", "Regards,", school_name])
    return "\n".join(lines)


def normalized_whatsapp_phone(phone: str) -> str:
    return "".join(character for character in str(phone or "") if character.isdigit())


def open_external_target(url: str) -> None:
    threading.Thread(target=webbrowser.open, args=(url,), kwargs={"new": 2}, daemon=True).start()


def first_applicable_admission_fee(session, student: Student) -> Fee | None:
    admission_fees = applicable_fees_for_student(session, student, category="Admission")
    admission_fees.sort(
        key=lambda fee: (
            0 if str(fee.target_type or "").strip() == "Course" and fee.target_id is not None else 1,
            fee.name,
            fee.id,
        )
    )
    return admission_fees[0] if admission_fees else None


def create_admission_payment(
    session,
    student: Student,
    admission_fee: Fee,
    *,
    payment_date: date,
    method: str,
    reference: str,
    notes: str = "",
) -> Payment:
    payment = Payment(
        student_id=student.id,
        student_code=student.student_code,
        student_name=student.full_name,
        parent_name=student.parent_name or "",
        service_type="admission",
        service_id=admission_fee.id,
        service_name=admission_fee.name,
        amount=float(admission_fee.amount or 0),
        payment_date=payment_date,
        method=method,
        reference=reference,
        notes=notes,
        status="Paid",
    )
    apply_receipt_snapshot(session, payment, student)
    session.add(payment)
    return payment


def apply_student_search(statement, search: str, *, broad: bool = False):
    query = search.strip()
    if not query:
        return statement

    field_matcher = "contains" if broad else "startswith"
    statement = statement.outerjoin(Student.course).outerjoin(Student.section)
    return statement.where(
        or_(
            Student.student_code == query,
            Student.full_name == query,
            Student.email == query,
            Student.phone == query,
            getattr(Student.student_code, field_matcher)(query),
            getattr(Student.full_name, field_matcher)(query),
            getattr(Student.email, field_matcher)(query),
            getattr(Student.phone, field_matcher)(query),
            getattr(Course.name, field_matcher)(query),
            getattr(Section.name, field_matcher)(query),
        )
    ).distinct()


def render_student_workspace(
    request: Request,
    *,
    active_page: str,
    search: str = "",
    page: int = 1,
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
    promote: int | None = None,
    error: str = "",
):
    labels = student_workspace_labels(active_page)
    base_path = "/admissions" if active_page == "admissions" else "/students"
    allow_manual_create = active_page == "admissions"
    if create and not allow_manual_create and not error:
        error = "students_read_only"
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        lookups = active_lookups(session)
        promotion_next_courses = next_course_map(lookups["courses"])
        statement = (
            select(Student)
            .options(
                joinedload(Student.course),
                joinedload(Student.section),
                joinedload(Student.hostel),
                joinedload(Student.transport_route),
            )
            .order_by(Student.id.desc())
        )
        page = max(page, 1)
        search_query = search.strip()
        total_students = 0
        if search_query:
            fast_statement = apply_student_search(statement, search_query)
            total_students = session.scalar(
                select(func.count()).select_from(fast_statement.order_by(None).subquery())
            ) or 0
            if total_students >= LIST_PAGE_SIZE:
                statement = fast_statement
            else:
                statement = apply_student_search(statement, search_query, broad=True)
                total_students = session.scalar(
                    select(func.count()).select_from(statement.order_by(None).subquery())
                ) or 0
        else:
            total_students = session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            ) or 0
        total_pages = max((total_students + LIST_PAGE_SIZE - 1) // LIST_PAGE_SIZE, 1)
        page = min(page, total_pages)
        page_students_statement = statement.limit(LIST_PAGE_SIZE).offset((page - 1) * LIST_PAGE_SIZE)
        selected_student = session.get(Student, edit or view) if (edit or view) else None
        promote_student = session.get(Student, promote) if promote else None
        promote_next_course = promotion_next_courses.get(promote_student.course_id) if promote_student else None
        promote_next_section = matching_promoted_section(
            lookups["sections"],
            promote_student.section if promote_student else None,
            promote_next_course,
        )
        promote_form_student = None
        if promote and promote_student is None and not error:
            error = "promotion_student_missing"
        elif promote and promote_next_course is None and not error:
            error = "promotion_course_unavailable"
        elif promote_student and promote_next_course is not None:
            promote_form_student = build_promotion_form_student(
                promote_student,
                promote_next_course,
                promote_next_section,
            )
        student_payment_summary_data = (
            student_payment_summary(session, selected_student.id) if selected_student else {}
        )
        selected_student_fees = {}
        if selected_student:
            selected_student_fees = calculate_student_fees_and_payments(session, selected_student)

        students = session.scalars(page_students_statement).all()
        fee_snapshots = calculate_fee_snapshots_for_students(session, students)
        students_data = []
        for student in students:
            students_data.append(
                {
                    "student": student,
                    "fees_payments": fee_snapshots.get(student.id, {}),
                    "promotion_next_course": promotion_next_courses.get(student.course_id),
                }
            )
        pagination_params = {"page": page}
        if search.strip():
            pagination_params["search"] = search.strip()
        page_start = ((page - 1) * LIST_PAGE_SIZE) + 1 if total_students else 0
        page_end = min(page * LIST_PAGE_SIZE, total_students)

        return render_page(
            request,
            session,
            current_user,
            "students.html",
            active_page,
            students_data=students_data,
            form_mode=(
                "create"
                if allow_manual_create and (create or promote_form_student is not None)
                else None
            )
            if not edit
            else "edit",
            form_student=selected_student if edit else promote_form_student,
            view_student=selected_student if view else None,
            view_student_payments=student_payment_summary_data,
            view_student_fees=selected_student_fees,
            search=search,
            lookups=lookups,
            error_message=STUDENT_ERROR_MESSAGES.get(error, ""),
            base_path=base_path,
            return_path=base_path,
            labels=labels,
            allow_manual_create=allow_manual_create,
            admission_payment_methods=sorted(ADMISSION_PAYMENT_METHODS),
            promotion_context={
                "source_student": promote_student,
                "next_course": promote_next_course,
                "next_section": promote_next_section,
            }
            if promote_form_student is not None
            else None,
            view_student_next_course=promotion_next_courses.get(selected_student.course_id)
            if selected_student
            else None,
            pagination={
                "page": page,
                "page_size": LIST_PAGE_SIZE,
                "total_items": total_students,
                "total_pages": total_pages,
                "has_previous": page > 1,
                "has_next": page < total_pages,
                "previous_query": urlencode({**pagination_params, "page": page - 1}) if page > 1 else "",
                "next_query": urlencode({**pagination_params, "page": page + 1}) if page < total_pages else "",
                "page_start": page_start,
                "page_end": page_end,
            },
        )


@router.get("/students", response_class=HTMLResponse)
async def students_page(
    request: Request,
    search: str = "",
    page: int = 1,
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
    error: str = "",
):
    return render_student_workspace(
        request,
        active_page="students",
        search=search,
        page=page,
        create=create,
        edit=edit,
        view=view,
        error=error,
    )


@router.get("/admissions", response_class=HTMLResponse)
async def admissions_page(
    request: Request,
    search: str = "",
    page: int = 1,
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
    promote: int | None = None,
    error: str = "",
):
    return render_student_workspace(
        request,
        active_page="admissions",
        search=search,
        page=page,
        create=create,
        edit=edit,
        view=view,
        promote=promote,
        error=error,
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
        return_path = sanitized_return_path(form.get("return_path"), "/students")
        if return_path != "/admissions":
            return redirect("/students?error=students_read_only")
        promotion_source_student_id = optional_int(str(form.get("promotion_source_student_id", "")))
        promotion_source_student = (
            session.get(Student, promotion_source_student_id)
            if promotion_source_student_id is not None
            else None
        )
        if promotion_source_student_id is not None and promotion_source_student is None:
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "promotion_student_missing",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )
        student_code = str(form.get("student_code", "")).strip()
        full_name = str(form.get("full_name", "")).strip()
        email = str(form.get("email", "")).strip()
        phone = str(form.get("phone", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not student_code or not full_name or not email or not phone:
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "missing_fields",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )
        if status not in STUDENT_STATUSES:
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "invalid_status",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )
        try:
            joined_on = optional_date(str(form.get("joined_on", "")) or None)
        except ValueError:
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "invalid_joined_on",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )
        course_id = optional_int(str(form.get("course_id", "")))
        section_id = optional_int(str(form.get("section_id", "")))
        hostel_id = optional_int(str(form.get("hostel_id", "")))
        transport_id = optional_int(str(form.get("transport_id", "")))
        if course_id is None:
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "missing_fields",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )
        section = session.get(Section, section_id) if section_id is not None else None
        if (
            (course_id is not None and session.get(Course, course_id) is None)
            or (section_id is not None and (section is None or section.course_id != course_id))
            or (hostel_id is not None and session.get(Hostel, hostel_id) is None)
            or (transport_id is not None and session.get(TransportRoute, transport_id) is None)
        ):
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "invalid_lookup",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )
        student = promotion_source_student or Student()
        if promotion_source_student is None:
            session.add(student)
        student.student_code = student_code
        student.full_name = full_name
        student.email = email
        student.phone = phone
        student.parent_name = str(form.get("parent_name", "")).strip()
        student.status = status
        student.address = str(form.get("address", "")).strip()
        student.joined_on = joined_on
        student.course_id = course_id
        student.section_id = section_id
        student.hostel_id = hostel_id
        student.transport_id = transport_id
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "duplicate",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )

        admission_fee = first_applicable_admission_fee(session, student)
        if admission_fee is None:
            session.rollback()
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "missing_admission_fee",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )

        method = str(form.get("admission_method", "Cash")).strip() or "Cash"
        if method not in ADMISSION_PAYMENT_METHODS:
            session.rollback()
            return redirect(
                student_form_redirect_url(
                    return_path,
                    "invalid_method",
                    promotion_source_student_id=promotion_source_student_id,
                )
            )

        payment = create_admission_payment(
            session,
            student,
            admission_fee,
            payment_date=joined_on,
            method=method,
            reference=str(form.get("admission_reference", "")).strip()
            or (
                f"ADM-PROM-{student.student_code}"
                if promotion_source_student_id is not None
                else f"ADM-{student.student_code}"
            ),
            notes=str(form.get("admission_notes", "")).strip(),
        )
        session.flush()
        payment_id = payment.id
        session.commit()
    return redirect(f"/payments/{payment_id}/bill")


@router.post("/students/{student_id}/edit")
async def edit_student(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/students")
        if response:
            return response
        return_path = sanitized_return_path(form.get("return_path"), "/students")
        student = session.get(Student, student_id)
        if not student:
            return redirect(return_path)
        previous_course_id = student.course_id
        student_code = str(form.get("student_code", "")).strip()
        full_name = str(form.get("full_name", "")).strip()
        email = str(form.get("email", "")).strip()
        phone = str(form.get("phone", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not student_code or not full_name or not email or not phone:
            return redirect(f"{return_path}?edit={student_id}&error=missing_fields")
        if status not in STUDENT_STATUSES:
            return redirect(f"{return_path}?edit={student_id}&error=invalid_status")
        try:
            joined_on = optional_date(str(form.get("joined_on", "")) or None, student.joined_on)
        except ValueError:
            return redirect(f"{return_path}?edit={student_id}&error=invalid_joined_on")
        course_id = optional_int(str(form.get("course_id", "")))
        section_id = optional_int(str(form.get("section_id", "")))
        hostel_id = optional_int(str(form.get("hostel_id", "")))
        transport_id = optional_int(str(form.get("transport_id", "")))
        if course_id is None:
            return redirect(f"{return_path}?edit={student_id}&error=missing_fields")
        course = session.get(Course, course_id) if course_id is not None else None
        section = session.get(Section, section_id) if section_id is not None else None
        if (
            (course_id is not None and course is None)
            or (section_id is not None and (section is None or section.course_id != course_id))
            or (hostel_id is not None and session.get(Hostel, hostel_id) is None)
            or (transport_id is not None and session.get(TransportRoute, transport_id) is None)
        ):
            return redirect(f"{return_path}?edit={student_id}&error=invalid_lookup")
        previous_course = session.get(Course, previous_course_id) if previous_course_id is not None else None
        student.student_code = student_code
        student.full_name = full_name
        student.email = email
        student.phone = phone
        student.parent_name = str(form.get("parent_name", "")).strip()
        student.status = status
        student.address = str(form.get("address", "")).strip()
        student.joined_on = joined_on
        student.course_id = course_id
        student.section_id = section_id
        student.hostel_id = hostel_id
        student.transport_id = transport_id
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return redirect(f"{return_path}?edit={student_id}&error=duplicate")
        course_changed = previous_course_id != course_id
        payment_id = None
        if course_changed:
            admission_fee = first_applicable_admission_fee(session, student)
            if admission_fee is None:
                session.rollback()
                return redirect(f"{return_path}?edit={student_id}&error=missing_admission_fee")
            payment = create_admission_payment(
                session,
                student,
                admission_fee,
                payment_date=joined_on,
                method="Cash",
                reference=f"ADM-COURSE-{student.student_code}-{date.today().strftime('%Y%m%d')}",
                notes=(
                    "Admission fee applied after course change"
                    f" from {previous_course.name if previous_course else 'unassigned'}"
                    f" to {course.name if course else 'unassigned'}."
                ),
            )
            session.flush()
            payment_id = payment.id
        session.commit()
        if payment_id is not None:
            return redirect(f"/payments/{payment_id}/bill")
    return redirect(return_path)


@router.post("/students/{student_id}/delete")
async def delete_student(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/students")
        if response:
            return response
        return_path = sanitized_return_path(form.get("return_path"), "/students")
        student = session.scalar(
            select(Student)
            .options(joinedload(Student.payments))
            .where(Student.id == student_id)
        )
        if student:
            for payment in student.payments:
                if not any(
                    float(value or 0) != 0
                    for value in (
                        payment.snapshot_total_fees,
                        payment.snapshot_paid_amount,
                        payment.snapshot_current_cycle_amount,
                        payment.snapshot_previous_pending_amount,
                        payment.snapshot_remaining_balance,
                    )
                ):
                    apply_receipt_snapshot(session, payment, student)
                payment.student_code = str(student.student_code or "")
                payment.student_name = str(student.full_name or "")
                payment.parent_name = str(student.parent_name or "")
                payment.student = None
            session.delete(student)
            session.commit()
    return redirect(return_path)


@router.post("/students/{student_id}/notify")
async def notify_guardian(student_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/students")
        if response:
            return response

        return_path = sanitized_return_path(form.get("return_path"), "/students")
        student = session.get(Student, student_id)
        if not student:
            return redirect(return_path)

        fees_data = calculate_student_fees_and_payments(session, student)
        if fees_data["remaining_balance"] <= 0:
            return redirect(return_path)

        settings = session.get(Setting, 1) or Setting()
        school_name = escape(settings.school_name or "")
        school_address = escape(settings.address or "")
        school_phone = escape(settings.phone_number or "")
        school_email = escape(settings.school_email or "")
        school_currency = escape(settings.currency or "")
        academic_year = escape(settings.academic_year or "")
        student_name = escape(student.full_name or "")
        student_code = escape(student.student_code or "")
        parent_name = escape(student.parent_name or "Parent/Guardian")
        student_address = escape(student.address or "N/A")
        student_phone = escape(student.phone or "")
        student_email = escape(student.email or "")

        fee_rows = []
        for item in fees_data["fee_items"]:
            current_month_amount = float(item["current_month_amount"])
            if current_month_amount <= 0:
                continue
            item_label = escape(str(item["name"]))
            frequency = str(item["frequency"])
            if frequency in {"Quarterly", "Half-Yearly", "Yearly"}:
                item_label = f"{item_label} (monthly from {escape(frequency.lower())} plan)"
            fee_rows.append(
                f"""
                        <tr>
                            <td>{item_label}</td>
                            <td>{current_month_amount:.2f}</td>
                        </tr>"""
            )
        fee_rows_html = "".join(fee_rows)

        notification_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Payment Reminder - {school_name}</title>
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
                <h1>{school_name}</h1>
                <p>{school_address}</p>
                <p>Phone: {school_phone} | Email: {school_email}</p>
            </div>

            <div class="school-info">
                <p><strong>Date:</strong> {date.today().strftime('%B %d, %Y')}</p>
            </div>

            <div class="student-info">
                <h2>Payment Reminder Notice</h2>
                <p><strong>Student Name:</strong> {student_name}</p>
                <p><strong>Student Code:</strong> {student_code}</p>
                <p><strong>Parent/Guardian:</strong> {parent_name}</p>
                <p><strong>Address:</strong> {student_address}</p>
                <p><strong>Guardian Phone:</strong> {student_phone}</p>
                <p><strong>Guardian Email:</strong> {student_email}</p>
            </div>

            <div class="fee-breakdown">
                <h3>Fee Breakdown</h3>
                <p>This reminder shows this month's amount plus any unpaid earlier balance.</p>
                <table class="fee-table">
                    <thead>
                        <tr>
                            <th>Fee Item</th>
                            <th>Amount ({school_currency})</th>
                        </tr>
                    </thead>
                    <tbody>
                        {fee_rows_html}
                        <tr>
                            <td>This Month's Charges</td>
                            <td>{fees_data['current_cycle_amount']:.2f}</td>
                        </tr>
                        <tr>
                            <td>Earlier Pending Balance</td>
                            <td>{fees_data['previous_pending_amount']:.2f}</td>
                        </tr>
                        <tr class="total-row">
                            <td>Total Outstanding Balance</td>
                            <td>{fees_data['remaining_balance']:.2f}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <div>
                <p>Dear {parent_name},</p>

                <p>This is to inform you that there is an outstanding balance of <strong>{school_currency} {fees_data['remaining_balance']:.2f}</strong>
                for your ward {student_name} (Student Code: {student_code}) for the academic year {academic_year}.</p>

                <p>The amount shown above combines this month's charges and any unpaid previous balance, so the reminder total is the amount currently due.</p>

                <p>Please arrange to clear the outstanding amount at the earliest to avoid any disruption in services.
                Payment can be made through cash, bank transfer, or other accepted payment methods.</p>

                <p>For any queries or assistance, please contact the school administration at {school_phone} or {school_email}.</p>

                <p>Thank you for your attention to this matter.</p>

                <p>Best regards,<br>
                {school_name}<br>
                {school_address}<br>
                Phone: {school_phone}<br>
                Email: {school_email}</p>
            </div>

            <div class="footer">
                <p><em>This is an auto-generated notification from the School Management System.</em></p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=notification_html, status_code=200)


@router.get("/students/{student_id}/notify/whatsapp")
async def notify_guardian_whatsapp(student_id: int, request: Request, return_to: str = "/students"):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response

        return_path = sanitized_return_path(return_to, "/students")
        student = session.get(Student, student_id)
        if not student:
            return redirect(return_path)

        fees_data = calculate_student_fees_and_payments(session, student)
        if fees_data["remaining_balance"] <= 0:
            return redirect(f"{return_path}?view={student_id}")

        phone = normalized_whatsapp_phone(student.phone)
        if not phone:
            return redirect(f"{return_path}?view={student_id}&error=missing_guardian_phone")

        settings = session.get(Setting, 1) or Setting()
        message = reminder_message(settings, student, fees_data)
    open_external_target(f"whatsapp://send?phone={phone}&text={quote(message)}")
    return redirect(f"{return_path}?view={student_id}")


@router.get("/students/{student_id}/notify/gmail")
async def notify_guardian_gmail(student_id: int, request: Request, return_to: str = "/students"):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response

        return_path = sanitized_return_path(return_to, "/students")
        student = session.get(Student, student_id)
        if not student:
            return redirect(return_path)

        fees_data = calculate_student_fees_and_payments(session, student)
        if fees_data["remaining_balance"] <= 0:
            return redirect(f"{return_path}?view={student_id}")

        recipient_email = str(student.email or "").strip()
        if not recipient_email:
            return redirect(f"{return_path}?view={student_id}&error=missing_guardian_email")

        settings = session.get(Setting, 1) or Setting()
        subject = reminder_subject(settings, student)
        body = reminder_message(settings, student, fees_data)
    gmail_url = (
        "https://mail.google.com/mail/?view=cm&fs=1"
        f"&to={quote(recipient_email)}"
        f"&su={quote(subject)}"
        f"&body={quote(body)}"
    )
    open_external_target(gmail_url)
    return redirect(f"{return_path}?view={student_id}")
