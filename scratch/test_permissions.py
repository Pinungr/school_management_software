from types import SimpleNamespace
from school_admin.permissions import has_permission

def test_permissions():
    admin = SimpleNamespace(role="ADMIN")
    clerk = SimpleNamespace(role="CLERK")
    
    # Check Admin
    assert has_permission(admin, "student.view") == True
    assert has_permission(admin, "catalog.manage") == True
    assert has_permission(admin, "settings.manage") == True
    
    # Check Clerk
    assert has_permission(clerk, "student.update") == True
    assert has_permission(clerk, "student.delete") == True
    assert has_permission(clerk, "student.update.course") == True
    assert has_permission(clerk, "catalog.view") == True
    assert has_permission(clerk, "catalog.manage") == False
    assert has_permission(clerk, "settings.manage") == False
    
    print("Permission mapping verification successful!")

if __name__ == "__main__":
    test_permissions()
