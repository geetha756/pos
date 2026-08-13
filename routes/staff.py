from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one, execute_transaction, get_db_connection
from .auth import login_required
from security import scoped_location_id
import calendar
import re
from datetime import date
import psycopg2

staff_bp = Blueprint('staff', __name__)

IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
BANK_ACCOUNT_RE = re.compile(r'^[0-9]{5,20}$')
PHONE_RE = re.compile(r'^[0-9]{10}$')


def _generate_employee_id():
    """Assign the next sequential Employee ID (EMP01, EMP02, ...), based on
    the highest EMP-numbered ID currently in the table. Computed fresh on
    every call (not a DB sequence) so a gap left by a deleted staff member -
    e.g. the highest employee_id being removed - is reclaimed immediately on
    the very next add, instead of only at the next app restart."""
    row = execute_query_one("""
        SELECT COALESCE(MAX(CAST(SUBSTRING(employee_id FROM '^EMP([0-9]+)$') AS INTEGER)), 0) AS max_n
        FROM staff WHERE employee_id ~ '^EMP[0-9]+$'
    """)
    return f"EMP{(row['max_n'] + 1):02d}"


def _days_in_current_month():
    today = date.today()
    return calendar.monthrange(today.year, today.month)[1]


def _compute_per_hour_salary(monthly_salary):
    """Derive Per Hour Salary from Monthly Salary: spread over this month's
    actual day count x an 8-hour day, so it stays current as months change
    length. Not stored - always computed fresh for display."""
    if not monthly_salary:
        return 0
    return float(monthly_salary) / (_days_in_current_month() * 8)


def _compute_per_day_salary(monthly_salary):
    """Derive Per Day Salary from Monthly Salary: spread over this month's
    actual day count. Not stored - always computed fresh for display."""
    if not monthly_salary:
        return 0
    return float(monthly_salary) / _days_in_current_month()


def _validate_bank_fields(bank_account_number, ifsc_code, monthly_salary, required=False):
    """Validate the bank/payroll fields. Returns an error message, or None.
    Format/range checks run before the required checks so a field that's
    present but invalid is always reported for what's wrong with it, not
    masked by a blank sibling field's "is required" error.
    required=True (Edit Staff Member only - Add Staff Member leaves these
    optional) additionally rejects a blank value for any of the three."""
    if bank_account_number and not BANK_ACCOUNT_RE.match(bank_account_number):
        return 'Bank Account Number must be 5-20 digits.'
    if ifsc_code and not IFSC_RE.match(ifsc_code):
        return 'IFSC Code must be in a valid format (e.g. SBIN0005814).'
    if monthly_salary:
        try:
            if float(monthly_salary) < 0:
                return 'Monthly Salary cannot be negative.'
        except ValueError:
            return 'Monthly Salary must be a valid number.'
    if required:
        if not bank_account_number:
            return 'Bank Account Number is required.'
        if not ifsc_code:
            return 'IFSC Code is required.'
        if not monthly_salary:
            return 'Monthly Salary is required.'
    return None

@staff_bp.route('/')
@login_required
def index():
    """List all staff members"""
    try:
        position_filter = request.args.get('position')
        department_filter = request.args.get('department')
        status_filter = request.args.get('status')
        # Staff Status has three views: Active, Inactive, and All (both) -
        # any missing/invalid value falls back to the Active tab.
        if status_filter not in ('active', 'inactive', 'all'):
            status_filter = 'active'

        # A store-scoped manager only sees staff at their own location.
        store = scoped_location_id()

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
            WHERE s.is_deleted = FALSE
        """
        params = []

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

        if status_filter != 'all':
            query += " AND s.is_active = %s"
            params.append(status_filter == 'active')

        # Explicit, stable order by Employee ID - never rely on Postgres's
        # default row order, which is not guaranteed to match insertion or
        # any other consistent sequence.
        query += " ORDER BY s.employee_id ASC"

        staff = execute_query(query, tuple(params) if params else None, fetch=True)

        # Counts for the tab labels - scoped to the manager's store like the
        # main list, but not narrowed by the position/department filters so
        # the counts always reflect the full Active/Inactive totals.
        count_query = """
            SELECT COUNT(*) FILTER (WHERE is_active = TRUE) as active_count,
                   COUNT(*) FILTER (WHERE is_active = FALSE) as inactive_count
            FROM staff
            WHERE is_deleted = FALSE
        """
        count_params = []
        if store:
            count_query += " AND location_id = %s"
            count_params.append(store)
        counts = execute_query_one(count_query, tuple(count_params) if count_params else None)
        active_count = counts['active_count'] if counts else 0
        inactive_count = counts['inactive_count'] if counts else 0

        # Get locations for filter dropdown
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)

        return render_template('staff/index.html',
                               staff=staff or [],
                               locations=locations or [],
                               selected_position=selected_position,
                               selected_position_title=selected_position['title'] if selected_position else None,
                               selected_position_id=position_filter,
                               selected_department_id=department_filter,
                               selected_status=status_filter,
                               active_count=active_count,
                               inactive_count=inactive_count,
                               all_count=active_count + inactive_count)
    except Exception as e:
        flash(f'Error loading staff: {str(e)}', 'error')
        return render_template('staff/index.html', staff=[], locations=[], selected_position=None,
                               selected_position_title=None,
                               selected_position_id=None,
                               selected_department_id=None,
                               selected_status='active',
                               active_count=0,
                               inactive_count=0,
                               all_count=0)

@staff_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """Add new staff member"""
    if request.method == 'POST':
        # Email, Hire Date, Manager, legacy Salary, and Emergency Contact are
        # not on the Add Staff form. Hire Date is NOT NULL in the database,
        # so it's stamped with today's date; the rest stay NULL (all
        # nullable) until set some other way.
        first_name = request.form.get('first_name')
        last_name = (request.form.get('last_name') or '').strip()
        phone = (request.form.get('phone') or '').strip() or None
        position_id = request.form.get('position_id') or None
        department_id = request.form.get('department_id') or None
        location_id = request.form.get('location_id') or None
        # A store-scoped manager can only assign staff to their own store.
        store = scoped_location_id()
        if store:
            location_id = store
        hire_date = date.today()
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        notes = request.form.get('notes')
        bank_account_number = (request.form.get('bank_account_number') or '').strip() or None
        ifsc_code = (request.form.get('ifsc_code') or '').strip().upper() or None
        monthly_salary = request.form.get('monthly_salary') or None

        if not first_name or not last_name or not position_id:
            flash('First name, last name, and position are required', 'error')
            return render_template('staff/add.html')

        if not phone or not PHONE_RE.match(phone):
            flash('Phone number is required and must be exactly 10 digits.', 'error')
            return render_template('staff/add.html')

        bank_error = _validate_bank_fields(bank_account_number, ifsc_code, monthly_salary)
        if bank_error:
            flash(bank_error, 'error')
            return render_template('staff/add.html')

        try:
            employee_id = _generate_employee_id()
            execute_query("""
                INSERT INTO staff (employee_id, first_name, last_name, phone, position_id,
                                 department_id, location_id, hire_date, address,
                                 city, state, zip_code, notes, bank_account_number, ifsc_code,
                                 monthly_salary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, first_name, last_name, phone, position_id, department_id,
                  location_id, hire_date, address, city, state, zip_code,
                  notes, bank_account_number, ifsc_code, monthly_salary))
            flash('Staff member added successfully!', 'success')
            return redirect(url_for('staff.index'))
        except psycopg2.IntegrityError as e:
            if 'employee_id' in str(e).lower():
                flash('Employee ID generation collided. Please try again.', 'error')
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
                WHERE (p.title LIKE '%Manager%' OR p.title LIKE '%Director%' OR p.title LIKE '%Supervisor%')
                AND s.is_active = TRUE AND s.is_deleted = FALSE
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
        # Employee ID, email, manager, legacy salary, and emergency contact
        # are not on the Edit Staff form and are intentionally left out of
        # both the SELECT-for-redisplay and the UPDATE below, so this
        # endpoint never touches them - whatever was set when the staff
        # member was added stays untouched. Hire Date IS editable here.
        first_name = request.form.get('first_name')
        last_name = (request.form.get('last_name') or '').strip()
        phone = (request.form.get('phone') or '').strip() or None
        position_id = request.form.get('position_id') or None
        department_id = request.form.get('department_id') or None
        location_id = request.form.get('location_id') or None
        # A store-scoped manager can only assign staff to their own store.
        store = scoped_location_id()
        if store:
            location_id = store
        hire_date = request.form.get('hire_date')
        is_active = request.form.get('is_active') == 'on'
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        notes = request.form.get('notes')
        bank_account_number = (request.form.get('bank_account_number') or '').strip() or None
        ifsc_code = (request.form.get('ifsc_code') or '').strip().upper() or None
        monthly_salary = request.form.get('monthly_salary') or None

        if not first_name or not last_name or not position_id or not hire_date:
            staff_member = execute_query_one("SELECT * FROM staff WHERE id = %s", (staff_id,))
            staff_member['per_hour_salary'] = _compute_per_hour_salary(staff_member.get('monthly_salary'))
            staff_member['per_day_salary'] = _compute_per_day_salary(staff_member.get('monthly_salary'))
            flash('First name, last name, position, and hire date are required', 'error')
            return render_template('staff/edit.html', staff=staff_member)

        if not phone or not PHONE_RE.match(phone):
            staff_member = execute_query_one("SELECT * FROM staff WHERE id = %s", (staff_id,))
            staff_member['per_hour_salary'] = _compute_per_hour_salary(staff_member.get('monthly_salary'))
            staff_member['per_day_salary'] = _compute_per_day_salary(staff_member.get('monthly_salary'))
            flash('Phone number is required and must be exactly 10 digits.', 'error')
            return render_template('staff/edit.html', staff=staff_member)

        bank_error = _validate_bank_fields(bank_account_number, ifsc_code, monthly_salary, required=True)
        if bank_error:
            staff_member = execute_query_one("SELECT * FROM staff WHERE id = %s", (staff_id,))
            staff_member['per_hour_salary'] = _compute_per_hour_salary(staff_member.get('monthly_salary'))
            staff_member['per_day_salary'] = _compute_per_day_salary(staff_member.get('monthly_salary'))
            flash(bank_error, 'error')
            return render_template('staff/edit.html', staff=staff_member)

        try:
            execute_query("""
                UPDATE staff
                SET first_name = %s, last_name = %s, phone = %s,
                    position_id = %s, department_id = %s, location_id = %s, hire_date = %s,
                    is_active = %s, address = %s, city = %s,
                    state = %s, zip_code = %s, notes = %s, bank_account_number = %s,
                    ifsc_code = %s, monthly_salary = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (first_name, last_name, phone, position_id, department_id,
                  location_id, hire_date, is_active, address, city, state,
                  zip_code, notes,
                  bank_account_number, ifsc_code, monthly_salary, staff_id))
            flash('Staff member updated successfully!', 'success')
            return redirect(url_for('staff.index'))
        except psycopg2.IntegrityError as e:
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

        if not staff_member or staff_member['is_deleted']:
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

        staff_member['per_hour_salary'] = _compute_per_hour_salary(staff_member.get('monthly_salary'))
        staff_member['per_day_salary'] = _compute_per_day_salary(staff_member.get('monthly_salary'))

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
                WHERE (p.title LIKE '%Manager%' OR p.title LIKE '%Director%' OR p.title LIKE '%Supervisor%')
                AND s.is_active = TRUE AND s.is_deleted = FALSE
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

@staff_bp.route('/deactivate/<staff_id>', methods=['POST'])
@login_required
def deactivate(staff_id):
    """Deactivate staff member - a reversible status change, not a delete: the
    record stays in the DB and still appears under Inactive Staff.
    Having subordinates never blocks this: any staff reporting to this person
    are automatically reassigned to this person's own manager (or left with
    no manager, if they had none) in the same transaction as the deactivation."""
    status_tab = request.args.get('status', 'active')
    try:
        manager = execute_query_one("SELECT manager_id FROM staff WHERE id = %s", (staff_id,))
        new_manager_id = manager['manager_id'] if manager else None

        execute_transaction([
            ("UPDATE staff SET manager_id = %s WHERE manager_id = %s", (new_manager_id, staff_id)),
            ("UPDATE staff SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (staff_id,)),
        ])
        flash('Staff member deactivated successfully!', 'success')
    except Exception as e:
        flash(f'Error deactivating staff member: {str(e)}', 'error')
    return redirect(url_for('staff.index', status=status_tab))

@staff_bp.route('/activate/<staff_id>', methods=['POST'])
@login_required
def activate(staff_id):
    """Activate staff member"""
    status_tab = request.args.get('status', 'inactive')
    try:
        execute_query("UPDATE staff SET is_active = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (staff_id,))
        flash('Staff member activated successfully!', 'success')
    except Exception as e:
        flash(f'Error activating staff member: {str(e)}', 'error')
    return redirect(url_for('staff.index', status=status_tab))

@staff_bp.route('/delete/<staff_id>', methods=['POST'])
@login_required
def delete(staff_id):
    """Soft-delete a staff member: the row is never removed from the
    database (orders, payroll, timesheets, and every other historical
    record that references it stay intact) - it's just flagged is_deleted
    and hidden from the normal Active/Inactive lists, dropdowns, and search.
    Like deactivate(), any subordinates reporting to this person are
    reassigned to this person's own manager in the same transaction, so a
    delete never leaves a dangling manager_id pointing at a deleted row."""
    status_tab = request.args.get('status', 'active')
    try:
        manager = execute_query_one("SELECT manager_id FROM staff WHERE id = %s", (staff_id,))
        new_manager_id = manager['manager_id'] if manager else None

        execute_transaction([
            ("UPDATE staff SET manager_id = %s WHERE manager_id = %s", (new_manager_id, staff_id)),
            ("UPDATE staff SET is_deleted = TRUE, is_active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE id = %s", (staff_id,)),
        ])
        flash('Staff member deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting staff member: {str(e)}', 'error')
    return redirect(url_for('staff.index', status=status_tab))

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

        if not staff_member or staff_member['is_deleted']:
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

        staff_member['per_hour_salary'] = _compute_per_hour_salary(staff_member.get('monthly_salary'))
        staff_member['per_day_salary'] = _compute_per_day_salary(staff_member.get('monthly_salary'))

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
