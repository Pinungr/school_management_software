from datetime import date, datetime
import os
from school_admin.database import SessionLocal
from school_admin.models import Student, Fee, User, PaymentTransaction, Receipt
from school_admin.services import PaymentService, ReceiptService
from sqlalchemy import select, delete

def test_receipts():
    with SessionLocal() as session:
        # 1. Setup - get existing test data
        student = session.scalar(select(Student).where(Student.status == "Active").limit(1))
        fee = session.scalar(select(Fee).where(Fee.status == "Active").limit(1))
        admin = session.scalar(select(User).where(User.role == "Admin").limit(1))
        
        if not student or not fee:
            print("Skipping verification: No student or fee found.")
            return

        print(f"--- Verification: Student {student.full_name} ---")

        # 2. Record a fresh payment to trigger automatic receipt
        # Check current balance to avoid overpayment error
        from school_admin.services import PaymentService
        balance = PaymentService.get_fee_balance(session, student.id, fee.id)
        if balance["due"] < 1.0:
             print("Fee already fully paid. Cannot generate new receipt for this fee.")
             # Fallback: Check if she has any existing receipts
             receipt = session.scalar(select(Receipt).where(Receipt.student_id == student.id).limit(1))
             if not receipt:
                 print("No receipts to test.")
                 return
        else:
            try:
                tx = PaymentService.record_payment(
                    session, student.id, fee.id, 1.0, "CASH", "RCPT-TEST-001", admin.id if admin else None
                )
                session.commit()
                print("Payment recorded successfully.")
                receipt = tx.receipt
            except Exception as e:
                print(f"Payment integration failed: {e}")
                return

        if not receipt:
            print("FAILED: Automatic receipt generation failed.")
            return

        print(f"Verified Receipt: {receipt.receipt_number}")

        # 3. Test PDF Generation
        try:
            pdf_path = ReceiptService.generate_receipt_pdf(session, receipt.id)
            if os.path.exists(pdf_path):
                print(f"SUCCESS: PDF created at {pdf_path}")
            else:
                print("FAILED: PDF file not found after generation.")
        except Exception as e:
            print(f"FAILED: PDF generation error: {e}")

        # 4. Test Immutability
        try:
            receipt.amount_paid = 9999.0
            session.commit()
            print("FAILED: Receipt update was allowed!")
        except Exception as e:
            print(f"SUCCESS: Receipt update blocked (Immutable): {e}")
            session.rollback()

if __name__ == "__main__":
    test_receipts()
