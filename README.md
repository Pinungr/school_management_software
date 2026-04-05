# SchoolFlow

A simple school management system built with FastAPI, SQLAlchemy, and Jinja2.

## Features

- Student management with course, hostel, and transport assignments
- Payment tracking and filtering by type, student, and status
- Guardian notification generation for outstanding fees
- Role-based access: admin and clerk views
- Printable payment reminder letter generation

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

3. Run the app:
   ```bash
   python main.py
   ```

4. The browser opens automatically to the first-run setup screen.
5. Create the administrator account and school profile in the one-time setup flow.

## Testing

Install development dependencies:
```bash
pip install -r requirements-dev.txt
```

Run tests:
```bash
pytest
```
