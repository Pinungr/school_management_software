from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session


MigrationStep = tuple[str, Callable[[Session], None]]


def table_exists(session: Session, table_name: str) -> bool:
    return bool(
        session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).first()
    )


def column_names(session: Session, table_name: str) -> set[str]:
    if not table_exists(session, table_name):
        return set()
    return {
        row[1] for row in session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    }


def index_rows(session: Session, table_name: str) -> list[tuple]:
    if not table_exists(session, table_name):
        return []
    return session.execute(text(f"PRAGMA index_list({table_name})")).fetchall()


def index_columns(session: Session, index_name: str) -> list[str]:
    return [row[2] for row in session.execute(text(f"PRAGMA index_info({index_name})")).fetchall()]


def has_index(session: Session, table_name: str, index_name: str) -> bool:
    return any(row[1] == index_name for row in index_rows(session, table_name))


def has_unique_index_for_column(session: Session, table_name: str, column_name: str) -> bool:
    for row in index_rows(session, table_name):
        index_name = row[1]
        is_unique = bool(row[2])
        if is_unique and index_columns(session, index_name) == [column_name]:
            return True
    return False


def ensure_migrations_table(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    session.commit()


def migration_users_add_username(session: Session) -> None:
    columns = column_names(session, "users")
    if columns and "username" not in columns:
        session.execute(text("ALTER TABLE users ADD COLUMN username TEXT"))


def migration_users_backfill_username_and_unique_index(session: Session) -> None:
    if "username" not in column_names(session, "users"):
        return

    users = session.execute(
        text("SELECT id, username, email FROM users ORDER BY id")
    ).fetchall()
    used_usernames: set[str] = set()

    for user_id, username, email in users:
        candidate = (username or "").strip().lower()
        if not candidate:
            email_value = (email or "").strip().lower()
            candidate = email_value.split("@", 1)[0] if "@" in email_value else f"user{user_id}"
        candidate = candidate or f"user{user_id}"

        base_candidate = candidate
        suffix = 1
        while candidate in used_usernames:
            suffix += 1
            candidate = f"{base_candidate}{suffix}"

        used_usernames.add(candidate)
        if candidate != (username or "").strip().lower():
            session.execute(
                text("UPDATE users SET username = :username WHERE id = :user_id"),
                {"username": candidate, "user_id": user_id},
            )

    if not has_unique_index_for_column(session, "users", "username"):
        session.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_unique ON users (username)")
        )


def migration_settings_add_metadata_columns(session: Session) -> None:
    columns = column_names(session, "settings")
    if not columns:
        return
    for column_name, column_type in (
        ("developer_name", "TEXT"),
        ("developer_email", "TEXT"),
        ("developer_phone", "TEXT"),
    ):
        if column_name not in columns:
            session.execute(text(f"ALTER TABLE settings ADD COLUMN {column_name} {column_type}"))


def migration_settings_add_setup_completed(session: Session) -> None:
    columns = column_names(session, "settings")
    if not columns:
        return
    if "setup_completed" not in columns:
        session.execute(text("ALTER TABLE settings ADD COLUMN setup_completed INTEGER DEFAULT 0"))
    session.execute(
        text("UPDATE settings SET setup_completed = COALESCE(setup_completed, 0)")
    )


def migration_payments_add_service_name(session: Session) -> None:
    columns = column_names(session, "payments")
    if not columns:
        return
    if "service_name" not in columns:
        session.execute(text("ALTER TABLE payments ADD COLUMN service_name TEXT DEFAULT ''"))


def migration_payments_backfill_service_name(session: Session) -> None:
    columns = column_names(session, "payments")
    if not columns or "service_name" not in columns:
        return

    payments = session.execute(
        text(
            """
            SELECT id, service_type, service_id, service_name
            FROM payments
            ORDER BY id
            """
        )
    ).fetchall()

    for payment_id, service_type, service_id, service_name in payments:
        if str(service_name or "").strip():
            continue

        resolved_name = ""
        if service_id is not None:
            if service_type == "course" and table_exists(session, "courses"):
                row = session.execute(
                    text("SELECT name FROM courses WHERE id = :service_id"),
                    {"service_id": service_id},
                ).first()
                resolved_name = str(row[0]) if row else ""
            elif service_type == "hostel" and table_exists(session, "hostels"):
                row = session.execute(
                    text("SELECT name FROM hostels WHERE id = :service_id"),
                    {"service_id": service_id},
                ).first()
                resolved_name = str(row[0]) if row else ""
            elif service_type == "transport" and table_exists(session, "transport_routes"):
                row = session.execute(
                    text("SELECT route_name FROM transport_routes WHERE id = :service_id"),
                    {"service_id": service_id},
                ).first()
                resolved_name = str(row[0]) if row else ""

        session.execute(
            text("UPDATE payments SET service_name = :service_name WHERE id = :payment_id"),
            {"service_name": resolved_name, "payment_id": payment_id},
        )


def migration_settings_clear_placeholder_developer_info(session: Session) -> None:
    columns = column_names(session, "settings")
    required_columns = {"developer_name", "developer_email", "developer_phone", "setup_completed"}
    if not columns or not required_columns.issubset(columns):
        return

    session.execute(
        text(
            """
            UPDATE settings
            SET developer_name = '',
                developer_email = '',
                developer_phone = ''
            WHERE setup_completed = 0
              AND developer_name = 'Pinaki Sarangi'
              AND developer_email = 'pinungr@gmail.com'
              AND developer_phone = '7751952860'
            """
        )
    )


def migration_create_fees_table(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS fees (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Other',
                amount REAL NOT NULL DEFAULT 0,
                frequency TEXT NOT NULL DEFAULT 'One Time',
                status TEXT NOT NULL DEFAULT 'Active',
                target_type TEXT NOT NULL DEFAULT 'General',
                target_id INTEGER,
                description TEXT NOT NULL DEFAULT ''
            )
            """
        )
    )


def migration_backfill_fees_from_legacy_catalog(session: Session) -> None:
    if not table_exists(session, "fees"):
        return

    if table_exists(session, "courses"):
        courses = session.execute(
            text("SELECT id, name, fees, frequency, status, description FROM courses ORDER BY id")
        ).fetchall()
        for course_id, name, fees, frequency, status, description in courses:
            existing = session.execute(
                text(
                    """
                    SELECT id
                    FROM fees
                    WHERE category = 'Course'
                      AND target_type = 'Course'
                      AND target_id = :target_id
                    """
                ),
                {"target_id": course_id},
            ).first()
            if existing:
                continue
            session.execute(
                text(
                    """
                    INSERT INTO fees (
                        name, category, amount, frequency, status, target_type, target_id, description
                    ) VALUES (
                        :name, 'Course', :amount, :frequency, :status, 'Course', :target_id, :description
                    )
                    """
                ),
                {
                    "name": f"{name} Course Fee",
                    "amount": float(fees or 0),
                    "frequency": str(frequency or "Monthly"),
                    "status": str(status or "Active"),
                    "target_id": course_id,
                    "description": str(description or ""),
                },
            )

    if table_exists(session, "hostels"):
        hostels = session.execute(
            text("SELECT id, name, fee_amount, status, description FROM hostels ORDER BY id")
        ).fetchall()
        for hostel_id, name, amount, status, description in hostels:
            existing = session.execute(
                text(
                    """
                    SELECT id
                    FROM fees
                    WHERE category = 'Hostel'
                      AND target_type = 'Hostel'
                      AND target_id = :target_id
                    """
                ),
                {"target_id": hostel_id},
            ).first()
            if existing:
                continue
            session.execute(
                text(
                    """
                    INSERT INTO fees (
                        name, category, amount, frequency, status, target_type, target_id, description
                    ) VALUES (
                        :name, 'Hostel', :amount, 'Monthly', :status, 'Hostel', :target_id, :description
                    )
                    """
                ),
                {
                    "name": f"{name} Hostel Fee",
                    "amount": float(amount or 0),
                    "status": str(status or "Active"),
                    "target_id": hostel_id,
                    "description": str(description or ""),
                },
            )

    if table_exists(session, "transport_routes"):
        routes = session.execute(
            text(
                "SELECT id, route_name, fee_amount, frequency, status, pickup_points FROM transport_routes ORDER BY id"
            )
        ).fetchall()
        for route_id, route_name, amount, frequency, status, pickup_points in routes:
            existing = session.execute(
                text(
                    """
                    SELECT id
                    FROM fees
                    WHERE category = 'Transport'
                      AND target_type = 'Transport'
                      AND target_id = :target_id
                    """
                ),
                {"target_id": route_id},
            ).first()
            if existing:
                continue
            session.execute(
                text(
                    """
                    INSERT INTO fees (
                        name, category, amount, frequency, status, target_type, target_id, description
                    ) VALUES (
                        :name, 'Transport', :amount, :frequency, :status, 'Transport', :target_id, :description
                    )
                    """
                ),
                {
                    "name": f"{route_name} Transport Fee",
                    "amount": float(amount or 0),
                    "frequency": str(frequency or "Monthly"),
                    "status": str(status or "Active"),
                    "target_id": route_id,
                    "description": str(pickup_points or ""),
                },
            )


def migration_payments_relink_legacy_services_to_fees(session: Session) -> None:
    if not table_exists(session, "payments") or not table_exists(session, "fees"):
        return

    mappings = {
        "course": ("Course", "Course"),
        "hostel": ("Hostel", "Hostel"),
        "transport": ("Transport", "Transport"),
    }
    payments = session.execute(
        text("SELECT id, service_type, service_id FROM payments WHERE service_id IS NOT NULL ORDER BY id")
    ).fetchall()

    for payment_id, service_type, service_id in payments:
        mapping = mappings.get(str(service_type or "").strip().lower())
        if not mapping:
            continue
        category, target_type = mapping
        fee_row = session.execute(
            text(
                """
                SELECT id
                FROM fees
                WHERE category = :category
                  AND target_type = :target_type
                  AND target_id = :target_id
                ORDER BY id
                LIMIT 1
                """
            ),
            {
                "category": category,
                "target_type": target_type,
                "target_id": service_id,
            },
        ).first()
        if not fee_row:
            continue
        session.execute(
            text("UPDATE payments SET service_id = :fee_id WHERE id = :payment_id"),
            {"fee_id": fee_row[0], "payment_id": payment_id},
        )


def migration_transport_routes_add_vehicle_and_driver_fields(session: Session) -> None:
    columns = column_names(session, "transport_routes")
    if not columns:
        return
    for column_name, column_sql in (
        ("vehicle_no", "TEXT DEFAULT ''"),
        ("driver_name", "TEXT DEFAULT ''"),
        ("driver_phone", "TEXT DEFAULT ''"),
    ):
        if column_name not in columns:
            session.execute(
                text(f"ALTER TABLE transport_routes ADD COLUMN {column_name} {column_sql}")
            )


def migration_create_sections_table(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY,
                course_id INTEGER NOT NULL REFERENCES courses(id),
                name TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                class_teacher TEXT NOT NULL DEFAULT '',
                room_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active',
                description TEXT NOT NULL DEFAULT ''
            )
            """
        )
    )


def migration_students_add_section_id(session: Session) -> None:
    columns = column_names(session, "students")
    if not columns:
        return
    if "section_id" not in columns:
        session.execute(text("ALTER TABLE students ADD COLUMN section_id INTEGER REFERENCES sections(id)"))


def migration_payments_add_student_snapshot_columns(session: Session) -> None:
    columns = column_names(session, "payments")
    if not columns:
        return
    for column_name, column_sql in (
        ("student_code", "TEXT DEFAULT ''"),
        ("student_name", "TEXT DEFAULT ''"),
        ("parent_name", "TEXT DEFAULT ''"),
    ):
        if column_name not in columns:
            session.execute(text(f"ALTER TABLE payments ADD COLUMN {column_name} {column_sql}"))


def migration_payments_backfill_student_snapshots(session: Session) -> None:
    columns = column_names(session, "payments")
    required_columns = {"student_id", "student_code", "student_name", "parent_name"}
    if not columns or not required_columns.issubset(columns) or not table_exists(session, "students"):
        return

    payments = session.execute(
        text(
            """
            SELECT id, student_id, student_code, student_name, parent_name
            FROM payments
            ORDER BY id
            """
        )
    ).fetchall()

    for payment_id, student_id, student_code, student_name, parent_name in payments:
        has_snapshot = any(str(value or "").strip() for value in (student_code, student_name, parent_name))
        if has_snapshot or student_id is None:
            continue
        student = session.execute(
            text(
                """
                SELECT student_code, full_name, parent_name
                FROM students
                WHERE id = :student_id
                """
            ),
            {"student_id": student_id},
        ).first()
        if not student:
            continue
        session.execute(
            text(
                """
                UPDATE payments
                SET student_code = :student_code,
                    student_name = :student_name,
                    parent_name = :parent_name
                WHERE id = :payment_id
                """
            ),
            {
                "student_code": str(student[0] or ""),
                "student_name": str(student[1] or ""),
                "parent_name": str(student[2] or ""),
                "payment_id": payment_id,
            },
        )


def migration_payments_make_student_optional(session: Session) -> None:
    columns = column_names(session, "payments")
    required_columns = {
        "id",
        "student_id",
        "student_code",
        "student_name",
        "parent_name",
        "service_type",
        "service_id",
        "service_name",
        "amount",
        "payment_date",
        "method",
        "reference",
        "notes",
        "status",
    }
    if not columns or not required_columns.issubset(columns):
        return

    table_sql_row = session.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='payments'")
    ).first()
    table_sql = str(table_sql_row[0] or "").lower() if table_sql_row else ""
    if "student_id integer not null" not in table_sql:
        return

    session.execute(text("PRAGMA foreign_keys=OFF"))
    session.execute(
        text(
            """
            CREATE TABLE payments_new (
                id INTEGER PRIMARY KEY,
                student_id INTEGER REFERENCES students(id),
                student_code TEXT DEFAULT '',
                student_name TEXT DEFAULT '',
                parent_name TEXT DEFAULT '',
                service_type TEXT NOT NULL DEFAULT 'course',
                service_id INTEGER,
                service_name TEXT DEFAULT '',
                amount REAL NOT NULL DEFAULT 0,
                payment_date DATE NOT NULL,
                method TEXT NOT NULL DEFAULT 'Cash',
                reference TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Paid'
            )
            """
        )
    )
    session.execute(
        text(
            """
            INSERT INTO payments_new (
                id, student_id, student_code, student_name, parent_name, service_type,
                service_id, service_name, amount, payment_date, method, reference, notes, status
            )
            SELECT
                id, student_id, student_code, student_name, parent_name, service_type,
                service_id, service_name, amount, payment_date, method, reference, notes, status
            FROM payments
            """
        )
    )
    session.execute(text("DROP TABLE payments"))
    session.execute(text("ALTER TABLE payments_new RENAME TO payments"))
    session.execute(text("PRAGMA foreign_keys=ON"))


def migration_payments_add_receipt_snapshot_columns(session: Session) -> None:
    columns = column_names(session, "payments")
    if not columns:
        return
    for column_name in (
        "snapshot_total_fees",
        "snapshot_paid_amount",
        "snapshot_current_cycle_amount",
        "snapshot_previous_pending_amount",
        "snapshot_remaining_balance",
    ):
        if column_name not in columns:
            session.execute(text(f"ALTER TABLE payments ADD COLUMN {column_name} REAL DEFAULT 0"))


def migration_payments_backfill_receipt_snapshots(session: Session) -> None:
    columns = column_names(session, "payments")
    required_columns = {
        "id",
        "student_id",
        "amount",
        "snapshot_total_fees",
        "snapshot_paid_amount",
        "snapshot_current_cycle_amount",
        "snapshot_previous_pending_amount",
        "snapshot_remaining_balance",
    }
    if not columns or not required_columns.issubset(columns):
        return

    payments = session.execute(
        text(
            """
            SELECT
                id,
                student_id,
                amount,
                snapshot_total_fees,
                snapshot_paid_amount,
                snapshot_current_cycle_amount,
                snapshot_previous_pending_amount,
                snapshot_remaining_balance
            FROM payments
            ORDER BY id
            """
        )
    ).fetchall()

    for (
        payment_id,
        student_id,
        amount,
        snapshot_total_fees,
        snapshot_paid_amount,
        snapshot_current_cycle_amount,
        snapshot_previous_pending_amount,
        snapshot_remaining_balance,
    ) in payments:
        has_snapshot = any(
            float(value or 0) != 0
            for value in (
                snapshot_total_fees,
                snapshot_paid_amount,
                snapshot_current_cycle_amount,
                snapshot_previous_pending_amount,
                snapshot_remaining_balance,
            )
        )
        if has_snapshot:
            continue

        paid_amount = float(amount or 0)
        session.execute(
            text(
                """
                UPDATE payments
                SET snapshot_paid_amount = :paid_amount
                WHERE id = :payment_id
                """
            ),
            {
                "paid_amount": paid_amount,
                "payment_id": payment_id,
            },
        )


def migration_create_large_dataset_indexes(session: Session) -> None:
    indexes_to_create = (
        (
            "students",
            "ix_students_status_id",
            "CREATE INDEX IF NOT EXISTS ix_students_status_id ON students (status, id)",
        ),
        (
            "students",
            "ix_students_status_full_name",
            "CREATE INDEX IF NOT EXISTS ix_students_status_full_name ON students (status, full_name)",
        ),
        (
            "payments",
            "ix_payments_status_payment_date",
            "CREATE INDEX IF NOT EXISTS ix_payments_status_payment_date ON payments (status, payment_date, id)",
        ),
        (
            "payments",
            "ix_payments_student_payment_date",
            "CREATE INDEX IF NOT EXISTS ix_payments_student_payment_date ON payments (student_id, payment_date, id)",
        ),
        (
            "payments",
            "ix_payments_service_type_payment_date",
            "CREATE INDEX IF NOT EXISTS ix_payments_service_type_payment_date ON payments (service_type, payment_date, id)",
        ),
    )

    for table_name, index_name, sql in indexes_to_create:
        if not table_exists(session, table_name) or has_index(session, table_name, index_name):
            continue
        session.execute(text(sql))


MIGRATIONS: list[MigrationStep] = [
    ("20260405_users_add_username", migration_users_add_username),
    ("20260405_users_backfill_username_and_unique_index", migration_users_backfill_username_and_unique_index),
    ("20260405_settings_add_metadata_columns", migration_settings_add_metadata_columns),
    ("20260405_settings_add_setup_completed", migration_settings_add_setup_completed),
    ("20260405_payments_add_service_name", migration_payments_add_service_name),
    ("20260405_payments_backfill_service_name", migration_payments_backfill_service_name),
    ("20260405_settings_clear_placeholder_developer_info", migration_settings_clear_placeholder_developer_info),
    ("20260406_create_fees_table", migration_create_fees_table),
    ("20260406_backfill_fees_from_legacy_catalog", migration_backfill_fees_from_legacy_catalog),
    ("20260406_payments_relink_legacy_services_to_fees", migration_payments_relink_legacy_services_to_fees),
    ("20260406_transport_routes_add_vehicle_and_driver_fields", migration_transport_routes_add_vehicle_and_driver_fields),
    ("20260406_create_sections_table", migration_create_sections_table),
    ("20260406_students_add_section_id", migration_students_add_section_id),
    ("20260407_payments_add_student_snapshot_columns", migration_payments_add_student_snapshot_columns),
    ("20260407_payments_backfill_student_snapshots", migration_payments_backfill_student_snapshots),
    ("20260407_payments_make_student_optional", migration_payments_make_student_optional),
    ("20260407_payments_add_receipt_snapshot_columns", migration_payments_add_receipt_snapshot_columns),
    ("20260407_payments_backfill_receipt_snapshots", migration_payments_backfill_receipt_snapshots),
    ("20260407_create_large_dataset_indexes", migration_create_large_dataset_indexes),
]


def run_migrations(session: Session) -> None:
    ensure_migrations_table(session)
    applied_ids = {
        row[0] for row in session.execute(text("SELECT id FROM schema_migrations")).fetchall()
    }

    for migration_id, migration_func in MIGRATIONS:
        if migration_id in applied_ids:
            continue
        migration_func(session)
        session.execute(
            text("INSERT INTO schema_migrations (id) VALUES (:migration_id)"),
            {"migration_id": migration_id},
        )
        session.commit()
    session.execute(text("PRAGMA foreign_keys=ON"))
    session.commit()
