from __future__ import annotations
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import PaymentTransaction, Fee, Student, Payment
from ..finance_utils import fee_cycle_count, fee_applies_to_student

class PaymentService:
    @staticmethod
    def record_payment(
        session: Session,
        student_id: int,
        fee_id: int,
        amount: float,
        mode: str,
        reference_id: str | None = None,
        user_id: int | None = None
    ) -> PaymentTransaction:
        # Task 3: Standardize error handling (HTTP 400 for validation)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be positive")
            
        student = session.get(Student, student_id)
        if not student:
            raise HTTPException(status_code=404, detail=f"Student ID {student_id} not found")

        fee = session.get(Fee, fee_id)
        if not fee:
            raise HTTPException(status_code=404, detail=f"Fee ID {fee_id} not found")

        # Task 2: Concurrency Safety (Fresh re-fetch within session)
        # Using a fresh balance calculation ensures we don't use stale data from previous reads
        balance = PaymentService.get_fee_balance(session, student_id, fee_id)
        total_paid = balance["total_paid"]
        total_due = balance["total_fee"]

        # Task 1 & 5: Overpayment Protection
        if total_paid >= total_due:
            raise HTTPException(status_code=400, detail="Fee already fully paid")
        
        if total_paid + amount > total_due:
            remaining = max(0, total_due - total_paid)
            raise HTTPException(status_code=400, detail=f"Payment exceeds remaining due of {remaining:.2f}")

        # Task 4: Safe transaction creation
        transaction = PaymentTransaction(
            student_id=student_id,
            fee_id=fee_id,
            amount_paid=amount,
            payment_date=datetime.utcnow(),
            payment_mode=mode.upper(),
            reference_id=reference_id,
            created_by=user_id,
            created_at=datetime.utcnow()
        )
        session.add(transaction)
        session.flush()

        # Task 3: Automatic Receipt Generation
        from .receipt_service import ReceiptService
        ReceiptService.create_receipt(session, transaction, user_id)

        return transaction

    @staticmethod
    def get_fee_balance(session: Session, student_id: int, fee_id: int) -> dict:
        student = session.get(Student, student_id)
        fee = session.get(Fee, fee_id)
        
        if not student or not fee:
            return {
                "total_fee": 0.0,
                "total_paid": 0.0,
                "due": 0.0,
                "status": "UNPAID"
            }
            
        # Total due based on time since joining
        cycle_count = fee_cycle_count(student.joined_on, fee.frequency)
        total_fee = float(fee.amount or 0.0) * cycle_count
        
        # Sum transactions from new ledger
        ledger_total = session.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount_paid), 0.0))
            .where(
                PaymentTransaction.student_id == student_id,
                PaymentTransaction.fee_id == fee_id
            )
        ) or 0.0
        
        # Backward compatibility: sum legacy payments
        legacy_total = session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0.0))
            .where(
                Payment.student_id == student_id,
                Payment.service_id == fee_id,
                Payment.status == "Paid"
            )
        ) or 0.0
        
        total_paid = float(ledger_total + legacy_total)
        due = max(0.0, total_fee - total_paid)
        
        if total_paid >= total_fee:
            status = "PAID"
        elif total_paid > 0:
            status = "PARTIAL"
        else:
            status = "UNPAID"
            
        return {
            "total_fee": total_fee,
            "total_paid": total_paid,
            "due": due,
            "status": status
        }

    @staticmethod
    def get_student_ledger(session: Session, student_id: int) -> list[dict]:
        stmt = (
            select(PaymentTransaction)
            .where(PaymentTransaction.student_id == student_id)
            .order_by(PaymentTransaction.payment_date.desc())
        )
        transactions = session.scalars(stmt).all()
        
        return [
            {
                "id": t.id,
                "fee_name": t.fee.name if t.fee else "Unknown Fee",
                "amount": t.amount_paid,
                "date": t.payment_date,
                "mode": t.payment_mode,
                "reference": t.reference_id,
            }
            for t in transactions
        ]
