"""
Standalone migration script for updating Fee model records.

This script updates existing Fee records based on their category:
- If category is 'admission': sets type to ADMISSION, is_one_time to True, and frequency to None.
- Otherwise: sets type to TUITION, is_one_time to False, and frequency to MONTHLY.

Safe to run multiple times: only updates records that don't already match the target state.
"""

from school_admin.database import SessionLocal
from school_admin.models import Fee, FeeType, FeeFrequency

def migrate_fees():
    print("Starting Fee model migration...")
    
    with SessionLocal() as session:
        fees = session.query(Fee).all()
        updated_count = 0
        
        for fee in fees:
            # Determine target state based on category
            normalized_category = str(fee.category or "").strip().lower()
            
            if normalized_category == "admission":
                target_type = FeeType.ADMISSION.value
                target_is_one_time = True
                target_frequency = None
            else:
                target_type = FeeType.TUITION.value
                target_is_one_time = False
                target_frequency = FeeFrequency.MONTHLY.value
            
            # Check if any fields actually need changing to avoid redundant updates
            has_changes = (
                fee.type != target_type or
                fee.is_one_time != target_is_one_time or
                fee.frequency != target_frequency
            )
            
            if has_changes:
                old_state = f"type={fee.type}, one_time={fee.is_one_time}, freq={fee.frequency}"
                new_state = f"type={target_type}, one_time={target_is_one_time}, freq={target_frequency}"
                
                fee.type = target_type
                fee.is_one_time = target_is_one_time
                fee.frequency = target_frequency
                
                updated_count += 1
                print(f"Update [{fee.id}] '{fee.name}' ({fee.category}):")
                print(f"  From: {old_state}")
                print(f"  To:   {new_state}")
        
        if updated_count > 0:
            session.commit()
            print("-" * 40)
            print(f"Completed: Updated {updated_count} fee records.")
        else:
            print("-" * 40)
            print("Completed: No records required updating.")

if __name__ == "__main__":
    try:
        migrate_fees()
    except Exception as e:
        print(f"Migration failed: {e}")
