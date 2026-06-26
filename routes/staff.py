from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one, get_db_connection
from .auth import login_required
from security import scoped_location_id
import psycopg2

staff_bp = Blueprint('staff', __name__)

@staff_bp.route('/')
@login_required
def index():
    """List all staff members"""
    try:
        position_filter = request.args.get('position')
        department_filter = request.args.get('department')
        status_filter = request.args.get('status')

        query = """
            SELECT s.*,
                   l.name as location_name,
                   m.first_name || ' ' || m.last_name as manager_name,
                   p.title as position,
                   d.name as department
            FROM staff s
            LEFT JOIN locations l ON s.location_id = l.id
            LEFT JOIN staff m ON s.manager_id = m.id
            LEFT JOIN positions p ON s.position_id = p.id
            LEFT JOIN departments d ON s.department_id = d.id
            WHERE 1=1
        """
        params = []

        # A store-scoped manager only sees staff at their own location.
        store = scoped_location_id()
        if store:
            query += " AND s.location_id = %s"
            params.append(store)

        selected_position = None
        if position_filter:
            query += " AND s.position_id = %s"
            params.append(position_filter)
            selected_position = execute_query_one("SELECT id, title FROM positions WHERE id = %s", (position_filter,))

        if department_filter:
            query += " AND s.department_id = %s"
            params.append(department_filter)

        if status_filter == 'active':
            query += " AND s.is_active = TRUE"
        elif status_filter == 'inactive':
            query += " AND s.is_active = FALSE"

        query += " ORDER BY s.last_name, s.first_name"

        staff = execute_query(query, tuple(params) if params else None, fetch=True)

        # Get locations for filter dropdown
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)

        return render_template('staff/index.html',
                               staff=staff or [],
                               locations=locations or [],
                               selected_position=selected_position,
                               selected_position_title=selected_position['title'] if selected_position else None,
                               selected_position_id=position_filter,
                               selected_department_id=department_filter,
                               selected_status=status_filter)
    except Exception as e:
        flash(f'Error loading staff: {str(e)}', 'error')
        return render_template('staff/index.html', staff=[], locations=[], selected_position=None,
                               selected_position_title=None,
                               selected_position_id=None,
                               selected_department_id=None,
                               selected_status=None)

@staff_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """Add new staff member"""
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        position_id = request.form.get('position_id') or None
        department_id = request.form.get('department_id') or None
        location_id = request.form.get('location_id') or None
        # A store-scoped manager can only assign staff to their own store.
        store = scoped_location_id()
        if store:
            location_id = store
        hire_date = request.form.get('hire_date')
        salary = request.form.get('salary') or None
        manager_id = request.form.get('manager_id') or None
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        emergency_contact_name = request.form.get('emergency_contact_name')
        emergency_contact_phone = request.form.get('emergency_contact_phone')
        notes = request.form.get('notes')

        if not employee_id or not first_name or not last_name or not position_id or not hire_date:
            flash('Employee ID, first name, last name, position, and hire date are required', 'error')
            return render_template('staff/add.html')

        try:
            execute_query("""
                INSERT INTO staff (employee_id, first_name, last_name, email, phone, position_id,
                                 department_id, location_id, hire_date, salary, manager_id, address,
                                 city, state, zip_code, emergency_contact_name,
                                 emergency_contact_phone, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, first_name, last_name, email, phone, position_id, department_id,
                  location_id, hire_date, salary, manager_id, address, city, state, zip_code,
                  emergency_contact_name, emergency_contact_phone, notes))
            flash('Staff member added successfully!', 'success')
            return redirect(url_for('staff.index'))
        except psycopg2.IntegrityError as e:
            if 'employee_id' in str(e).lower():
                flash('Employee ID already exists. Please choose a different ID.', 'error')
            elif 'email' in str(e).lower():
                flash('Email address already exists. Please use a different email.', 'error')
            else:
                flash(f'Error adding staff member: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error adding staff member: {str(e)}', 'error')

    # Get locations, departments, positions and potential managers for dropdowns
    try:
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)
        departments = execute_query("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name", fetch=True)
        positions = execute_query("SELECT id, title FROM positions WHERE is_active = TRUE ORDER BY title", fetch=True)

        # Use regular cursor for managers query to avoid RealDictCursor issues
        managers_conn = get_db_connection()
        managers_cursor = managers_conn.cursor()
        try:
            managers_cursor.execute("""
                SELECT s.id, COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as name, p.title
                FROM staff s
                JOIN positions p ON s.position_id = p.id
                WHERE p.title LIKE '%Manager%' OR p.title LIKE '%Director%' OR p.title LIKE '%Supervisor%'
                AND s.is_active = TRUE
                ORDER BY s.last_name, s.first_name
            """)
            managers_raw = managers_cursor.fetchall()
            # Convert to dict format
            managers = [{'id': row[0], 'name': row[1], 'title': row[2]} for row in managers_raw]
        finally:
            managers_cursor.close()
            managers_conn.close()
    except Exception as e:
        locations = []
        departments = []
        positions = []
        managers = []

    return render_template('staff/add.html', locations=locations or [], departments=departments or [],
                         positions=positions or [], managers=managers or [])

@staff_bp.route('/edit/<staff_id>', methods=['GET', 'POST'])
@login_required
def edit(staff_id):
    """Edit staff member"""
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        position_id = request.form.get('position_id') or None
        department_id = request.form.get('department_id') or None
        location_id = request.form.get('location_id') or None
        # A store-scoped manager can only assign staff to their own store.
        store = scoped_location_id()
        if store:
            location_id = store
        hire_date = request.form.get('hire_date')
        salary = request.form.get('salary') or None
        manager_id = request.form.get('manager_id') or None
        is_active = request.form.get('is_active') == 'on'
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        emergency_contact_name = request.form.get('emergency_contact_name')
        emergency_contact_phone = request.form.get('emergency_contact_phone')
        notes = request.form.get('notes')

        if not employee_id or not first_name or not last_name or not position_id or not hire_date:
            staff_member = execute_query_one("SELECT * FROM staff WHERE id = %s", (staff_id,))
            flash('Employee ID, first name, last name, position, and hire date are required', 'error')
            return render_template('staff/edit.html', staff=staff_member)

        try:
            execute_query("""
                UPDATE staff
                SET employee_id = %s, first_name = %s, last_name = %s, email = %s, phone = %s,
                    position_id = %s, department_id = %s, location_id = %s, hire_date = %s,
                    salary = %s, manager_id = %s, is_active = %s, address = %s, city = %s,
                    state = %s, zip_code = %s, emergency_contact_name = %s,
                    emergency_contact_phone = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (employee_id, first_name, last_name, email, phone, position_id, department_id,
                  location_id, hire_date, salary, manager_id, is_active, address, city, state,
                  zip_code, emergency_contact_name, emergency_contact_phone, notes, staff_id))
            flash('Staff member updated successfully!', 'success')
            return redirect(url_for('staff.index'))
        except psycopg2.IntegrityError as e:
            if 'employee_id' in str(e).lower():
                flash('Employee ID already exists. Please choose a different ID.', 'error')
            elif 'email' in str(e).lower():
                flash('Email address already exists. Please use a different email.', 'error')
            else:
                flash(f'Error updating staff member: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error updating staff member: {str(e)}', 'error')

    # GET request - show edit form
    try:
        staff_member = execute_query_one("""
            SELECT s.*
            FROM staff s
            WHERE s.id = %s
        """, (staff_id,))

        if not staff_member:
            flash('Staff member not found', 'error')
            return redirect(url_for('staff.index'))

        # Get additional info separately to avoid JOIN issues
        if staff_member['location_id']:
            location = execute_query_one("SELECT name FROM locations WHERE id = %s", (staff_member['location_id'],))
            staff_member['location_name'] = location['name'] if location else None
        else:
            staff_member['location_name'] = None

        if staff_member['manager_id']:
            manager = execute_query_one("SELECT COALESCE(first_name, '') || ' ' || COALESCE(last_name, '') as name FROM staff WHERE id = %s", (staff_member['manager_id'],))
            staff_member['manager_name'] = manager['name'] if manager else None
        else:
            staff_member['manager_name'] = None

        # Get position and department info
        if staff_member['position_id']:
            position = execute_query_one("SELECT title FROM positions WHERE id = %s", (staff_member['position_id'],))
            staff_member['position'] = position['title'] if position else None
        else:
            staff_member['position'] = None

        if staff_member['department_id']:
            department = execute_query_one("SELECT name FROM departments WHERE id = %s", (staff_member['department_id'],))
            staff_member['department'] = department['name'] if department else None
        else:
            staff_member['department'] = None

        # Get locations, departments, positions and potential managers for dropdowns
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)
        departments = execute_query("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name", fetch=True)
        positions = execute_query("SELECT id, title FROM positions WHERE is_active = TRUE ORDER BY title", fetch=True)

        # Use regular cursor for managers query to avoid RealDictCursor issues
        managers_conn = get_db_connection()
        managers_cursor = managers_conn.cursor()
        try:
            managers_cursor.execute("""
                SELECT s.id, COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as name, p.title
                FROM staff s
                JOIN positions p ON s.position_id = p.id
                WHERE p.title LIKE '%Manager%' OR p.title LIKE '%Director%' OR p.title LIKE '%Supervisor%'
                AND s.is_active = TRUE
                ORDER BY s.last_name, s.first_name
            """)
            managers_raw = managers_cursor.fetchall()
            # Convert to dict format
            managers = [{'id': row[0], 'name': row[1], 'title': row[2]} for row in managers_raw]
        finally:
            managers_cursor.close()
            managers_conn.close()

        return render_template('staff/edit.html', staff=staff_member,
                             locations=locations or [], departments=departments or [],
                             positions=positions or [], managers=managers or [])
    except Exception as e:
        flash(f'Error loading staff member: {str(e)}', 'error')
        return redirect(url_for('staff.index'))

@staff_bp.route('/check-employee-id', methods=['POST'])
@login_required
def check_employee_id():
    """Check if an employee ID already exists"""
    try:
        data = request.get_json()
        employee_id = data.get('employee_id', '').strip()
        exclude_id = data.get('exclude_id')  # For edit operations

        if not employee_id:
            return jsonify({'exists': False})

        query = "SELECT id FROM staff WHERE employee_id = %s"
        params = (employee_id,)

        if exclude_id:
            query += " AND id != %s"
            params = (employee_id, exclude_id)

        result = execute_query_one(query, params)
        return jsonify({'exists': result is not None})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@staff_bp.route('/check-email', methods=['POST'])
@login_required
def check_email():
    """Check if an email address already exists"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        exclude_id = data.get('exclude_id')  # For edit operations

        if not email:
            return jsonify({'exists': False})

        query = "SELECT id FROM staff WHERE email = %s"
        params = (email,)

        if exclude_id:
            query += " AND id != %s"
            params = (email, exclude_id)

        result = execute_query_one(query, params)
        return jsonify({'exists': result is not None})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@staff_bp.route('/delete/<staff_id>', methods=['POST'])
@login_required
def delete(staff_id):
    """Delete staff member"""
    try:
        # Check if staff member is a manager for others
        subordinates = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE manager_id = %s", (staff_id,))
        if subordinates and subordinates['count'] > 0:
            flash('Cannot delete staff member who has subordinates. Please reassign subordinates first.', 'error')
            return redirect(url_for('staff.index'))

        execute_query("DELETE FROM staff WHERE id = %s", (staff_id,))
        flash('Staff member deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting staff member: {str(e)}', 'error')
    return redirect(url_for('staff.index'))

@staff_bp.route('/view/<staff_id>')
@login_required
def view(staff_id):
    """View staff member details"""
    try:
        staff_member = execute_query_one("""
            SELECT s.*
            FROM staff s
            WHERE s.id = %s
        """, (staff_id,))

        if not staff_member:
            flash('Staff member not found', 'error')
            return redirect(url_for('staff.index'))

        # Get additional info separately
        if staff_member['location_id']:
            location = execute_query_one("SELECT name FROM locations WHERE id = %s", (staff_member['location_id'],))
            staff_member['location_name'] = location['name'] if location else None
        else:
            staff_member['location_name'] = None

        if staff_member['manager_id']:
            manager = execute_query_one("SELECT first_name || ' ' || last_name as name FROM staff WHERE id = %s", (staff_member['manager_id'],))
            staff_member['manager_name'] = manager['name'] if manager else None
        else:
            staff_member['manager_name'] = None

        # Get position and department info
        if staff_member['position_id']:
            position = execute_query_one("SELECT title FROM positions WHERE id = %s", (staff_member['position_id'],))
            staff_member['position'] = position['title'] if position else None
        else:
            staff_member['position'] = None

        if staff_member['department_id']:
            department = execute_query_one("SELECT name FROM departments WHERE id = %s", (staff_member['department_id'],))
            staff_member['department'] = department['name'] if department else None
        else:
            staff_member['department'] = None

        # Get subordinates if this person is a manager
        subordinates = execute_query("""
            SELECT s.id, s.first_name || ' ' || s.last_name as name, p.title as position, d.name as department
            FROM staff s
            LEFT JOIN positions p ON s.position_id = p.id
            LEFT JOIN departments d ON s.department_id = d.id
            WHERE s.manager_id = %s
            ORDER BY s.last_name, s.first_name
        """, (staff_id,), fetch=True)

        return render_template('staff/view.html', staff=staff_member, subordinates=subordinates or [])
    except Exception as e:
        flash(f'Error loading staff member details: {str(e)}', 'error')
        return redirect(url_for('staff.index'))
