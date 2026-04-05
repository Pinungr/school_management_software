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


MIGRATIONS: list[MigrationStep] = [
    ("20260405_users_add_username", migration_users_add_username),
    ("20260405_users_backfill_username_and_unique_index", migration_users_backfill_username_and_unique_index),
    ("20260405_settings_add_metadata_columns", migration_settings_add_metadata_columns),
    ("20260405_settings_add_setup_completed", migration_settings_add_setup_completed),
    ("20260405_payments_add_service_name", migration_payments_add_service_name),
    ("20260405_payments_backfill_service_name", migration_payments_backfill_service_name),
    ("20260405_settings_clear_placeholder_developer_info", migration_settings_clear_placeholder_developer_info),
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
