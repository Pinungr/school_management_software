from datetime import date, timedelta
from school_admin.database import SessionLocal, Base, engine
from school_admin.models import Fee, Student, Course, Payment, FeeType, FeeFrequency
from school_admin.utils import calculate_student_due_breakdown

def setup_test_data():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    
    # Create a course
    course = Course(name="Test Grade", code="TG101", fees=1000)
    session.add(course)
    session.flush()
    
    # Create an Admission fee (One-time)
    admission_fee = Fee(
        name="Admission Fee",
        category="Admission",
        type=FeeType.ADMISSION.value,
        is_one_time=True,
        amount=5000,
        frequency=None,
        status="Active",
        target_type="General"
    )
    
    # Create a Tuition fee (Monthly)
    tuition_fee = Fee(
        name="Tuition Fee",
        category="Course",
        type=FeeType.TUITION.value,
        is_one_time=False,
        amount=2000,
        frequency=FeeFrequency.MONTHLY.value,
        status="Active",
        target_type="General"
    )
    
    # Create a Yearly fee
    yearly_fee = Fee(
        name="Annual Activity Fee",
        category="Other",
        type=FeeType.TUITION.value,
        is_one_time=False,
        amount=1200,
        frequency=FeeFrequency.YEARLY.value,
        status="Active",
        target_type="General"
    )
    
    session.add_all([admission_fee, tuition_fee, yearly_fee])
    session.flush()
    
    # Create a student who joined today
    student = Student(
        student_code="S101",
        full_name="Test Student",
        email="test@example.com",
        phone="1234567890",
        course_id=course.id,
        joined_on=date.today()
    )
    session.add(student)
    session.flush()
    
    return session, student

def test_reminder_logic():
    session, student = setup_test_data()
    
    print("Testing reminder logic for new student (month 0)...")
    due_data = calculate_student_due_breakdown(session, student)
    
    print(f"Total Due: {due_data['total_due']}")
    for item in due_data['breakdown']:
        print(f"  {item['type']}: {item['amount']}")
        
    # Expected:
    # ADMISSION: 5000
    # COURSE: 2000 (Monthly Tuition)
    # OTHER: 100 (Monthly share of 1200 yearly fee)
    # Total: 7100
    
    assert due_data['total_due'] == 7100
    breakdown_types = {item['type']: item['amount'] for item in due_data['breakdown']}
    assert breakdown_types["ADMISSION"] == 5000
    assert breakdown_types["COURSE"] == 2000
    assert breakdown_types["OTHER"] == 100
    
    print("Testing grouping (adding another Course fee)...")
    lab_fee = Fee(
        name="Lab Fee",
        category="Course",
        type=FeeType.TUITION.value,
        is_one_time=False,
        amount=500,
        frequency=FeeFrequency.MONTHLY.value,
        status="Active",
        target_type="General"
    )
    session.add(lab_fee)
    session.flush()
    
    due_data = calculate_student_due_breakdown(session, student)
    breakdown_types = {item['type']: item['amount'] for item in due_data['breakdown']}
    # COURSE should now be 2000 + 500 = 2500
    print(f"New COURSE total: {breakdown_types['COURSE']}")
    assert breakdown_types["COURSE"] == 2500
    
    print("Testing payment impact on One-time fee...")
    # Partial payment for admission
    payment = Payment(
        student_id=student.id,
        service_type="admission",
        service_id=1, # Admission Fee ID
        amount=3000,
        status="Paid",
        payment_date=date.today()
    )
    session.add(payment)
    session.flush()
    
    due_data = calculate_student_due_breakdown(session, student)
    breakdown_types = {item['type']: item['amount'] for item in due_data['breakdown']}
    print(f"New ADMISSION total after payment: {breakdown_types['ADMISSION']}")
    assert breakdown_types["ADMISSION"] == 2000 # 5000 - 3000
    
    print("Verification successful!")
    session.close()

if __name__ == "__main__":
    try:
        test_reminder_logic()
    except Exception as e:
        print(f"Tests failed: {e}")
        import traceback
        traceback.print_exc()
