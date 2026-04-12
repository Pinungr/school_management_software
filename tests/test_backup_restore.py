from __future__ import annotations

from datetime import date
import io
from pathlib import Path
import shutil
import uuid
import zipfile

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import school_admin.backup_restore as backup_restore
from school_admin.database import Base
from school_admin.migrations import run_migrations
from school_admin.models import Payment, Setting, Student
from school_admin.seed import seed_database


def test_backup_export_creates_single_importable_file(monkeypatch):
    temp_root = Path("build").resolve() / f"backup-restore-test-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    test_engine = None
    try:
        app_data_dir = temp_root / "appdata"
        data_dir = app_data_dir / "data"
        uploads_dir = app_data_dir / "uploads"
        database_path = data_dir / "school.db"

        data_dir.mkdir(parents=True, exist_ok=True)
        uploads_dir.mkdir(parents=True, exist_ok=True)

        test_engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

        Base.metadata.create_all(bind=test_engine)
        with TestSessionLocal() as session:
            run_migrations(session)
            seed_database(session)

            settings = session.get(Setting, 1)
            assert settings is not None
            settings.school_name = "Original School"
            settings.setup_completed = True

            student = Student(
                student_code="STU-ROUND-001",
                full_name="Original Student",
                email="student@example.com",
                phone="9999999999",
            )
            session.add(student)
            session.flush()
            session.add(
                Payment(
                    student_id=student.id,
                    student_code=student.student_code,
                    student_name=student.full_name,
                    amount=1250,
                    payment_date=date(2026, 4, 7),
                    service_type="course",
                    service_name="Course Fee",
                    method="Cash",
                    status="Paid",
                )
            )
            session.commit()

        original_upload = uploads_dir / "logo.txt"
        original_upload.write_text("original upload", encoding="utf-8")

        monkeypatch.setattr(backup_restore, "APP_DATA_DIR", app_data_dir)
        monkeypatch.setattr(backup_restore, "UPLOADS_DIR", uploads_dir)
        monkeypatch.setattr(backup_restore, "DATABASE_PATH", database_path)
        monkeypatch.setattr(backup_restore, "engine", test_engine)
        monkeypatch.setattr(backup_restore, "SessionLocal", TestSessionLocal)

        backup_bytes, filename = backup_restore.create_backup_archive()

        assert filename.endswith(backup_restore.BACKUP_EXTENSION)
        assert zipfile.is_zipfile(io.BytesIO(backup_bytes))

        with zipfile.ZipFile(io.BytesIO(backup_bytes)) as archive:
            assert backup_restore.BACKUP_METADATA_PATH in archive.namelist()
            assert backup_restore.BACKUP_DATABASE_PATH in archive.namelist()

        with TestSessionLocal() as session:
            settings = session.get(Setting, 1)
            assert settings is not None
            settings.school_name = "Changed School"
            student = session.scalar(select(Student).where(Student.student_code == "STU-ROUND-001"))
            assert student is not None
            student.full_name = "Changed Student"
            session.commit()

        original_upload.write_text("changed upload", encoding="utf-8")
        (uploads_dir / "extra.txt").write_text("delete me", encoding="utf-8")

        backup_restore.restore_backup_archive(backup_bytes)

        with TestSessionLocal() as session:
            settings = session.get(Setting, 1)
            assert settings is not None
            assert settings.school_name == "Original School"

            student = session.scalar(select(Student).where(Student.student_code == "STU-ROUND-001"))
            assert student is not None
            assert student.full_name == "Original Student"

            payment = session.scalar(select(Payment).where(Payment.student_code == "STU-ROUND-001"))
            assert payment is not None
            assert payment.amount == 1250

        assert original_upload.read_text(encoding="utf-8") == "original upload"
        assert not (uploads_dir / "extra.txt").exists()
    finally:
        if test_engine is not None:
            test_engine.dispose()
        shutil.rmtree(temp_root, ignore_errors=True)


def test_restore_valid_pinaki_backup_without_temp_directory(monkeypatch):
    temp_root = Path("data").resolve() / f"backup-direct-restore-test-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    test_engine = None
    try:
        app_data_dir = temp_root / "appdata"
        data_dir = app_data_dir / "data"
        uploads_dir = app_data_dir / "uploads"
        database_path = data_dir / "school.db"

        data_dir.mkdir(parents=True, exist_ok=True)
        uploads_dir.mkdir(parents=True, exist_ok=True)

        test_engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

        Base.metadata.create_all(bind=test_engine)
        with TestSessionLocal() as session:
            run_migrations(session)
            seed_database(session)
            settings = session.get(Setting, 1)
            assert settings is not None
            settings.school_name = "Restore Source School"
            student = Student(
                student_code="RESTORE-DIRECT-001",
                full_name="Restore Direct Student",
                email="restore.direct@example.com",
                phone="9999990000",
            )
            session.add(student)
            session.commit()

        monkeypatch.setattr(backup_restore, "APP_DATA_DIR", app_data_dir)
        monkeypatch.setattr(backup_restore, "UPLOADS_DIR", uploads_dir)
        monkeypatch.setattr(backup_restore, "DATABASE_PATH", database_path)
        monkeypatch.setattr(backup_restore, "engine", test_engine)
        monkeypatch.setattr(backup_restore, "SessionLocal", TestSessionLocal)

        backup_bytes, _ = backup_restore.create_backup_archive()

        with TestSessionLocal() as session:
            settings = session.get(Setting, 1)
            assert settings is not None
            settings.school_name = "Changed Before Restore"
            student = session.scalar(select(Student).where(Student.student_code == "RESTORE-DIRECT-001"))
            assert student is not None
            student.full_name = "Changed Before Restore"
            session.commit()

        backup_restore.restore_backup_archive(backup_bytes)

        with TestSessionLocal() as session:
            settings = session.get(Setting, 1)
            assert settings is not None
            assert settings.school_name == "Restore Source School"
            student = session.scalar(select(Student).where(Student.student_code == "RESTORE-DIRECT-001"))
            assert student is not None
            assert student.full_name == "Restore Direct Student"
    finally:
        if test_engine is not None:
            test_engine.dispose()
        shutil.rmtree(temp_root, ignore_errors=True)
