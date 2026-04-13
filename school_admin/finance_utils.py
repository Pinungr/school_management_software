from __future__ import annotations
from datetime import date
from .models import Fee, FeeType, Student, normalize_fee_type

def frequency_months(frequency: str | None) -> int:
    normalized_frequency = str(frequency or "One Time").strip()
    return {
        "Monthly": 1,
        "Quarterly": 3,
        "Half-Yearly": 6,
        "Yearly": 12,
    }.get(normalized_frequency, 0)

def monthly_equivalent_amount(amount: float | int | None, frequency: str | None) -> float:
    amount_value = float(amount or 0)
    months = frequency_months(frequency)
    if months <= 1:
        return amount_value
    return amount_value / months

def month_difference(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 0
    return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)

def fee_cycle_count(start_date: date, frequency: str, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    if as_of < start_date:
        return 0
    normalized_frequency = str(frequency or "One Time").strip()
    if normalized_frequency == "One Time":
        return 1
    return month_difference(start_date, as_of) + 1

def current_month_amount(
    amount: float | int | None,
    frequency: str | None,
    start_date: date,
    as_of: date | None = None,
) -> float:
    as_of = as_of or date.today()
    if as_of < start_date:
        return 0.0
    normalized_frequency = str(frequency or "One Time").strip()
    if normalized_frequency == "One Time":
        return float(amount or 0) if month_difference(start_date, as_of) == 0 else 0.0
    return monthly_equivalent_amount(amount, frequency)

def is_one_time_fee(fee: Fee) -> bool:
    if bool(fee.is_one_time):
        return True
    if normalize_fee_type(fee.type, category=fee.category) == FeeType.ADMISSION:
        return True
    if str(fee.frequency or "").strip() == "One Time":
        return True
    return False

def is_due_this_cycle(start_date: date, frequency: str, as_of: date | None = None) -> bool:
    as_of = as_of or date.today()
    if as_of < start_date:
        return False
    interval_months = frequency_months(frequency)
    if interval_months <= 0:
        return month_difference(start_date, as_of) == 0
    elapsed_months = month_difference(start_date, as_of)
    return elapsed_months % interval_months == 0

def cycle_index_for_frequency(start_date: date, frequency: str, as_of: date | None = None) -> int:
    as_of = as_of or date.today()
    if as_of < start_date:
        return 0
    interval_months = frequency_months(frequency)
    elapsed_months = month_difference(start_date, as_of)
    if interval_months <= 0:
        return 1
    return (elapsed_months // interval_months) + 1

def fee_applies_to_student(fee: Fee, student: Student) -> bool:
    target_type = str(fee.target_type or "General").strip()
    if target_type == "General":
        return True
    if target_type == "Course":
        return student.course_id == fee.target_id
    if target_type == "Hostel":
        return student.hostel_id == fee.target_id
    if target_type == "Transport":
        return student.transport_id == fee.target_id
    return False
