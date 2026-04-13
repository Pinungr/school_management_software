from school_admin.database import SessionLocal
from school_admin.models import Student, Fee, User, PaymentTransaction
from school_admin.services import PaymentService
from sqlalchemy import select, delete
from fastapi import HTTPException

def test_hardening():
    with SessionLocal() as session:
        student = session.scalar(select(Student).where(Student.status == "Active").limit(1))
        fee = session.scalar(select(Fee).where(Fee.status == "Active").limit(1))
        admin = session.scalar(select(User).where(User.role == "Admin").limit(1))

        if not student or not fee:
            print("No test data found. Skipping.")
            return

        print(f"Testing Hardening for Student: {student.full_name}, Fee: {fee.name}")

        # 1. Test Negative Amount
        try:
            PaymentService.record_payment(session, student.id, fee.id, -100, "CASH")
            print("FAILED: Negative amount allowed")
        except HTTPException as e:
            print(f"SUCCESS: Negative amount rejected (400): {e.detail}")
            assert e.status_code == 400

        # 2. Test Overpayment
        balance = PaymentService.get_fee_balance(session, student.id, fee.id)
        excess_amount = balance["due"] + 50000.0 # large enough to exceed due
        try:
            PaymentService.record_payment(session, student.id, fee.id, excess_amount, "CASH")
            print("FAILED: Overpayment allowed")
        except HTTPException as e:
            print(f"SUCCESS: Overpayment rejected: {e.detail}")
            assert e.status_code == 400

        # 3. Test Immutability
        # We need a small valid amount
        if balance["due"] >= 1.0:
            tx = PaymentService.record_payment(session, student.id, fee.id, 1.0, "CASH", "HARDENING-TEST-IMMUTABLE")
            session.commit()
            print(f"Created test transaction {tx.id} for immutability check")
            
            # Try to update
            try:
                tx.amount_paid = 999.0
                session.commit()
                print("FAILED: Update allowed")
            except Exception as e:
                print(f"SUCCESS: Update blocked via event listener: {e}")
                session.rollback()

            # Try to delete
            try:
                # Need to refresh or get a new proxy for tx
                tx_to_del = session.scalar(select(PaymentTransaction).where(PaymentTransaction.id == tx.id))
                session.delete(tx_to_del)
                session.commit()
                print("FAILED: Delete allowed")
            except Exception as e:
                print(f"SUCCESS: Delete blocked via event listener: {e}")
                session.rollback()
        else:
            print("Fee already fully paid, skipping immutability test on this fee.")

        print("\nHardening verification completed.")

if __name__ == "__main__":
    test_hardening()
