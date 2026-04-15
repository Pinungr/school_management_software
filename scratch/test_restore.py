
import sys
from pathlib import Path
from school_admin.backup_restore import restore_backup_archive

backup_path = Path("students_600_backup.pinaki-backup")
if not backup_path.exists():
    print("File not found")
    exit(1)

try:
    with open(backup_path, "rb") as f:
        archive_bytes = f.read()
    
    print("Starting restore...")
    restore_backup_archive(archive_bytes)
    print("Restore successful!")
except Exception as e:
    print(f"Restore failed: {e}")
    import traceback
    traceback.print_exc()
