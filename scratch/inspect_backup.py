
import zipfile
import json
import sqlite3
import io
from pathlib import Path

backup_path = Path("students_600_backup.pinaki-backup")

if not backup_path.exists():
    print(f"File {backup_path} does not exist")
    exit(1)

try:
    with zipfile.ZipFile(backup_path) as archive:
        print("Archive members:", archive.namelist())
        
        if "metadata.json" in archive.namelist():
            metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
            print("Metadata:", metadata)
        else:
            print("CRITICAL: metadata.json missing")
            
        if "data/school.db" in archive.namelist():
            db_bytes = archive.read("data/school.db")
            print(f"Database size: {len(db_bytes)} bytes")
            
            # Try to open and check tables
            with sqlite3.connect(":memory:") as conn:
                conn.deserialize(db_bytes)
                tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                print("Tables found:", tables)
                
                required_tables = {"settings", "users", "students", "payments"}
                missing = required_tables - set(tables)
                if missing:
                    print(f"MISSING TABLES: {missing}")
                else:
                    print("All required tables present")
                    
                # Check student count
                student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
                print(f"Student count: {student_count}")
        else:
            print("CRITICAL: data/school.db missing")
            
except Exception as e:
    print(f"Error inspecting backup: {e}")
