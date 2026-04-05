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

4. Open a browser at `http://127.0.0.1:8000`.

## Default accounts

- **Admin**: `admin` / `adminadmin`
- **Clerk**: `clark` / `clarkclark`

## Testing

Install development dependencies:
```bash
pip install -r requirements-dev.txt
```

Run tests:
```bash
pytest
```
