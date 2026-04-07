# Pinaki

A desktop school management system built with FastAPI, SQLAlchemy, and a Windows app-style launcher.

## Features

- Student management with course, hostel, and transport assignments
- Payment tracking and filtering by type, student, and status
- Guardian notification generation for outstanding fees
- Role-based access: admin and clerk views
- Printable payment reminder letter generation
- Native desktop application interface

## Setup

1. Create a Python environment:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the desktop app:
   ```bash
   python launcher.py
   ```

4. The application opens in its own app window to the first-run setup screen.
5. Create the administrator account and school profile in the one-time setup flow.

For an installable Windows desktop build, package `launcher.py` with PyInstaller and the included Inno Setup script as described in [PACKAGING.md](PACKAGING.md).

## Testing

Install development dependencies:
```bash
pip install -r requirements-dev.txt
```

Run tests:
```bash
pytest
```

## Database Migrations

Alembic is now configured for developer-managed schema migrations.

Install development dependencies first:
```bash
pip install -r requirements-dev.txt
```

Create a new revision:
```bash
alembic revision --autogenerate -m "describe the change"
```

Apply migrations to a fresh or Alembic-managed database:
```bash
alembic upgrade head
```

Important:
- The app still keeps its existing built-in startup migration runner for current installs and packaged desktops.
- The Alembic baseline revision in `alembic/versions/20260407_0001_baseline_schema.py` represents the current schema for new databases.
- If you already have a database created by the app, stamp it once instead of replaying the baseline:

```bash
alembic stamp head
```

- To target a different database when using the CLI, set `SCHOOLFLOW_DATABASE_URL` before running Alembic.
