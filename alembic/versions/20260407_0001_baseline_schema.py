"""Baseline schema for the current Pinaki data model.

This revision represents the schema that new databases should start from
when using Alembic. Existing deployed databases that were created through
the app's built-in migration runner should be stamped to this revision
instead of replaying it.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260407_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("fees", sa.Float(), nullable=False),
        sa.Column("frequency", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "fees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("frequency", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "hostels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("hostel_type", sa.String(length=40), nullable=False),
        sa.Column("rooms", sa.Integer(), nullable=False),
        sa.Column("fee_amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("school_name", sa.String(length=120), nullable=False),
        sa.Column("school_email", sa.String(length=120), nullable=False),
        sa.Column("phone_number", sa.String(length=40), nullable=False),
        sa.Column("logo_url", sa.String(length=255), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("academic_year", sa.String(length=40), nullable=False),
        sa.Column("financial_year", sa.String(length=40), nullable=False),
        sa.Column("fee_frequency", sa.String(length=30), nullable=False),
        sa.Column("currency", sa.String(length=30), nullable=False),
        sa.Column("timezone", sa.String(length=60), nullable=False),
        sa.Column("developer_name", sa.String(length=120), nullable=False),
        sa.Column("developer_email", sa.String(length=120), nullable=False),
        sa.Column("developer_phone", sa.String(length=40), nullable=False),
        sa.Column("setup_completed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transport_routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("route_name", sa.String(length=120), nullable=False),
        sa.Column("pickup_points", sa.Text(), nullable=False),
        sa.Column("vehicle_no", sa.String(length=40), nullable=False),
        sa.Column("driver_name", sa.String(length=120), nullable=False),
        sa.Column("driver_phone", sa.String(length=30), nullable=False),
        sa.Column("fee_amount", sa.Float(), nullable=False),
        sa.Column("frequency", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("username", sa.String(length=60), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_on", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("class_teacher", sa.String(length=120), nullable=False),
        sa.Column("room_name", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "students",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_code", sa.String(length=30), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("parent_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("section_id", sa.Integer(), nullable=True),
        sa.Column("hostel_id", sa.Integer(), nullable=True),
        sa.Column("transport_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["hostel_id"], ["hostels.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.ForeignKeyConstraint(["transport_id"], ["transport_routes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_code"),
    )
    op.create_index("ix_students_status_full_name", "students", ["status", "full_name"], unique=False)
    op.create_index("ix_students_status_id", "students", ["status", "id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=True),
        sa.Column("student_code", sa.String(length=30), nullable=False),
        sa.Column("student_name", sa.String(length=120), nullable=False),
        sa.Column("parent_name", sa.String(length=120), nullable=False),
        sa.Column("snapshot_total_fees", sa.Float(), nullable=False),
        sa.Column("snapshot_paid_amount", sa.Float(), nullable=False),
        sa.Column("snapshot_current_cycle_amount", sa.Float(), nullable=False),
        sa.Column("snapshot_previous_pending_amount", sa.Float(), nullable=False),
        sa.Column("snapshot_remaining_balance", sa.Float(), nullable=False),
        sa.Column("service_type", sa.String(length=30), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.Column("reference", sa.String(length=60), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payments_service_type_payment_date",
        "payments",
        ["service_type", "payment_date", "id"],
        unique=False,
    )
    op.create_index(
        "ix_payments_status_payment_date",
        "payments",
        ["status", "payment_date", "id"],
        unique=False,
    )
    op.create_index(
        "ix_payments_student_payment_date",
        "payments",
        ["student_id", "payment_date", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payments_student_payment_date", table_name="payments")
    op.drop_index("ix_payments_status_payment_date", table_name="payments")
    op.drop_index("ix_payments_service_type_payment_date", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_students_status_id", table_name="students")
    op.drop_index("ix_students_status_full_name", table_name="students")
    op.drop_table("students")
    op.drop_table("sections")
    op.drop_table("users")
    op.drop_table("transport_routes")
    op.drop_table("settings")
    op.drop_table("hostels")
    op.drop_table("fees")
    op.drop_table("courses")
