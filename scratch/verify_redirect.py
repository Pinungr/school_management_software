from school_admin.database import SessionLocal
from school_admin.routes.auth import login_page
from school_admin.utils import is_setup_complete, setup_redirect, is_terms_accepted
from fastapi import Request
from sqlalchemy import select
from school_admin.models import Setting

with SessionLocal() as session:
    settings = session.get(Setting, 1)
    settings.setup_completed = False
    settings.terms_accepted = False
    session.commit()
    
    print(f"Setup complete: {is_setup_complete(session)}")
    print(f"Terms accepted: {is_terms_accepted(session)}")
    print(f"setup_redirect() returns: {setup_redirect().headers['location']}")
    print(f"setup_redirect(session) returns: {setup_redirect(session).headers['location']}")
