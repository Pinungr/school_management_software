from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from school_admin.models import Course, Fee, Hostel, Payment, Section, Student, TransportRoute, User
from school_admin.routes.catalog import (
    CATALOG_STATUSES,
    non_negative_float,
    non_negative_int,
    resolve_fee_target,
)
from school_admin.routes.payments import PAYMENT_METHODS, PAYMENT_STATUSES, apply_receipt_snapshot, resolve_service_name
from school_admin.utils import (
    FEE_CATEGORIES,
    FEE_FREQUENCIES,
    FEE_TARGET_TYPES,
    optional_date,
    optional_int,
    validate_service_for_type,
)


DATA_REPAIR_TABLE_ORDER = ("students", "payments", "fees", "users", "courses", "sections")
TABLE_PAGE_SIZE = 25
USER_VISIBLE_ROLES = ("Admin", "Clerk")
STUDENT_STATUSES = ("Active", "Inactive")
PAYMENT_SERVICE_TYPES = ("admission", "course", "hostel", "transport", "other")


class DataRepairError(ValueError):
    pass


@dataclass(frozen=True)
class RepairField:
    name: str
    label: str
    input_type: str = "text"
    required: bool = False
    editable: bool = True
    options_key: str | None = None
    help_text: str = ""


@dataclass(frozen=True)
class RepairTableSpec:
    key: str
    label: str
    model: type[Any]
    fields: tuple[RepairField, ...]
    search_fields: tuple[str, ...]


TABLE_SPECS: dict[str, RepairTableSpec] = {
    "students": RepairTableSpec(
        key="students",
        label="Students",
        model=Student,
        search_fields=("student_code", "full_name", "email", "phone", "parent_name"),
        fields=(
            RepairField("id", "ID", editable=False),
            RepairField("student_code", "Student ID", required=True),
            RepairField("full_name", "Full Name", required=True),
            RepairField("email", "Guardian Email", input_type="email", required=True),
            RepairField("phone", "Guardian Phone", required=True),
            RepairField("parent_name", "Parent Name"),
            RepairField("status", "Status", input_type="select", required=True, options_key="student_statuses"),
            RepairField("joined_on", "Joined On", input_type="date", required=True),
            RepairField("course_id", "Course", input_type="select", required=True, options_key="courses"),
            RepairField("section_id", "Section", input_type="select", options_key="sections"),
            RepairField("hostel_id", "Hostel", input_type="select", options_key="hostels"),
            RepairField("transport_id", "Transport", input_type="select", options_key="transport_routes"),
            RepairField("address", "Address", input_type="textarea"),
        ),
    ),
    "payments": RepairTableSpec(
        key="payments",
        label="Payments",
        model=Payment,
        search_fields=("reference", "student_code", "student_name", "service_name", "method", "status"),
        fields=(
            RepairField("id", "ID", editable=False),
            RepairField("student_id", "Linked Student", input_type="select", options_key="students"),
            RepairField("service_type", "Service Type", input_type="select", required=True, options_key="payment_service_types"),
            RepairField("service_id", "Service ID"),
            RepairField("service_name", "Service Name"),
            RepairField("amount", "Amount", input_type="number", required=True),
            RepairField("payment_date", "Payment Date", input_type="date", required=True),
            RepairField("method", "Method", input_type="select", required=True, options_key="payment_methods"),
            RepairField("reference", "Reference"),
            RepairField("notes", "Notes", input_type="textarea"),
            RepairField("status", "Status", input_type="select", required=True, options_key="payment_statuses"),
        ),
    ),
    "fees": RepairTableSpec(
        key="fees",
        label="Fees",
        model=Fee,
        search_fields=("name", "category", "target_type", "description"),
        fields=(
            RepairField("id", "ID", editable=False),
            RepairField("name", "Name", required=True),
            RepairField("category", "Category", input_type="select", required=True, options_key="fee_categories"),
            RepairField("amount", "Amount", input_type="number", required=True),
            RepairField("frequency", "Frequency", input_type="select", required=True, options_key="fee_frequencies"),
            RepairField("status", "Status", input_type="select", required=True, options_key="catalog_statuses"),
            RepairField("target_type", "Target Type", input_type="select", required=True, options_key="fee_target_types"),
            RepairField("target_id", "Target ID"),
            RepairField("description", "Description", input_type="textarea"),
        ),
    ),
    "users": RepairTableSpec(
        key="users",
        label="Users",
        model=User,
        search_fields=("full_name", "username", "email", "role", "status"),
        fields=(
            RepairField("id", "ID", editable=False),
            RepairField("full_name", "Full Name", required=True),
            RepairField("username", "Username", required=True),
            RepairField("email", "Email", input_type="email", required=True),
            RepairField("role", "Role", input_type="select", required=True, options_key="user_roles"),
            RepairField("status", "Status", input_type="select", required=True, options_key="student_statuses"),
            RepairField("created_on", "Created On", input_type="date", required=True),
        ),
    ),
    "courses": RepairTableSpec(
        key="courses",
        label="Courses",
        model=Course,
        search_fields=("name", "code", "status", "description"),
        fields=(
            RepairField("id", "ID", editable=False),
            RepairField("name", "Name", required=True),
            RepairField("code", "Code", required=True),
            RepairField("fees", "Fees", input_type="number", required=True),
            RepairField("frequency", "Frequency", input_type="select", required=True, options_key="course_frequencies"),
            RepairField("status", "Status", input_type="select", required=True, options_key="catalog_statuses"),
            RepairField("description", "Description", input_type="textarea"),
        ),
    ),
    "sections": RepairTableSpec(
        key="sections",
        label="Sections",
        model=Section,
        search_fields=("name", "code", "class_teacher", "room_name", "status", "description"),
        fields=(
            RepairField("id", "ID", editable=False),
            RepairField("course_id", "Course", input_type="select", required=True, options_key="courses"),
            RepairField("name", "Name", required=True),
            RepairField("code", "Code"),
            RepairField("class_teacher", "Class Teacher"),
            RepairField("room_name", "Room"),
            RepairField("status", "Status", input_type="select", required=True, options_key="catalog_statuses"),
            RepairField("description", "Description", input_type="textarea"),
        ),
    ),
}


def available_table_specs() -> list[RepairTableSpec]:
    return [TABLE_SPECS[key] for key in DATA_REPAIR_TABLE_ORDER]


def get_table_spec(table_key: str | None) -> RepairTableSpec:
    key = str(table_key or DATA_REPAIR_TABLE_ORDER[0]).strip().lower()
    return TABLE_SPECS.get(key, TABLE_SPECS[DATA_REPAIR_TABLE_ORDER[0]])


def options_for_field(session: Session) -> dict[str, list[dict[str, str]]]:
    return {
        "student_statuses": [{"value": value, "label": value} for value in STUDENT_STATUSES],
        "catalog_statuses": [{"value": value, "label": value} for value in sorted(CATALOG_STATUSES)],
        "payment_methods": [{"value": value, "label": value} for value in sorted(PAYMENT_METHODS)],
        "payment_statuses": [{"value": value, "label": value} for value in sorted(PAYMENT_STATUSES)],
        "payment_service_types": [{"value": value, "label": value.title()} for value in PAYMENT_SERVICE_TYPES],
        "fee_categories": [{"value": value, "label": value} for value in FEE_CATEGORIES],
        "fee_frequencies": [{"value": value, "label": value} for value in FEE_FREQUENCIES],
        "fee_target_types": [{"value": value, "label": value} for value in FEE_TARGET_TYPES],
        "course_frequencies": [
            {"value": value, "label": value}
            for value in ("Monthly", "Quarterly", "Half-Yearly", "Yearly")
        ],
        "user_roles": [{"value": value, "label": value} for value in USER_VISIBLE_ROLES],
        "courses": _select_options(session, Course, "name"),
        "sections": _select_options(session, Section, "name", extra_label=lambda row: f"{row.name} ({row.code})" if row.code else row.name),
        "hostels": _select_options(session, Hostel, "name"),
        "transport_routes": _select_options(session, TransportRoute, "route_name"),
        "students": _select_options(
            session,
            Student,
            "full_name",
            extra_label=lambda row: f"{row.student_code} - {row.full_name}",
        ),
    }


def _select_options(session: Session, model: type[Any], label_attr: str, extra_label=None) -> list[dict[str, str]]:
    rows = session.scalars(select(model).order_by(getattr(model, label_attr))).all()
    options = [{"value": "", "label": "Not assigned"}]
    for row in rows:
        label = extra_label(row) if extra_label else getattr(row, label_attr)
        options.append({"value": str(row.id), "label": str(label)})
    return options


def build_data_repair_page(
    session: Session,
    *,
    table_key: str | None = None,
    search: str = "",
    page: int = 1,
    edit_id: int | None = None,
) -> dict[str, Any]:
    spec = get_table_spec(table_key)
    statement = select(spec.model)
    if spec.key == "users":
        statement = statement.where(User.role != "SuperAdmin")
    if search.strip():
        query = search.strip()
        statement = statement.where(
            or_(*[getattr(spec.model, field_name).contains(query) for field_name in spec.search_fields])
        )
    statement = statement.order_by(spec.model.id.desc())
    total_items = session.scalar(select(func_count()).select_from(statement.order_by(None).subquery())) or 0
    page = max(page, 1)
    total_pages = max((total_items + TABLE_PAGE_SIZE - 1) // TABLE_PAGE_SIZE, 1)
    page = min(page, total_pages)
    rows = session.scalars(statement.limit(TABLE_PAGE_SIZE).offset((page - 1) * TABLE_PAGE_SIZE)).all()
    options = options_for_field(session)
    edit_row = _get_edit_row(session, spec, edit_id)
    return {
        "table_spec": spec,
        "table_specs": available_table_specs(),
        "table_rows": [_serialize_row(spec, row) for row in rows],
        "edit_row": _serialize_row(spec, edit_row) if edit_row else None,
        "field_options": options,
        "search": search,
        "pagination": {
            "page": page,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "page_start": ((page - 1) * TABLE_PAGE_SIZE) + 1 if total_items else 0,
            "page_end": min(page * TABLE_PAGE_SIZE, total_items),
        },
    }


def func_count():
    from sqlalchemy import func

    return func.count()


def _get_edit_row(session: Session, spec: RepairTableSpec, edit_id: int | None):
    if edit_id is None:
        return None
    row = session.get(spec.model, edit_id)
    if spec.key == "users" and row and row.role == "SuperAdmin":
        return None
    return row


def _serialize_row(spec: RepairTableSpec, row: Any) -> dict[str, Any]:
    serialized = {"id": row.id}
    for field in spec.fields:
        serialized[field.name] = _serialize_value(getattr(row, field.name, None))
    return serialized


def _serialize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def export_table_csv(session: Session, table_key: str) -> tuple[bytes, str]:
    spec = get_table_spec(table_key)
    statement = select(spec.model)
    if spec.key == "users":
        statement = statement.where(User.role != "SuperAdmin")
    statement = statement.order_by(spec.model.id)
    rows = session.scalars(statement).all()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[field.name for field in spec.fields])
    writer.writeheader()
    for row in rows:
        writer.writerow(_serialize_row(spec, row))
    return buffer.getvalue().encode("utf-8"), f"{spec.key}.csv"


def import_table_csv(session: Session, table_key: str, file_bytes: bytes) -> int:
    if not file_bytes:
        raise DataRepairError("missing_import_file")
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataRepairError("invalid_import_file") from exc
    reader = csv.DictReader(io.StringIO(text))
    spec = get_table_spec(table_key)
    expected_columns = {field.name for field in spec.fields}
    if not reader.fieldnames or not expected_columns.issubset(set(reader.fieldnames)):
        raise DataRepairError("invalid_import_file")

    processed = 0
    for row in reader:
        if not any(str(value or "").strip() for value in row.values()):
            continue
        _upsert_row_from_data(session, spec, row)
        processed += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DataRepairError("duplicate_or_invalid_data") from exc
    return processed


def update_row_from_form(session: Session, table_key: str, row_id: int, form_data: dict[str, Any]) -> None:
    spec = get_table_spec(table_key)
    row = _get_edit_row(session, spec, row_id)
    if row is None:
        raise DataRepairError("record_not_found")
    _apply_data_to_row(session, spec, row, form_data)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DataRepairError("duplicate_or_invalid_data") from exc


def _upsert_row_from_data(session: Session, spec: RepairTableSpec, raw_data: dict[str, Any]) -> None:
    row_id = optional_int(str(raw_data.get("id", "")))
    row = _get_edit_row(session, spec, row_id) if row_id is not None else None
    if row is None:
        row = spec.model()
        session.add(row)
    _apply_data_to_row(session, spec, row, raw_data)
    session.flush()


def _apply_data_to_row(session: Session, spec: RepairTableSpec, row: Any, raw_data: dict[str, Any]) -> None:
    parsed = {}
    for field in spec.fields:
        if not field.editable:
            continue
        raw_value = raw_data.get(field.name, "")
        parsed[field.name] = parse_field_value(spec, field, raw_value)
    if spec.key == "students":
        _apply_student_data(session, row, parsed)
    elif spec.key == "payments":
        _apply_payment_data(session, row, parsed)
    elif spec.key == "fees":
        _apply_fee_data(session, row, parsed)
    elif spec.key == "users":
        _apply_user_data(session, row, parsed)
    elif spec.key == "courses":
        _apply_course_data(row, parsed)
    elif spec.key == "sections":
        _apply_section_data(session, row, parsed)
    else:
        raise DataRepairError("unsupported_table")


def parse_field_value(spec: RepairTableSpec, field: RepairField, raw_value: Any) -> Any:
    value = str(raw_value or "").strip()
    if field.required and not value:
        raise DataRepairError("missing_required_field")
    if field.input_type == "date":
        return optional_date(value or None) if value else None
    if field.input_type == "number":
        if value == "":
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise DataRepairError("invalid_numeric_value") from exc
    if field.name.endswith("_id") or field.name == "service_id":
        return optional_int(value)
    return value


def _apply_student_data(session: Session, row: Student, parsed: dict[str, Any]) -> None:
    if parsed["status"] not in STUDENT_STATUSES:
        raise DataRepairError("invalid_status")
    course_id = parsed["course_id"]
    section_id = parsed["section_id"]
    hostel_id = parsed["hostel_id"]
    transport_id = parsed["transport_id"]
    if course_id is None or session.get(Course, course_id) is None:
        raise DataRepairError("invalid_lookup")
    section = session.get(Section, section_id) if section_id is not None else None
    if section_id is not None and (section is None or section.course_id != course_id):
        raise DataRepairError("invalid_lookup")
    if hostel_id is not None and session.get(Hostel, hostel_id) is None:
        raise DataRepairError("invalid_lookup")
    if transport_id is not None and session.get(TransportRoute, transport_id) is None:
        raise DataRepairError("invalid_lookup")
    for key, value in parsed.items():
        setattr(row, key, value if value is not None else "")
    row.section_id = section_id
    row.hostel_id = hostel_id
    row.transport_id = transport_id
    _sync_payments_for_student(row)


def _sync_payments_for_student(student: Student) -> None:
    for payment in student.payments:
        payment.student_code = str(student.student_code or "")
        payment.student_name = str(student.full_name or "")
        payment.parent_name = str(student.parent_name or "")


def _apply_payment_data(session: Session, row: Payment, parsed: dict[str, Any]) -> None:
    student = session.get(Student, parsed["student_id"]) if parsed["student_id"] is not None else None
    service_type = str(parsed["service_type"] or "").lower()
    if service_type not in PAYMENT_SERVICE_TYPES:
        raise DataRepairError("invalid_service_type")
    amount = parsed["amount"]
    if amount is None or amount <= 0:
        raise DataRepairError("invalid_numeric_value")
    if parsed["method"] not in PAYMENT_METHODS:
        raise DataRepairError("invalid_method")
    if parsed["status"] not in PAYMENT_STATUSES:
        raise DataRepairError("invalid_status")
    service_id = parsed["service_id"]
    if service_id is not None and not validate_service_for_type(session, service_type, service_id, student=student):
        raise DataRepairError("invalid_lookup")

    row.student = student
    row.service_type = service_type
    row.service_id = service_id
    row.service_name = (
        resolve_service_name(session, service_type, service_id, student)
        if service_id is not None
        else str(parsed["service_name"] or "").strip()
    )
    row.amount = float(amount)
    row.payment_date = parsed["payment_date"] or date.today()
    row.method = parsed["method"]
    row.reference = str(parsed["reference"] or "").strip()
    row.notes = str(parsed["notes"] or "")
    row.status = parsed["status"]
    apply_receipt_snapshot(session, row, student)


def _apply_fee_data(session: Session, row: Fee, parsed: dict[str, Any]) -> None:
    amount = non_negative_float(str(parsed["amount"]))
    if not parsed["name"]:
        raise DataRepairError("missing_required_field")
    if parsed["category"] not in FEE_CATEGORIES:
        raise DataRepairError("invalid_category")
    if amount is None:
        raise DataRepairError("invalid_numeric_value")
    if parsed["frequency"] not in FEE_FREQUENCIES:
        raise DataRepairError("invalid_frequency")
    if parsed["status"] not in CATALOG_STATUSES:
        raise DataRepairError("invalid_status")
    if parsed["target_type"] not in FEE_TARGET_TYPES:
        raise DataRepairError("invalid_lookup")
    target_type, target_id, valid_target = _resolve_repair_fee_target(
        session,
        parsed["target_type"],
        parsed["target_id"],
    )
    if not valid_target:
        raise DataRepairError("invalid_lookup")
    row.name = parsed["name"]
    row.category = parsed["category"]
    row.amount = amount
    row.frequency = parsed["frequency"]
    row.status = parsed["status"]
    row.target_type = target_type
    row.target_id = target_id
    row.description = str(parsed["description"] or "")


def _resolve_repair_fee_target(session: Session, target_type: str, target_id: int | None) -> tuple[str, int | None, bool]:
    normalized = str(target_type or "").strip()
    if normalized == "General":
        return normalized, None, True
    if normalized == "Course":
        return normalized, target_id, target_id is not None and session.get(Course, target_id) is not None
    if normalized == "Hostel":
        return normalized, target_id, target_id is not None and session.get(Hostel, target_id) is not None
    if normalized == "Transport":
        return (
            normalized,
            target_id,
            target_id is not None and session.get(TransportRoute, target_id) is not None,
        )
    return normalized, None, False


def _apply_user_data(session: Session, row: User, parsed: dict[str, Any]) -> None:
    if row.role == "SuperAdmin":
        raise DataRepairError("record_not_found")
    if not parsed["full_name"] or not parsed["username"] or not parsed["email"]:
        raise DataRepairError("missing_required_field")
    if parsed["role"] not in USER_VISIBLE_ROLES:
        raise DataRepairError("invalid_role")
    if parsed["status"] not in STUDENT_STATUSES:
        raise DataRepairError("invalid_status")
    active_admin_count = session.query(User).filter(User.role == "Admin", User.status == "Active").count()
    if (
        row.role == "Admin"
        and row.status == "Active"
        and (parsed["role"] != "Admin" or parsed["status"] != "Active")
        and active_admin_count <= 1
    ):
        raise DataRepairError("last_admin")
    row.full_name = parsed["full_name"]
    row.username = parsed["username"].lower()
    row.email = parsed["email"].lower()
    row.role = parsed["role"]
    row.status = parsed["status"]
    row.created_on = parsed["created_on"] or row.created_on or date.today()


def _apply_course_data(row: Course, parsed: dict[str, Any]) -> None:
    amount = non_negative_float(str(parsed["fees"]))
    if not parsed["name"] or not parsed["code"]:
        raise DataRepairError("missing_required_field")
    if amount is None:
        raise DataRepairError("invalid_numeric_value")
    if parsed["frequency"] not in ("Monthly", "Quarterly", "Half-Yearly", "Yearly"):
        raise DataRepairError("invalid_frequency")
    if parsed["status"] not in CATALOG_STATUSES:
        raise DataRepairError("invalid_status")
    row.name = parsed["name"]
    row.code = parsed["code"]
    row.fees = amount
    row.frequency = parsed["frequency"]
    row.status = parsed["status"]
    row.description = str(parsed["description"] or "")


def _apply_section_data(session: Session, row: Section, parsed: dict[str, Any]) -> None:
    course_id = parsed["course_id"]
    if course_id is None or session.get(Course, course_id) is None:
        raise DataRepairError("invalid_lookup")
    if not parsed["name"]:
        raise DataRepairError("missing_required_field")
    if parsed["status"] not in CATALOG_STATUSES:
        raise DataRepairError("invalid_status")
    row.course_id = course_id
    row.name = parsed["name"]
    row.code = str(parsed["code"] or "")
    row.class_teacher = str(parsed["class_teacher"] or "")
    row.room_name = str(parsed["room_name"] or "")
    row.status = parsed["status"]
    row.description = str(parsed["description"] or "")
