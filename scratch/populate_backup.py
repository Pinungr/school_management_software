
import sqlite3
import zipfile
import json
import io
import random
from datetime import datetime, timezone, date
from pathlib import Path

def generate_data():
    # Courses
    courses = [
        (1, "Class 1", "C1", 5000, "Monthly", "Active", ""),
        (2, "Class 2", "C2", 5500, "Monthly", "Active", ""),
        (3, "Class 3", "C3", 6000, "Monthly", "Active", ""),
    ]
    
    # Sections
    sections = [
        (1, 1, "Section A", "1A", "Mr. X", "Room 101", "Active", ""),
        (2, 2, "Section A", "2A", "Mr. Y", "Room 201", "Active", ""),
        (3, 3, "Section A", "3A", "Mr. Z", "Room 301", "Active", ""),
    ]
    
    students = []
    first_names = ["Arjun", "Deepak", "Rohan", "Suresh", "Amit", "Priya", "Anjali", "Sneha", "Kavita", "Neeta"]
    last_names = ["Sharma", "Verma", "Gupta", "Singh", "Patel", "Reddy", "Nair", "Iyer", "Kumar", "Das"]
    
    for i in range(1, 601):
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        code = f"ST{2024000 + i}"
        course_id = random.randint(1, 3)
        section_id = course_id # simplicity
        students.append((
            i, code, f"{fn} {ln}", f"{fn.lower()}.{ln.lower()}{i}@example.com", 
            "9876543" + str(i).zfill(3), f"Parent {ln}", "Active", "Street " + str(i),
            date.today().isoformat(), course_id, section_id, None, None
        ))
    return courses, sections, students

backup_path = Path("students_600_backup.pinaki-backup")

# Always create fresh to ensure schema matches current models.py
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, school_name TEXT, school_email TEXT, phone_number TEXT, logo_url TEXT, address TEXT, academic_year TEXT, financial_year TEXT, fee_frequency TEXT, currency TEXT, timezone TEXT, developer_name TEXT, developer_email TEXT, developer_phone TEXT, terms_accepted BOOLEAN, terms_accepted_at DATE, setup_completed BOOLEAN)")
conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, email TEXT, password_hash TEXT, role TEXT, status TEXT, created_on DATE)")
conn.execute("CREATE TABLE IF NOT EXISTS courses (id INTEGER PRIMARY KEY, name TEXT, code TEXT, fees FLOAT, frequency TEXT, status TEXT, description TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS sections (id INTEGER PRIMARY KEY, course_id INTEGER, name TEXT, code TEXT, class_teacher TEXT, room_name TEXT, status TEXT, description TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY, student_code TEXT, full_name TEXT, email TEXT, phone TEXT, parent_name TEXT, status TEXT, address TEXT, joined_on DATE, course_id INTEGER, section_id INTEGER, hostel_id INTEGER, transport_id INTEGER)")
conn.execute("CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY, student_id INTEGER, student_code TEXT, student_name TEXT, parent_name TEXT, snapshot_total_fees FLOAT, snapshot_paid_amount FLOAT, snapshot_current_cycle_amount FLOAT, snapshot_previous_pending_amount FLOAT, snapshot_remaining_balance FLOAT, service_type TEXT, service_id INTEGER, service_name TEXT, amount FLOAT, payment_date DATE, method TEXT, reference TEXT, notes TEXT, status TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS hostels (id INTEGER PRIMARY KEY, name TEXT, hostel_type TEXT, rooms INTEGER, fee_amount FLOAT, status TEXT, description TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS transport_routes (id INTEGER PRIMARY KEY, route_name TEXT, pickup_points TEXT, vehicle_no TEXT, driver_name TEXT, driver_phone TEXT, fee_amount FLOAT, frequency TEXT, status TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS fees (id INTEGER PRIMARY KEY, name TEXT, category TEXT, amount FLOAT, frequency TEXT, status TEXT, target_type TEXT, target_id INTEGER, description TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)")

# Insert data
courses, sections, students = generate_data()
conn.executemany("INSERT INTO courses VALUES (?, ?, ?, ?, ?, ?, ?)", courses)
conn.executemany("INSERT INTO sections VALUES (?, ?, ?, ?, ?, ?, ?, ?)", sections)
conn.executemany("INSERT INTO students VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", students)

# Add basic settings and one admin
conn.execute("INSERT INTO settings (id, school_name, setup_completed) VALUES (1, 'Pinaki School', 1)")
conn.execute("INSERT INTO users (id, full_name, username, email, password_hash, role, status) VALUES (1, 'Admin', 'admin', 'admin@example.com', 'scrypt:32768:8:1$7D2Y1u6H$e9f45657...', 'SuperAdmin', 'Active')")

conn.commit()
db_data = conn.serialize()

archive_buffer = io.BytesIO()
with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr(
        "metadata.json",
        json.dumps(
            {
                "app_name": "Pinaki",
                "format_version": 1,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
    )
    archive.writestr("data/school.db", db_data)

backup_path.write_bytes(archive_buffer.getvalue())
print(f"Successfully updated {backup_path} with 600 students matching project schema.")
