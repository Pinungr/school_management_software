from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from school_admin.database import SessionLocal
from school_admin.models import Course, Hostel, Student, TransportRoute
from school_admin.utils import form_with_csrf, optional_float, optional_int, redirect, render_page, require_user


router = APIRouter()
CATALOG_STATUSES = {"Active", "Inactive"}
CATALOG_FREQUENCIES = {"Monthly", "Quarterly", "Half-Yearly", "Yearly"}
CATALOG_ERROR_MESSAGES = {
    "missing_name": "Enter a name before saving this record.",
    "missing_code": "Enter a course code before saving this course.",
    "invalid_amount": "Enter a valid non-negative amount.",
    "invalid_rooms": "Enter a valid room count of zero or more.",
    "invalid_frequency": "Choose a valid fee frequency.",
    "invalid_status": "Choose a valid status.",
    "duplicate": "That code is already in use.",
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


@router.get("/courses", response_class=HTMLResponse)
async def courses_page(
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
            error_message=CATALOG_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/courses/create")
async def create_course(request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        name = str(form.get("name", "")).strip()
        code = str(form.get("code", "")).strip()
        fees = non_negative_float(str(form.get("fees", "")))
        frequency = str(form.get("frequency", "Monthly")).strip()
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect("/courses?create=1&error=missing_name")
        if not code:
            return redirect("/courses?create=1&error=missing_code")
        if fees is None:
            return redirect("/courses?create=1&error=invalid_amount")
        if frequency not in CATALOG_FREQUENCIES:
            return redirect("/courses?create=1&error=invalid_frequency")
        if status not in CATALOG_STATUSES:
            return redirect("/courses?create=1&error=invalid_status")
        session.add(
            Course(
                name=name,
                code=code,
                fees=fees,
                frequency=frequency,
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
        current_user, response = require_user(session, request)
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
        fees = non_negative_float(str(form.get("fees", "")))
        frequency = str(form.get("frequency", "Monthly")).strip()
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect(f"/courses?edit={course_id}&error=missing_name")
        if not code:
            return redirect(f"/courses?edit={course_id}&error=missing_code")
        if fees is None:
            return redirect(f"/courses?edit={course_id}&error=invalid_amount")
        if frequency not in CATALOG_FREQUENCIES:
            return redirect(f"/courses?edit={course_id}&error=invalid_frequency")
        if status not in CATALOG_STATUSES:
            return redirect(f"/courses?edit={course_id}&error=invalid_status")
        course.name = name
        course.code = code
        course.fees = fees
        course.frequency = frequency
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
        current_user, response = require_user(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/courses")
        if response:
            return response
        course = session.get(Course, course_id)
        if course:
            for student in session.scalars(select(Student).where(Student.course_id == course_id)).all():
                student.course_id = None
            session.delete(course)
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
            error_message=CATALOG_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/hostels/create")
async def create_hostel(request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/hostels")
        if response:
            return response
        name = str(form.get("name", "")).strip()
        rooms = non_negative_int(str(form.get("rooms", "")))
        fee_amount = non_negative_float(str(form.get("fee_amount", "")))
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect("/hostels?create=1&error=missing_name")
        if rooms is None:
            return redirect("/hostels?create=1&error=invalid_rooms")
        if fee_amount is None:
            return redirect("/hostels?create=1&error=invalid_amount")
        if status not in CATALOG_STATUSES:
            return redirect("/hostels?create=1&error=invalid_status")
        session.add(
            Hostel(
                name=name,
                hostel_type=str(form.get("hostel_type", "Boys")).strip(),
                rooms=rooms,
                fee_amount=fee_amount,
                status=status,
                description=str(form.get("description", "")).strip(),
            )
        )
        session.commit()
    return redirect("/hostels")


@router.post("/hostels/{hostel_id}/edit")
async def edit_hostel(hostel_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
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
        fee_amount = non_negative_float(str(form.get("fee_amount", "")))
        status = str(form.get("status", "Active")).strip()
        if not name:
            return redirect(f"/hostels?edit={hostel_id}&error=missing_name")
        if rooms is None:
            return redirect(f"/hostels?edit={hostel_id}&error=invalid_rooms")
        if fee_amount is None:
            return redirect(f"/hostels?edit={hostel_id}&error=invalid_amount")
        if status not in CATALOG_STATUSES:
            return redirect(f"/hostels?edit={hostel_id}&error=invalid_status")
        hostel.name = name
        hostel.hostel_type = str(form.get("hostel_type", "Boys")).strip()
        hostel.rooms = rooms
        hostel.fee_amount = fee_amount
        hostel.status = status
        hostel.description = str(form.get("description", "")).strip()
        session.commit()
    return redirect("/hostels")


@router.post("/hostels/{hostel_id}/delete")
async def delete_hostel(hostel_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/hostels")
        if response:
            return response
        hostel = session.get(Hostel, hostel_id)
        if hostel:
            for student in session.scalars(select(Student).where(Student.hostel_id == hostel_id)).all():
                student.hostel_id = None
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
            error_message=CATALOG_ERROR_MESSAGES.get(error, ""),
        )


@router.post("/transport/create")
async def create_route(request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/transport")
        if response:
            return response
        route_name = str(form.get("route_name", "")).strip()
        fee_amount = non_negative_float(str(form.get("fee_amount", "")))
        frequency = str(form.get("frequency", "Monthly")).strip()
        status = str(form.get("status", "Active")).strip()
        if not route_name:
            return redirect("/transport?create=1&error=missing_name")
        if fee_amount is None:
            return redirect("/transport?create=1&error=invalid_amount")
        if frequency not in CATALOG_FREQUENCIES:
            return redirect("/transport?create=1&error=invalid_frequency")
        if status not in CATALOG_STATUSES:
            return redirect("/transport?create=1&error=invalid_status")
        session.add(
            TransportRoute(
                route_name=route_name,
                pickup_points=str(form.get("pickup_points", "")).strip(),
                fee_amount=fee_amount,
                frequency=frequency,
                status=status,
            )
        )
        session.commit()
    return redirect("/transport")


@router.post("/transport/{route_id}/edit")
async def edit_route(route_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        form, response = await form_with_csrf(request, "/transport")
        if response:
            return response
        route = session.get(TransportRoute, route_id)
        if not route:
            return redirect("/transport")
        route_name = str(form.get("route_name", "")).strip()
        fee_amount = non_negative_float(str(form.get("fee_amount", "")))
        frequency = str(form.get("frequency", "Monthly")).strip()
        status = str(form.get("status", "Active")).strip()
        if not route_name:
            return redirect(f"/transport?edit={route_id}&error=missing_name")
        if fee_amount is None:
            return redirect(f"/transport?edit={route_id}&error=invalid_amount")
        if frequency not in CATALOG_FREQUENCIES:
            return redirect(f"/transport?edit={route_id}&error=invalid_frequency")
        if status not in CATALOG_STATUSES:
            return redirect(f"/transport?edit={route_id}&error=invalid_status")
        route.route_name = route_name
        route.pickup_points = str(form.get("pickup_points", "")).strip()
        route.fee_amount = fee_amount
        route.frequency = frequency
        route.status = status
        session.commit()
    return redirect("/transport")


@router.post("/transport/{route_id}/delete")
async def delete_route(route_id: int, request: Request):
    with SessionLocal() as session:
        current_user, response = require_user(session, request)
        if response:
            return response
        _, response = await form_with_csrf(request, "/transport")
        if response:
            return response
        route = session.get(TransportRoute, route_id)
        if route:
            for student in session.scalars(select(Student).where(Student.transport_id == route_id)).all():
                student.transport_id = None
            session.delete(route)
            session.commit()
    return redirect("/transport")
