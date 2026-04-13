from school_admin.database import SessionLocal, Base, engine
from school_admin.models import Setting, User
from sqlalchemy import select
from school_admin.migrations import run_migrations
from school_admin.seed import seed_database

def reset_and_setup_for_demo():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        run_migrations(session)
        seed_database(session)
        settings = session.get(Setting, 1)
        if settings:
            settings.setup_completed = False
            settings.terms_accepted = False
            session.commit()
    print("Database reset for manual verification.")

if __name__ == "__main__":
    reset_and_setup_for_demo()
