from __future__ import annotations

from sqlalchemy import select

from school_admin.database import SessionLocal
from school_admin.models import Fee, FeeFrequency, FeeType, normalize_fee_frequency


def main() -> None:
    with SessionLocal() as session:
        admission_fees = session.scalars(select(Fee).where(Fee.type == FeeType.ADMISSION.value)).all()
        recurring_fees = session.scalars(select(Fee).where(Fee.type != FeeType.ADMISSION.value)).all()

        admission_updates = 0
        recurring_updates = 0

        for fee in admission_fees:
            if not fee.is_one_time or fee.frequency is not None:
                fee.is_one_time = True
                fee.frequency = None
                admission_updates += 1

        for fee in recurring_fees:
            if fee.type == FeeType.TUITION.value:
                if fee.is_one_time or fee.frequency != FeeFrequency.MONTHLY.value:
                    fee.is_one_time = False
                    fee.frequency = FeeFrequency.MONTHLY.value
                    recurring_updates += 1
                continue
            normalized_frequency = normalize_fee_frequency(fee.frequency)
            desired_frequency = normalized_frequency or FeeFrequency.MONTHLY.value
            if fee.is_one_time or fee.frequency != desired_frequency:
                fee.is_one_time = False
                fee.frequency = desired_frequency
                recurring_updates += 1

        session.commit()

    print(
        "Fee normalization complete.",
        f"Admission updated: {admission_updates}.",
        f"Recurring defaulted: {recurring_updates}.",
    )


if __name__ == "__main__":
    main()
