from __future__ import annotations

from contextlib import closing
import io
import json
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from time import sleep

from school_admin.database import APP_DATA_DIR, DATA_DIR, SessionLocal, UPLOADS_DIR, engine
from school_admin.migrations import run_migrations
from sqlalchemy.orm import close_all_sessions


BACKUP_EXTENSION = ".pinaki-backup"
BACKUP_FORMAT_VERSION = 1
BACKUP_METADATA_PATH = "metadata.json"
BACKUP_DATABASE_PATH = "data/school.db"
DATABASE_PATH = DATA_DIR / "school.db"


class BackupRestoreError(ValueError):
    pass


def create_backup_archive() -> tuple[bytes, str]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"pinaki-backup-{timestamp}{BACKUP_EXTENSION}"

    with closing(sqlite3.connect(str(DATABASE_PATH))) as source_connection:
        database_bytes = source_connection.serialize()

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            BACKUP_METADATA_PATH,
            json.dumps(
                {
                    "app_name": "Pinaki",
                    "format_version": BACKUP_FORMAT_VERSION,
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
        )
        archive.writestr(BACKUP_DATABASE_PATH, database_bytes)
        if UPLOADS_DIR.exists():
            for path in sorted(UPLOADS_DIR.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(APP_DATA_DIR).as_posix())
    return archive_buffer.getvalue(), filename


def restore_backup_archive(archive_bytes: bytes) -> None:
    if not archive_bytes:
        raise BackupRestoreError("missing_backup_file")

    try:
        archive_buffer = io.BytesIO(archive_bytes)
        if not zipfile.is_zipfile(archive_buffer):
            raise BackupRestoreError("invalid_backup_file")
        archive_buffer.seek(0)

        with zipfile.ZipFile(archive_buffer) as archive:
            members = archive.namelist()
            if BACKUP_METADATA_PATH not in members or BACKUP_DATABASE_PATH not in members:
                raise BackupRestoreError("invalid_backup_file")

            for member_name in members:
                _normalize_archive_member(member_name)

            metadata = json.loads(archive.read(BACKUP_METADATA_PATH).decode("utf-8"))
            if str(metadata.get("app_name", "")).strip() != "Pinaki":
                raise BackupRestoreError("invalid_backup_file")
            if int(metadata.get("format_version", 0)) > BACKUP_FORMAT_VERSION:
                raise BackupRestoreError("invalid_backup_file")

            restored_database_bytes = archive.read(BACKUP_DATABASE_PATH)
            _validate_pinaki_database(restored_database_bytes)
            upload_entries = [
                (
                    _normalize_archive_member(member_name),
                    archive.read(member_name),
                )
                for member_name in members
                if member_name.startswith("uploads/") and not member_name.endswith("/")
            ]

            close_all_sessions()
            engine.dispose()
            _restore_sqlite_database(restored_database_bytes, DATABASE_PATH)

            with SessionLocal() as session:
                run_migrations(session)

            _replace_uploads_from_archive(upload_entries, UPLOADS_DIR)
    except BackupRestoreError:
        raise
    except (OSError, sqlite3.Error, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise BackupRestoreError("invalid_backup_file") from exc


def _restore_sqlite_database(database_bytes: bytes, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(":memory:")) as source_connection:
        source_connection.deserialize(database_bytes)
        _restore_database_with_retries(source_connection, destination_path)
    _remove_sqlite_sidecar_files(destination_path)


def _restore_database_with_retries(source_connection: sqlite3.Connection, destination_path: Path) -> None:
    attempts = 10
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            # On Windows, we need to ensure we can actually open the destination
            with closing(sqlite3.connect(str(destination_path), timeout=30)) as destination_connection:
                destination_connection.execute("PRAGMA wal_checkpoint(FULL)")
                destination_connection.execute("PRAGMA journal_mode=DELETE")
                source_connection.backup(destination_connection)
                destination_connection.commit()
            return
        except sqlite3.OperationalError as exc:
            last_error = exc
            # Active readers/writers can briefly lock SQLite during restore.
            if "locked" in str(exc).lower() and attempt < attempts:
                sleep(0.3 * attempt)
                continue
            raise BackupRestoreError("database_is_locked_try_closing_app") from exc
    if last_error:
        raise last_error


def _validate_pinaki_database(database_bytes: bytes) -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(database_bytes)
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required_tables = {"settings", "users", "students", "payments"}
        if not required_tables.issubset(table_names):
            raise BackupRestoreError("invalid_backup_file")


def _normalize_archive_member(member_name: str) -> PurePosixPath:
    member_path = PurePosixPath(member_name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise BackupRestoreError("invalid_backup_file")
    return member_path


def _replace_uploads_from_archive(
    source_entries: list[tuple[PurePosixPath, bytes]],
    destination_dir: Path,
) -> None:
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_uploads_dir = destination_dir.parent / f".uploads-restore-{uuid.uuid4().hex}"
    previous_uploads_dir = destination_dir.parent / f".uploads-previous-{uuid.uuid4().hex}"
    temporary_uploads_dir.mkdir(parents=True, exist_ok=False)

    try:
        for relative_path, file_bytes in source_entries:
            destination_path = temporary_uploads_dir / Path(*relative_path.parts[1:])
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_bytes(file_bytes)

        if destination_dir.exists():
            destination_dir.rename(previous_uploads_dir)
        temporary_uploads_dir.rename(destination_dir)
    except Exception:
        if not destination_dir.exists() and previous_uploads_dir.exists():
            previous_uploads_dir.rename(destination_dir)
        raise
    finally:
        if temporary_uploads_dir.exists():
            shutil.rmtree(temporary_uploads_dir, ignore_errors=True)
        if previous_uploads_dir.exists():
            shutil.rmtree(previous_uploads_dir, ignore_errors=True)


def _remove_sqlite_sidecar_files(database_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        database_path.with_name(f"{database_path.name}{suffix}").unlink(missing_ok=True)
