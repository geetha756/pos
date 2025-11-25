from datetime import date
import uuid

from flask import session, flash

from database import execute_query_one, execute_query


def _split_name_defaults(full_name: str, email: str):
    """Split a user's name into first/last parts with sensible fallbacks."""
    fallback = (full_name or '').strip()
    if not fallback:
        fallback = (email or 'User Account').split('@')[0]

    parts = fallback.split(None, 1)
    first = parts[0] if parts else 'User'
    last = parts[1] if len(parts) > 1 else 'Account'
    return first, last


def _auto_create_staff_for_user(email: str):
    """Create a minimal staff record for a logged-in user when none exists."""
    if not email:
        return None

    first_name, last_name = _split_name_defaults(session.get('user_name', ''), email)
    employee_id = f"AUTO-{uuid.uuid4().hex[:8].upper()}"
    today = date.today()

    location_row = execute_query_one("SELECT id FROM locations ORDER BY name LIMIT 1")
    department_row = execute_query_one("SELECT id FROM departments ORDER BY name LIMIT 1")
    position_row = execute_query_one("SELECT id FROM positions ORDER BY title LIMIT 1")

    try:
        staff = execute_query_one("""
            INSERT INTO staff (
                employee_id, first_name, last_name, email, hire_date,
                location_id, department_id, position_id, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id
        """, (
            employee_id, first_name, last_name, email, today,
            location_row['id'] if location_row else None,
            department_row['id'] if department_row else None,
            position_row['id'] if position_row else None
        ))
    except Exception as e:
        print(f"Failed to auto-create staff record for {email}: {e}")
        return None

    if not staff or not staff.get('id'):
        return None

    staff_id = str(staff['id'])
    session['staff_id'] = staff_id

    try:
        execute_query("""
            UPDATE users
            SET staff_id = %s,
                department_id = COALESCE(department_id, %s),
                position_id = COALESCE(position_id, %s)
            WHERE email = %s
        """, (
            staff_id,
            department_row['id'] if department_row else None,
            position_row['id'] if position_row else None,
            email
        ))
    except Exception as e:
        print(f"Failed to link user to staff record for {email}: {e}")

    flash('A staff profile was automatically created for your account to complete this action.', 'info')
    return staff_id


def get_current_staff_id():
    """Return the logged-in user's staff ID (string), auto-creating one if needed."""
    staff_id = session.get('staff_id')
    if staff_id:
        return staff_id

    user_email = session.get('user_id')
    if not user_email:
        return None

    staff = execute_query_one("SELECT id FROM staff WHERE email = %s", (user_email,))
    if staff and staff.get('id'):
        staff_id = str(staff['id'])
        session['staff_id'] = staff_id
        return staff_id

    return _auto_create_staff_for_user(user_email)

