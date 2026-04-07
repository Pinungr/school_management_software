from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from school_admin.database import SessionLocal
from school_admin.models import Course, Fee, Hostel, Section, Student, TransportRoute
from school_admin.utils import (
    FEE_CATEGORIES,
    FEE_FREQUENCIES,
    FEE_TARGET_TYPES,
    active_lookups,
    fee_target_display_name,
    form_with_csrf,
    optional_float,
    optional_int,
    redirect,
    render_page,
    require_admin,
    require_user,
)


router = APIRouter()
CATALOG_STATUSES = {"Active", "Inactive"}
CATALOG_ERROR_MESSAGES = {
    "missing_name": "Enter a name before saving this record.",
    "missing_code": "Enter a course code before saving this course.",
    "missing_course": "Choose a course before saving this section.",
    "invalid_amount": "Enter a valid non-negative amount.",
    "invalid_rooms": "Enter a valid room count of zero or more.",
    "invalid_status": "Choose a valid status.",
    "invalid_category": "Choose a valid fee category.",
    "invalid_target": "Choose a valid fee target.",
    "invalid_frequency": "Choose a valid fee frequency.",
    "duplicate": "That code is already in use.",
}

CATEGORY_TARGET_TYPE_MAP = {
    "Admission": "Course",
    "Course": "Course",
    "Hostel": "Hostel",
    "Transport": "Transport",
    "Other": "General",
}


def non_negative_float(value: str) -> float | None:
    try:
        amount = optional_float(value)
    except ValueError:
        return None
    return amount if amount >= 0 else None


def non_negative_int(value: str) -> int | None:
    try:
        amount = optional_int(value)
    except ValueError:
        return None
    if amount is None:
        return 0
    return amount if amount >= 0 else None


def target_type_for_fee_category(category: str) -> str:
    return CATEGORY_TARGET_TYPE_MAP.get(str(category or "").strip().title(), "General")


def resolve_fee_target(
    session,
    category: str,
    raw_target_id: str,
) -> tuple[str, int | None, bool]:
    normalized_target_type = target_type_for_fee_category(category)
    target_id = optional_int(raw_target_id)
    if normalized_target_type == "General":
        return normalized_target_type, None, True
    if target_id is None:
        return normalized_target_type, None, False
    if normalized_target_type == "Course":
        return normalized_target_type, target_id, session.get(Course, target_id) is not None
    if normalized_target_type == "Hostel":
        return normalized_target_type, target_id, session.get(Hostel, target_id) is not None
    if normalized_target_type == "Transport":
        return normalized_target_type, target_id, session.get(TransportRoute, target_id) is not None
    return normalized_target_type, None, False


def normalized_fee_frequency(category: str, frequency: str) -> str:
    if str(category or "").strip().title() == "Admission":
        return "One Time"
    return str(frequency or "Monthly").strip()


@router.get("/fees", response_class=HTMLResponse)
async def fees_page(
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
        can_manage_catalog = current_user.role == "Admin"
        statement = select(Fee).order_by(Fee.id.desc())
        if search.strip():
            query = search.strip()
            statement = statement.where(
                or_(
                    Fee.name.contains(query),
                    Fee.category.contains(query),
                    Fee.target_type.contains(query),
                )
            )
        selected_fee = None
        if view:
            selected_fee = session.get(Fee, view)
        elif can_manage_catalog and edit:
            selected_fee = session.get(Fee, edit)
        fees = session.scalars(statement).all()
        fee_targets = {fee.id: fee_target_display_name(session, fee) for fee in fees}
        return render_page(
            request,
            session,
            current_user,
            "fees.html",
            "fees",
            fees=fees,
            fee_targets=fee_targets,
            form_mode="create" if can_manage_catalog and create else ("edit" if can_manage_catalog and edit else None),
            form_fee=selected_fee if can_manage_catalog and edit else None,
            view_fee=selected_fee if view else None,
            search=search,
            error_message=CATALOG_ERROR_MESSAGES.get(error, ""),
            fee_categories=FEE_CATEGORIES,
            fee_frequencies=FEE_FREQUENCIES,
            fee_target_types=FEE_TARGET_TYPES,
            lookups=active_lookups(session),
            view_fee_target=fee_target_display_name(session, selected_fee) if selected_fee else "",
        )


@router.post("/fees/create")
async def create_fee(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/fees")
        if response:
            return response

        name = str(form.get("name", "")).strip()
        category = str(form.get("category", "Other")).strip().title()
        amount = non_negative_float(str(form.get("amount", "")))
        frequency = normalized_fee_frequency(category, str(form.get("frequency", "One Time")))
        status = str(form.get("status", "Active")).strip()
        target_type, target_id, valid_target = resolve_fee_target(
            session,
            category,
            str(form.get("target_id", "")),
        )

        if not name:
            return redirect("/fees?create=1&error=missing_name")
        if category not in FEE_CATEGORIES:
            return redirect("/fees?create=1&error=invalid_category")
        if amount is None:
            return redirect("/fees?create=1&error=invalid_amount")
        if frequency not in FEE_FREQUENCIES:
            return redirect("/fees?create=1&error=invalid_frequency")
        if target_type not in FEE_TARGET_TYPES or not valid_target:
            return redirect("/fees?create=1&error=invalid_target")
        if status not in CATALOG_STATUSES:
            return redirect("/fees?create=1&error=invalid_status")

        session.add(
            Fee(
                name=name,
                category=category,
                amount=amount,
                frequency=frequency,
                status=status,
                target_type=target_type,
                target_id=target_id,
                description=str(form.get("description", "")).strip(),
            )
        )
        session.commit()
    return redirect("/fees")


@router.post("/fees/{fee_id}/edit")
async def edit_fee(fee_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/fees")
        if response:
            return response
        fee = session.get(Fee, fee_id)
        if not fee:
            return redirect("/fees")

        name = str(form.get("name", "")).strip()
        category = str(form.get("category", "Other")).strip().title()
        amount = non_negative_float(str(form.get("amount", "")))
        frequency = normalized_fee_frequency(category, str(form.get("frequency", "One Time")))
        status = str(form.get("status", "Active")).strip()
        target_type, target_id, valid_target = resolve_fee_target(
            session,
            category,
            str(form.get("target_id", "")),
        )

        if not name:
            return redirect(f"/fees?edit={fee_id}&error=missing_name")
        if category not in FEE_CATEGORIES:
            return redirect(f"/fees?edit={fee_id}&error=invalid_category")
        if amount is None:
            return redirect(f"/fees?edit={fee_id}&error=invalid_amount")
        if frequency not in FEE_FREQUENCIES:
            return redirect(f"/fees?edit={fee_id}&error=invalid_frequency")
        if target_type not in FEE_TARGET_TYPES or not valid_target:
            return redirect(f"/fees?edit={fee_id}&error=invalid_target")
        if status not in CATALOG_STATUSES:
            return redirect(f"/fees?edit={fee_id}&error=invalid_status")

        fee.name = name
        fee.category = category
        fee.amount = amount
        fee.frequency = frequency
        fee.status = status
        fee.target_type = target_type
        fee.target_id = target_id
        fee.description = str(form.get("description", "")).strip()
        session.commit()
    return redirect("/fees")


@router.post("/fees/{fee_id}/delete")
async def delete_fee(fee_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/fees")
        if response:
            return response
        fee = session.get(Fee, fee_id)
        if fee:
            session.delete(fee)
            session.commit()
    return redirect("/fees")


@router.get("/courses", response_class=HTMLResponse)
async def courses_page(
    request: Request,
    search: str = "",
    create: int | None = None,
    edit: int | None = None,
    view: int | None = None,
    section_create: int | None = None,
    section_edit: int | None = None,
    section_view: int | None = None,
    section_search: str = "",
    error: str = "",
):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        can_manage_catalog = current_user.role == "Admin"
        section_courses = session.scalars(select(Course).order_by(Course.name)).all()
        statement = select(Course).order_by(Course.id.desc())
        if search.strip():
            statement = statement.where(
                or_(Course.name.contains(search.strip()), Course.code.contains(search.strip()))
            )
        selected_course = None
        if view:
            selected_course = session.get(Course, view)
        elif can_manage_catalog and edit:
            selected_course = session.get(Course, edit)
        section_statement = select(Section).options(joinedload(Section.course)).order_by(Section.id.desc())
        if section_search.strip():
            section_statement = section_statement.where(
                or_(
                    Section.name.contains(section_search.strip()),
                    Section.code.contains(section_search.strip()),
                    Section.class_teacher.contains(section_search.strip()),
                    Section.room_name.contains(section_search.strip()),
                )
            )
        selected_section = None
        if section_view:
            selected_section = session.get(Section, section_view)
        elif can_manage_catalog and section_edit:
            selected_section = session.get(Section, section_edit)
        return render_page(
            request,
            session,
            current_user,
            "courses.html",
            "courses",
            courses=session.scalars(statement).all(),
            section_courses=section_courses,
            form_mode="create" if can_manage_catalog and create else ("edit" if can_manage_catalog and edit else None),
            form_course=selected_course if can_manage_catalog and edit else None,
            view_course=selected_course if view else None,
            sections=session.scalars(section_statement).all(),
            section_form_mode="create" if can_manage_catalog and section_create else ("edit" if can_manage_catalog and section_edit else None),
            form_section=selected_section if can_manage_catalog and section_edit else None,
            view_section=selected_section if section_view else None,
            search=search,
            section_search=section_search,
            error_message=CATALOG_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/courses/create")
async def create_course(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        name = str(form.get("name", "")).strip()
        code = str(form.get("code", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect("/courses?create=1&error=missing_name")
        if not code:
            return redirect("/courses?create=1&error=missing_code")
        if status not in CATALOG_STATUSES:
            return redirect("/courses?create=1&error=invalid_status")
        session.add(
            Course(
                name=name,
                code=code,
                fees=0,
                frequency="Monthly",
                status=status,
                description=str(form.get("description", "")).strip(),
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect("/courses?create=1&error=duplicate")
    return redirect("/courses")


@router.post("/courses/{course_id}/edit")
async def edit_course(course_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        course = session.get(Course, course_id)
        if not course:
            return redirect("/courses")
        name = str(form.get("name", "")).strip()
        code = str(form.get("code", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect(f"/courses?edit={course_id}&error=missing_name")
        if not code:
            return redirect(f"/courses?edit={course_id}&error=missing_code")
        if status not in CATALOG_STATUSES:
            return redirect(f"/courses?edit={course_id}&error=invalid_status")
        course.name = name
        course.code = code
        course.status = status
        course.description = str(form.get("description", "")).strip()
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return redirect(f"/courses?edit={course_id}&error=duplicate")
    return redirect("/courses")


@router.post("/courses/{course_id}/delete")
async def delete_course(course_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        course = session.get(Course, course_id)
        if course:
            for student in session.scalars(select(Student).where(Student.course_id == course_id)).all():
                student.course_id = None
                student.section_id = None
            for section in session.scalars(select(Section).where(Section.course_id == course_id)).all():
                session.delete(section)
            for fee in session.scalars(
                select(Fee).where(Fee.target_type == "Course", Fee.target_id == course_id)
            ).all():
                session.delete(fee)
            session.delete(course)
            session.commit()
    return redirect("/courses")


@router.post("/sections/create")
async def create_section(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        course_id = optional_int(str(form.get("course_id", "")))
        name = str(form.get("name", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if course_id is None or session.get(Course, course_id) is None:
            return redirect("/courses?section_create=1&error=missing_course")
        if not name:
            return redirect("/courses?section_create=1&error=missing_name")
        if status not in CATALOG_STATUSES:
            return redirect("/courses?section_create=1&error=invalid_status")
        session.add(
            Section(
                course_id=course_id,
                name=name,
                code=str(form.get("code", "")).strip(),
                class_teacher=str(form.get("class_teacher", "")).strip(),
                room_name=str(form.get("room_name", "")).strip(),
                status=status,
                description=str(form.get("description", "")).strip(),
            )
        )
        session.commit()
    return redirect("/courses")


@router.post("/sections/{section_id}/edit")
async def edit_section(section_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        section = session.get(Section, section_id)
        if not section:
            return redirect("/courses")
        course_id = optional_int(str(form.get("course_id", "")))
        name = str(form.get("name", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if course_id is None or session.get(Course, course_id) is None:
            return redirect(f"/courses?section_edit={section_id}&error=missing_course")
        if not name:
            return redirect(f"/courses?section_edit={section_id}&error=missing_name")
        if status not in CATALOG_STATUSES:
            return redirect(f"/courses?section_edit={section_id}&error=invalid_status")
        section.course_id = course_id
        section.name = name
        section.code = str(form.get("code", "")).strip()
        section.class_teacher = str(form.get("class_teacher", "")).strip()
        section.room_name = str(form.get("room_name", "")).strip()
        section.status = status
        section.description = str(form.get("description", "")).strip()
        for student in session.scalars(select(Student).where(Student.section_id == section_id)).all():
            if student.course_id != course_id:
                student.course_id = course_id
        session.commit()
    return redirect("/courses")


@router.post("/sections/{section_id}/delete")
async def delete_section(section_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        section = session.get(Section, section_id)
        if section:
            for student in session.scalars(select(Student).where(Student.section_id == section_id)).all():
                student.section_id = None
            session.delete(section)
            session.commit()
    return redirect("/courses")


@router.get("/hostels", response_class=HTMLResponse)
async def hostels_page(
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
        can_manage_catalog = current_user.role == "Admin"
        statement = select(Hostel).order_by(Hostel.id.desc())
        if search.strip():
            statement = statement.where(
                or_(Hostel.name.contains(search.strip()), Hostel.hostel_type.contains(search.strip()))
            )
        selected_hostel = None
        if view:
            selected_hostel = session.get(Hostel, view)
        elif can_manage_catalog and edit:
            selected_hostel = session.get(Hostel, edit)
        return render_page(
            request,
            session,
            current_user,
            "hostels.html",
            "hostels",
            hostels=session.scalars(statement).all(),
            form_mode="create" if can_manage_catalog and create else ("edit" if can_manage_catalog and edit else None),
            form_hostel=selected_hostel if can_manage_catalog and edit else None,
            view_hostel=selected_hostel if view else None,
            search=search,
            error_message=CATALOG_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/hostels/create")
async def create_hostel(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/hostels")
        if response:
            return response
        name = str(form.get("name", "")).strip()
        rooms = non_negative_int(str(form.get("rooms", "")))
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect("/hostels?create=1&error=missing_name")
        if rooms is None:
            return redirect("/hostels?create=1&error=invalid_rooms")
        if status not in CATALOG_STATUSES:
            return redirect("/hostels?create=1&error=invalid_status")
        session.add(
            Hostel(
                name=name,
                hostel_type=str(form.get("hostel_type", "Boys")).strip(),
                rooms=rooms,
                fee_amount=0,
                status=status,
                description=str(form.get("description", "")).strip(),
            )
        )
        session.commit()
    return redirect("/hostels")


@router.post("/hostels/{hostel_id}/edit")
async def edit_hostel(hostel_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/hostels")
        if response:
            return response
        hostel = session.get(Hostel, hostel_id)
        if not hostel:
            return redirect("/hostels")
        name = str(form.get("name", "")).strip()
        rooms = non_negative_int(str(form.get("rooms", "")))
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect(f"/hostels?edit={hostel_id}&error=missing_name")
        if rooms is None:
            return redirect(f"/hostels?edit={hostel_id}&error=invalid_rooms")
        if status not in CATALOG_STATUSES:
            return redirect(f"/hostels?edit={hostel_id}&error=invalid_status")
        hostel.name = name
        hostel.hostel_type = str(form.get("hostel_type", "Boys")).strip()
        hostel.rooms = rooms
        hostel.status = status
        hostel.description = str(form.get("description", "")).strip()
        session.commit()
    return redirect("/hostels")


@router.post("/hostels/{hostel_id}/delete")
async def delete_hostel(hostel_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/hostels")
        if response:
            return response
        hostel = session.get(Hostel, hostel_id)
        if hostel:
            for student in session.scalars(select(Student).where(Student.hostel_id == hostel_id)).all():
                student.hostel_id = None
            for fee in session.scalars(
                select(Fee).where(Fee.target_type == "Hostel", Fee.target_id == hostel_id)
            ).all():
                session.delete(fee)
            session.delete(hostel)
            session.commit()
    return redirect("/hostels")


@router.get("/transport", response_class=HTMLResponse)
async def transport_page(
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
        can_manage_catalog = current_user.role == "Admin"
        statement = select(TransportRoute).order_by(TransportRoute.id.desc())
        if search.strip():
            statement = statement.where(
                or_(
                    TransportRoute.route_name.contains(search.strip()),
                    TransportRoute.pickup_points.contains(search.strip()),
                )
            )
        selected_route = None
        if view:
            selected_route = session.get(TransportRoute, view)
        elif can_manage_catalog and edit:
            selected_route = session.get(TransportRoute, edit)
        return render_page(
            request,
            session,
            current_user,
            "transport.html",
            "transport",
            routes=session.scalars(statement).all(),
            form_mode="create" if can_manage_catalog and create else ("edit" if can_manage_catalog and edit else None),
            form_route=selected_route if can_manage_catalog and edit else None,
            view_route=selected_route if view else None,
            search=search,
            error_message=CATALOG_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/transport/create")
async def create_route(request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/transport")
        if response:
            return response
        route_name = str(form.get("route_name", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not route_name:
            return redirect("/transport?create=1&error=missing_name")
        if status not in CATALOG_STATUSES:
            return redirect("/transport?create=1&error=invalid_status")
        session.add(
            TransportRoute(
                route_name=route_name,
                pickup_points=str(form.get("pickup_points", "")).strip(),
                vehicle_no=str(form.get("vehicle_no", "")).strip(),
                driver_name=str(form.get("driver_name", "")).strip(),
                driver_phone=str(form.get("driver_phone", "")).strip(),
                fee_amount=0,
                frequency="Monthly",
                status=status,
            )
        )
        session.commit()
    return redirect("/transport")


@router.post("/transport/{route_id}/edit")
async def edit_route(route_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/transport")
        if response:
            return response
        route = session.get(TransportRoute, route_id)
        if not route:
            return redirect("/transport")
        route_name = str(form.get("route_name", "")).strip()
        status = str(form.get("status", "Active")).strip()
        if not route_name:
            return redirect(f"/transport?edit={route_id}&error=missing_name")
        if status not in CATALOG_STATUSES:
            return redirect(f"/transport?edit={route_id}&error=invalid_status")
        route.route_name = route_name
        route.pickup_points = str(form.get("pickup_points", "")).strip()
        route.vehicle_no = str(form.get("vehicle_no", "")).strip()
        route.driver_name = str(form.get("driver_name", "")).strip()
        route.driver_phone = str(form.get("driver_phone", "")).strip()
        route.status = status
        session.commit()
    return redirect("/transport")


@router.post("/transport/{route_id}/delete")
async def delete_route(route_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_admin(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/transport")
        if response:
            return response
        route = session.get(TransportRoute, route_id)
        if route:
            for student in session.scalars(select(Student).where(Student.transport_id == route_id)).all():
                student.transport_id = None
            for fee in session.scalars(
                select(Fee).where(Fee.target_type == "Transport", Fee.target_id == route_id)
            ).all():
                session.delete(fee)
            session.delete(route)
            session.commit()
    return redirect("/transport")
