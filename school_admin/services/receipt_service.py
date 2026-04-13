from __future__ import annotations
from datetime import datetime, date
import os
from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors

from ..models import Receipt, PaymentTransaction, Student, Setting

class ReceiptService:
    @staticmethod
    def generate_receipt_number(session: Session) -> str:
        """
        Generates a receipt number in the format RCPT-YYYYMMDD-XXXX.
        Sequence XXXX resets daily.
        """
        today_str = date.today().strftime("%Y%m%d")
        prefix = f"RCPT-{today_str}-"
        
        # Count receipts generated today to get the next sequence
        count = session.scalar(
            select(func.count(Receipt.id))
            .where(Receipt.receipt_number.like(f"{prefix}%"))
        ) or 0
        
        return f"{prefix}{str(count + 1).zfill(4)}"

    @staticmethod
    def create_receipt(session: Session, payment: PaymentTransaction, user_id: int | None = None) -> Receipt:
        """
        Creates a Receipt record linked to a PaymentTransaction.
        """
        receipt_number = ReceiptService.generate_receipt_number(session)
        receipt = Receipt(
            receipt_number=receipt_number,
            student_id=payment.student_id,
            payment_id=payment.id,
            amount_paid=payment.amount_paid,
            payment_date=payment.payment_date,
            generated_at=datetime.utcnow(),
            generated_by=user_id
        )
        session.add(receipt)
        session.flush() # Generate ID
        return receipt

    @staticmethod
    def generate_receipt_pdf(session: Session, receipt_id: int) -> str:
        """
        Generates a PDF for the given receipt and returns the file path.
        """
        receipt = session.scalar(
            select(Receipt)
            .options(
                joinedload(Receipt.student),
                joinedload(Receipt.payment).joinedload(PaymentTransaction.fee)
            )
            .where(Receipt.id == receipt_id)
        )
        if not receipt:
            raise ValueError(f"Receipt ID {receipt_id} not found")
            
        settings = session.get(Setting, 1) or Setting()
        
        # Ensure media/receipts directory exists
        receipts_dir = os.path.join("media", "receipts")
        if not os.path.exists(receipts_dir):
            os.makedirs(receipts_dir)
            
        file_path = os.path.join(receipts_dir, f"{receipt.receipt_number}.pdf")
        
        c = canvas.Canvas(file_path, pagesize=A4)
        width, height = A4
        
        # --- School Header ---
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width/2, height - 1.0*inch, (settings.school_name or "SCHOOL NAME").upper())
        
        c.setFont("Helvetica", 10)
        addr = settings.address or "Address not specified"
        c.drawCentredString(width/2, height - 1.25*inch, addr)
        
        # Line Separator
        c.setStrokeColor(colors.lightgrey)
        c.line(0.5*inch, height - 1.5*inch, width - 0.5*inch, height - 1.5*inch)
        
        # --- Receipt Info ---
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(colors.black)
        c.drawString(0.5*inch, height - 2.0*inch, "PAYMENT RECEIPT")
        
        c.setFont("Helvetica", 12)
        c.drawRightString(width - 0.5*inch, height - 2.0*inch, f"Receipt No: {receipt.receipt_number}")
        
        # --- Transaction Details Grid ---
        y = height - 2.6*inch
        
        def draw_row(label, value):
            nonlocal y
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(colors.darkslategray)
            c.drawString(1.0*inch, y, label)
            c.setFont("Helvetica", 11)
            c.setFillColor(colors.black)
            c.drawString(2.5*inch, y, str(value))
            y -= 0.3*inch

        draw_row("Date:", receipt.payment_date.strftime("%d %B, %Y"))
        draw_row("Student Name:", receipt.student.full_name)
        draw_row("Student Code:", receipt.student.student_code)
        
        fee_name = "General Fee"
        if receipt.payment and receipt.payment.fee:
            fee_name = receipt.payment.fee.name
        draw_row("Fee Category:", fee_name)
        
        draw_row("Payment Mode:", receipt.payment.payment_mode or "CASH")
        draw_row("Reference ID:", receipt.payment.reference_id or "N/A")
        
        # --- Amount Box ---
        y -= 0.4*inch
        c.setStrokeColor(colors.black)
        c.rect(0.5*inch, y - 0.5*inch, width - 1.0*inch, 0.7*inch, stroke=1, fill=0)
        
        c.setFont("Helvetica-Bold", 16)
        currency = settings.currency or "INR"
        c.drawCentredString(width/2, y - 0.3*inch, f"TOTAL PAID: {currency} {receipt.amount_paid:,.2f}")
        
        # --- Watermark ---
        c.saveState()
        c.setFont("Helvetica-Bold", 80)
        c.setStrokeColor(colors.lightgrey)
        c.setFillColor(colors.lightgrey, alpha=0.1)
        c.translate(width/2, height/2)
        c.rotate(45)
        c.drawCentredString(0, 0, "PAID")
        c.restoreState()
        
        # --- Footer ---
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(colors.grey)
        footer_text = "This is a computer-generated receipt. No signature is required."
        c.drawCentredString(width/2, 0.7*inch, footer_text)
        
        c.setFont("Helvetica", 8)
        c.drawCentredString(width/2, 0.5*inch, f"Generated at {receipt.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        c.showPage()
        c.save()
        
        return file_path
