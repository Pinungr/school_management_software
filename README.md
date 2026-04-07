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
