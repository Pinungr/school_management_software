from fastapi.testclient import TestClient
from main import app
from school_admin.database import SessionLocal, Base, engine
from school_admin.seed import seed_database
from school_admin.migrations import run_migrations
from school_admin.models import Setting, User, Course
from sqlalchemy import select
from tests.test_financial_summary import configure_setup_state, extract_csrf_token

client = TestClient(app)

with SessionLocal() as session:
    Base.metadata.create_all(bind=engine)
    run_migrations(session)
    seed_database(session)
    configure_setup_state(session, setup_completed=True)
    
    course = session.scalar(select(Course).where(Course.code == "TEST-COURSE"))
    
    # Log in
    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "identifier": "admin",
            "password": "adminadmin",
            "next_path": "/dashboard",
        },
        follow_redirects=False,
    )
    print(f"Login status: {login_response.status_code}")
    
    # Try to access payments
    response = client.get("/payments?page=2")
    print(f"Payments Page Status: {response.status_code}")
    print(f"Payments Page Title: {response.text.split('<title>')[1].split('</title>')[0] if '<title>' in response.text else 'No Title'}")
    if "Showing 51-55 of 55 records." not in response.text:
         print("CONTENT NOT FOUND!")
         # Print a bit of the body
         print(response.text[:1000])
