from datetime import date, datetime
from school_admin.database import SessionLocal
from school_admin.models import Student, Fee, User, PaymentTransaction
from school_admin.services import PaymentService
from sqlalchemy import select, delete

def test_ledger():
    with SessionLocal() as session:
        # 1. Setup - find a test student and fee
        student = session.scalar(select(Student).where(Student.status == "Active").limit(1))
        fee = session.scalar(select(Fee).where(Fee.status == "Active").limit(1))
        admin = session.scalar(select(User).where(User.role == "Admin").limit(1))
        
        if not student or not fee:
            print("Missing test data (student or fee). Verification skipped.")
            return

        # Cleanup any previous test transactions for this student/fee
        session.execute(delete(PaymentTransaction).where(
            PaymentTransaction.student_id == student.id,
            PaymentTransaction.fee_id == fee.id,
            PaymentTransaction.reference_id == "TEST-REF-LEDGER-001"
        ))
        session.commit()

        print(f"Testing for Student: {student.full_name}, Fee: {fee.name}")
        
        # 2. Check initial balance
        balance_before = PaymentService.get_fee_balance(session, student.id, fee.id)
        print(f"Initial Total Paid: {balance_before['total_paid']}")
        
        # 3. Record a partial payment
        partial_amount = 100.0
        PaymentService.record_payment(
            session, student.id, fee.id, partial_amount, "CASH", "TEST-REF-LEDGER-001", admin.id if admin else None
        )
        session.commit()
        
        # 4. Check partial balance
        balance_partial = PaymentService.get_fee_balance(session, student.id, fee.id)
        print(f"New Total Paid: {balance_partial['total_paid']}")
        
        # Basic assertions
        assert balance_partial["total_paid"] == balance_before["total_paid"] + partial_amount
        assert balance_partial["status"] in ["PARTIAL", "PAID"] # might be paid if fee was small
        
        # 5. Verify Ledger retrieval
        ledger = PaymentService.get_student_ledger(session, student.id)
        found = any(t["reference"] == "TEST-REF-LEDGER-001" for t in ledger)
        assert found, "Transaction not found in ledger"
        
        print("\nPayment Ledger verification successful!")

if __name__ == "__main__":
    test_ledger()
