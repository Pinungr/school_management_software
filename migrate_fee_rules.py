from __future__ import annotations

from sqlalchemy import func, select

from school_admin.database import SessionLocal
from school_admin.models import Fee


def main() -> None:
    with SessionLocal() as session:
        admission_fees = session.scalars(select(Fee).where(func.lower(Fee.category) == "admission")).all()
        recurring_fees = session.scalars(select(Fee).where(func.lower(Fee.category) != "admission")).all()

        admission_updates = 0
        recurring_updates = 0

        for fee in admission_fees:
            if str(fee.frequency or "").strip() != "One Time":
                fee.frequency = "One Time"
                admission_updates += 1

        for fee in recurring_fees:
            if not str(fee.frequency or "").strip():
                fee.frequency = "Monthly"
                recurring_updates += 1

        session.commit()

    print(
        "Fee normalization complete.",
        f"Admission updated: {admission_updates}.",
        f"Recurring defaulted: {recurring_updates}.",
    )


if __name__ == "__main__":
    main()
