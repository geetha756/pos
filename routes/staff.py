from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one, execute_transaction, get_db_connection
from .auth import login_required
from security import scoped_location_id
import calendar
import re
from datetime import date
import psycopg2

staff_bp = Blueprint('staff', __name__)

# Indian states + union territories for the Address Information "State"
# dropdown on Add/Edit Staff Member. Andhra Pradesh is first so it's the
# default/pre-selected option.
INDIAN_STATES = [
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand', 'Karnataka',
    'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya',
    'Mizoram', 'Nagaland', 'Odisha', 'Punjab', 'Rajasthan', 'Sikkim',
    'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand',
    'West Bengal',
    'Andaman and Nicobar Islands', 'Chandigarh',
    'Dadra and Nagar Haveli and Daman and Diu', 'Delhi', 'Jammu and Kashmir',
    'Ladakh', 'Lakshadweep', 'Puducherry',
]

IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
BANK_ACCOUNT_RE = re.compile(r'^[0-9]{5,20}$')
# Kept for reference/back-compat; _is_valid_phone below does the real,
# explicitly-separated checks and is what every caller actually uses.
PHONE_RE = re.compile(r'^[6-9][0-9]{9}$')


def _has_repeating_pattern(phone, min_run=8):
    """True if `phone` contains a run of `min_run`+ consecutive digits (out
    of its 10) that repeats with a period of 1 or 2 - e.g. 7989898989 (the
    "89" pair keeps repeating from index 2 onward), 7878787878, 1111111111.
    Checked over every starting position, not just from the very first
    digit, so a pattern that only kicks in partway through the number
    (like 7989898989) is still caught - a naive `phone[:2] * 5 == phone`
    check only catches a pattern that starts at position 0."""
    n = len(phone)
    for start in range(0, n - min_run + 1):
        window = phone[start:]
        for period in (1, 2):
            if all(window[i] == window[i % period] for i in range(len(window))):
                return True
    return False


def _is_valid_phone(phone):
    """True if `phone` is a plausible, genuine Indian mobile number - not
    just a well-formed string of digits. Every rule is its own explicit
    check - deliberately NOT collapsed into a single regex - so a bad first
    digit is always caught on its own, never masked by (or mistaken for) a
    plain length check:
      1. digits only, and exactly 10 of them
      2. first digit is 6, 7, 8, or 9 (0-5 rejected outright)
      3. not a straight ascending/descending run across all 10 digits
         (1234567890, 1234567891, 9876543210, ...) - detected
         algorithmically, not via a fixed list, so every such run is
         caught, not just a couple of hardcoded examples
      4. no repeating/pattern-based dummy run of 8+ digits with period 1 or
         2, anywhere in the number - not just anchored at the start (see
         _has_repeating_pattern) - covers all-same-digit numbers
         (1111111111, 9999999999) and 2-digit alternating patterns
         (9898989898, 9191919191, and mid-number ones like 7989898989)
         under one general rule
    """
    if not phone:
        return False
    if not phone.isdigit() or len(phone) != 10:
        return False
    if phone[0] not in ('6', '7', '8', '9'):
        return False
    digits = [int(d) for d in phone]
    ascending = all(digits[i] == digits[i - 1] + 1 for i in range(1, 10))
    descending = all(digits[i] == digits[i - 1] - 1 for i in range(1, 10))
    if ascending or descending:
        return False
    if _has_repeating_pattern(phone):
        return False
    return True


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


def _validate_bank_fields(bank_account_number, ifsc_code, monthly_salary):
    """Validate the bank/payroll fields - Bank Account Number, IFSC Code,
    and Monthly Salary are mandatory on both Add and Edit Staff Member.
    Returns a list of every error found (empty if all three are present and
    valid), not just the first - a blank field is reported as "required"
    and a present-but-malformed field is reported for what's wrong with it."""
    errors = []
    if not bank_account_number:
        errors.append('Bank Account Number is required.')
    elif not BANK_ACCOUNT_RE.match(bank_account_number):
        errors.append('Bank Account Number must be 5-20 digits.')

    if not ifsc_code:
        errors.append('IFSC Code is required.')
    elif not IFSC_RE.match(ifsc_code):
        errors.append('IFSC Code must be in a valid format (e.g. SBIN0005814).')

    if not monthly_salary:
        errors.append('Monthly Salary is required.')
    else:
        try:
            salary_value = float(monthly_salary)
            if salary_value < 0:
                errors.append('Monthly Salary cannot be negative.')
            elif salary_value == 0:
                errors.append('Monthly Salary must be greater than zero.')
        except ValueError:
            errors.append('Monthly Salary must be a valid number.')
    return errors


def _validate_address_fields(address, city, state, zip_code):
    """Street Address, City, State, and ZIP are all mandatory. Returns a
    list of error messages (empty if every field is present)."""
    errors = []
    if not address:
        errors.append('Street Address is required.')
    if not city:
        errors.append('City is required.')
    if not state:
        errors.append('State is required.')
    if not zip_code:
        errors.append('ZIP is required.')
    return errors


def _validate_staff_form(*, first_name, last_name, phone, position_id, department_id,
                          location_id, hire_date_required, hire_date,
                          bank_account_number, ifsc_code, monthly_salary,
                          address, city, state, zip_code,
                          duplicate_exclude_id=None):
    """Validate every field on the Add/Edit Staff form and return the full
    list of error messages found - not just the first one - so the caller
    can flash and highlight every invalid/missing field at once, matching
    the inline per-field messages the frontend shows for the same fields."""
    errors = []

    if not first_name:
        errors.append('First name is required.')
    if not last_name:
        errors.append('Last name is required.')
    if not position_id:
        errors.append('Position is required.')
    if not location_id:
        errors.append('Location is required.')
    if hire_date_required and not hire_date:
        errors.append('Hire date is required.')

    if not phone:
        errors.append('Phone number is required.')
    elif phone[0] in ('0', '1', '2', '3', '4', '5'):
        # Called out explicitly and on its own - checked before every other
        # phone rule, so a bad first digit is never silently folded into
        # the generic length/format message below.
        errors.append('Enter a valid 10-digit mobile number starting with 6, 7, 8, or 9.')
    elif not _is_valid_phone(phone):
        errors.append('Enter a valid 10-digit mobile number. Example: 7989189681')

    errors.extend(_validate_bank_fields(bank_account_number, ifsc_code, monthly_salary))
    errors.extend(_validate_address_fields(address, city, state, zip_code))

    # Duplicate-name is checked last since it costs a query, and only when
    # the name fields themselves are actually present.
    if first_name and last_name and _find_duplicate_name(first_name, last_name, exclude_id=duplicate_exclude_id):
        errors.append('A staff member with this name already exists.')

    return errors


def _find_duplicate_name(first_name, last_name, exclude_id=None):
    """Look for another (non-deleted) staff member with the same First +
    Last Name, case-insensitively. Returns that staff member's row (with a
    few identifying fields joined in) or None. exclude_id excludes the
    record currently being edited so it never flags itself."""
    query = """
        SELECT s.id, s.employee_id, s.first_name, s.last_name, s.phone,
               l.name AS location_name, p.title AS position
        FROM staff s
        LEFT JOIN locations l ON s.location_id = l.id
        LEFT JOIN positions p ON s.position_id = p.id
        WHERE s.is_deleted = FALSE
          AND LOWER(s.first_name) = LOWER(%s)
          AND LOWER(s.last_name) = LOWER(%s)
    """
    params = [first_name, last_name]
    if exclude_id:
        query += " AND s.id != %s"
        params.append(exclude_id)
    query += " LIMIT 1"
    return execute_query_one(query, tuple(params))

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

        validation_errors = _validate_staff_form(
            first_name=first_name, last_name=last_name, phone=phone,
            position_id=position_id, department_id=department_id, location_id=location_id,
            hire_date_required=False, hire_date=hire_date,
            bank_account_number=bank_account_number, ifsc_code=ifsc_code, monthly_salary=monthly_salary,
            address=address, city=city, state=state, zip_code=zip_code,
        )

        if validation_errors:
            for message in validation_errors:
                flash(message, 'error')
            return _render_staff_form('staff/add.html')

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
        return _render_staff_form('staff/add.html')

    return _render_staff_form('staff/add.html')


def _render_staff_form(template_name, **extra):
    """Fetch the shared Add/Edit Staff dropdown data (locations, departments,
    positions, managers) and render the given template with it, plus any
    extra context (e.g. staff=... for Edit). Used both for the initial GET
    and to redisplay the form with its dropdowns intact after a validation
    error on POST."""
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

    return render_template(template_name, locations=locations or [], departments=departments or [],
                         positions=positions or [], managers=managers or [], indian_states=INDIAN_STATES, **extra)

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

        validation_errors = _validate_staff_form(
            first_name=first_name, last_name=last_name, phone=phone,
            position_id=position_id, department_id=department_id, location_id=location_id,
            hire_date_required=True, hire_date=hire_date,
            bank_account_number=bank_account_number, ifsc_code=ifsc_code, monthly_salary=monthly_salary,
            address=address, city=city, state=state, zip_code=zip_code,
            duplicate_exclude_id=staff_id,
        )

        if validation_errors:
            for message in validation_errors:
                flash(message, 'error')
            return _render_edit_form(staff_id)

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
        return _render_edit_form(staff_id)

    # GET request - show edit form
    return _render_edit_form(staff_id)


def _render_edit_form(staff_id):
    """Load a staff member (with derived display fields) and render the Edit
    Staff form for them, with dropdowns intact. Used for the initial GET and
    to redisplay the form after a validation/save error on POST, so the
    user's dropdown selections are never dropped."""
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

        return _render_staff_form('staff/edit.html', staff=staff_member)
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

@staff_bp.route('/check-duplicate-name', methods=['POST'])
@login_required
def check_duplicate_name():
    """Check if another (non-deleted) staff member already has this First +
    Last Name. Used by the Add/Edit Staff form to warn about a possible
    duplicate before submitting."""
    try:
        data = request.get_json()
        first_name = (data.get('first_name') or '').strip()
        last_name = (data.get('last_name') or '').strip()
        exclude_id = data.get('exclude_id')  # For edit operations

        if not first_name or not last_name:
            return jsonify({'exists': False})

        duplicate = _find_duplicate_name(first_name, last_name, exclude_id=exclude_id)
        if not duplicate:
            return jsonify({'exists': False})

        return jsonify({
            'exists': True,
            'staff': {
                'name': f"{duplicate['first_name']} {duplicate['last_name']}",
                'employee_id': duplicate['employee_id'],
                'phone': duplicate['phone'],
                'location': duplicate['location_name'],
                'position': duplicate['position'],
            }
        })
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
