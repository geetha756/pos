from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one, get_db_connection
from .auth import login_required
import psycopg2

departments_bp = Blueprint('departments', __name__)

@departments_bp.route('/')
@login_required
def index():
    """List all departments"""
    try:
        # Get departments with manager information
        departments_conn = get_db_connection()
        departments_cursor = departments_conn.cursor()
        try:
            departments_cursor.execute("""
                SELECT d.id, d.name, d.description, d.manager_id, d.budget, d.is_active,
                       d.created_at, d.updated_at,
                       COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as manager_name,
                       COUNT(s2.id) as staff_count
                FROM departments d
                LEFT JOIN staff s ON d.manager_id = s.id
                LEFT JOIN staff s2 ON d.id = s2.department_id AND s2.is_active = TRUE AND s2.is_deleted = FALSE
                GROUP BY d.id, d.name, d.description, d.manager_id, d.budget, d.is_active,
                         d.created_at, d.updated_at, s.first_name, s.last_name
                ORDER BY d.name
            """)
            departments_raw = departments_cursor.fetchall()
            # Convert to dict format
            departments = [{
                'id': row[0], 'name': row[1], 'description': row[2], 'manager_id': row[3],
                'budget': row[4], 'is_active': row[5], 'created_at': row[6], 'updated_at': row[7],
                'manager_name': row[8], 'staff_count': row[9]
            } for row in departments_raw]
        finally:
            departments_cursor.close()
            departments_conn.close()

        return render_template('departments/index.html', departments=departments or [])
    except Exception as e:
        flash(f'Error loading departments: {str(e)}', 'error')
        return render_template('departments/index.html', departments=[])

@departments_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """Add new department"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        manager_id = request.form.get('manager_id') or None
        budget = request.form.get('budget') or None

        if not name:
            flash('Department name is required', 'error')
            return render_template('departments/add.html')

        try:
            execute_query("""
                INSERT INTO departments (name, description, manager_id, budget)
                VALUES (%s, %s, %s, %s)
            """, (name, description, manager_id, budget))
            flash('Department added successfully!', 'success')
            return redirect(url_for('departments.index'))
        except psycopg2.IntegrityError as e:
            if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                flash('A department with this name already exists. Please choose a different name.', 'error')
            else:
                flash(f'Error adding department: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error adding department: {str(e)}', 'error')

    # Get potential managers (staff with managerial positions)
    try:
        # Use regular cursor to avoid RealDictCursor issues
        managers_conn = get_db_connection()
        managers_cursor = managers_conn.cursor()
        try:
            managers_cursor.execute("""
                SELECT s.id, COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as name, p.title
                FROM staff s
                JOIN positions p ON s.position_id = p.id
                WHERE (p.title LIKE '%Manager%' OR p.title LIKE '%Director%' OR p.title LIKE '%Supervisor%')
                AND s.is_active = TRUE AND s.is_deleted = FALSE
                ORDER BY COALESCE(s.last_name, ''), COALESCE(s.first_name, '')
            """)
            managers_raw = managers_cursor.fetchall()
            # Convert to dict format
            managers = [{'id': row[0], 'name': row[1], 'title': row[2]} for row in managers_raw]
        finally:
            managers_cursor.close()
            managers_conn.close()
    except Exception as e:
        managers = []

    return render_template('departments/add.html', managers=managers or [])

@departments_bp.route('/edit/<department_id>', methods=['GET', 'POST'])
@login_required
def edit(department_id):
    """Edit department"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        manager_id = request.form.get('manager_id') or None
        budget = request.form.get('budget') or None
        is_active = request.form.get('is_active') == 'on'

        if not name:
            flash('Department name is required', 'error')
            department = execute_query_one("SELECT * FROM departments WHERE id = %s", (department_id,))
            return render_template('departments/edit.html', department=department)

        try:
            execute_query("""
                UPDATE departments
                SET name = %s, description = %s, manager_id = %s, budget = %s,
                    is_active = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, description, manager_id, budget, is_active, department_id))
            flash('Department updated successfully!', 'success')
            return redirect(url_for('departments.index'))
        except psycopg2.IntegrityError as e:
            if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                flash('A department with this name already exists. Please choose a different name.', 'error')
                department = execute_query_one("SELECT * FROM departments WHERE id = %s", (department_id,))
                return render_template('departments/edit.html', department=department)
            else:
                flash(f'Error updating department: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error updating department: {str(e)}', 'error')

    # GET request - show edit form
    try:
        department = execute_query_one("""
            SELECT d.*,
                   s.first_name || ' ' || s.last_name as manager_name
            FROM departments d
            LEFT JOIN staff s ON d.manager_id = s.id
            WHERE d.id = %s
        """, (department_id,))

        if not department:
            flash('Department not found', 'error')
            return redirect(url_for('departments.index'))

        # Get potential managers (use regular cursor to avoid RealDictCursor issues)
        managers_conn = get_db_connection()
        managers_cursor = managers_conn.cursor()
        try:
            managers_cursor.execute("""
                SELECT s.id, COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as name, p.title
                FROM staff s
                JOIN positions p ON s.position_id = p.id
                WHERE (p.title LIKE '%Manager%' OR p.title LIKE '%Director%' OR p.title LIKE '%Supervisor%')
                AND s.is_active = TRUE AND s.is_deleted = FALSE
                ORDER BY COALESCE(s.last_name, ''), COALESCE(s.first_name, '')
            """)
            managers_raw = managers_cursor.fetchall()
            # Convert to dict format
            managers = [{'id': row[0], 'name': row[1], 'title': row[2]} for row in managers_raw]
        finally:
            managers_cursor.close()
            managers_conn.close()

        return render_template('departments/edit.html', department=department,
                             managers=managers or [])
    except Exception as e:
        flash(f'Error loading department: {str(e)}', 'error')
        return redirect(url_for('departments.index'))

@departments_bp.route('/check-name', methods=['POST'])
@login_required
def check_name():
    """Check if a department name already exists"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        exclude_id = data.get('exclude_id')  # For edit operations

        if not name:
            return jsonify({'exists': False})

        query = "SELECT id FROM departments WHERE name = %s"
        params = (name,)

        if exclude_id:
            query += " AND id != %s"
            params = (name, exclude_id)

        result = execute_query_one(query, params)
        return jsonify({'exists': result is not None})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@departments_bp.route('/delete/<department_id>', methods=['POST'])
@login_required
def delete(department_id):
    """Delete department"""
    try:
        # Check if department has staff assigned
        staff_count = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE department_id = %s", (department_id,))
        if staff_count and staff_count['count'] > 0:
            flash('Cannot delete department with assigned staff. Please reassign staff first.', 'error')
            return redirect(url_for('departments.index'))

        execute_query("DELETE FROM departments WHERE id = %s", (department_id,))
        flash('Department deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting department: {str(e)}', 'error')
    return redirect(url_for('departments.index'))

@departments_bp.route('/view/<department_id>')
@login_required
def view(department_id):
    """View department details"""
    try:
        # Get department info
        department_conn = get_db_connection()
        department_cursor = department_conn.cursor()
        try:
            department_cursor.execute("""
                SELECT d.id, d.name, d.description, d.manager_id, d.budget, d.is_active,
                       d.created_at, d.updated_at,
                       COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as manager_name
                FROM departments d
                LEFT JOIN staff s ON d.manager_id = s.id
                WHERE d.id = %s
            """, (department_id,))
            department_raw = department_cursor.fetchone()
            if department_raw:
                department = {
                    'id': department_raw[0], 'name': department_raw[1], 'description': department_raw[2],
                    'manager_id': department_raw[3], 'budget': department_raw[4], 'is_active': department_raw[5],
                    'created_at': department_raw[6], 'updated_at': department_raw[7], 'manager_name': department_raw[8]
                }
            else:
                department = None
        finally:
            department_cursor.close()
            department_conn.close()

        if not department:
            flash('Department not found', 'error')
            return redirect(url_for('departments.index'))

        # Get staff in this department
        staff_conn = get_db_connection()
        staff_cursor = staff_conn.cursor()
        try:
            staff_cursor.execute("""
                SELECT s.id, s.employee_id, COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as name,
                       COALESCE(p.title, 'No Position') as position, s.is_active
                FROM staff s
                LEFT JOIN positions p ON s.position_id = p.id
                WHERE s.department_id = %s AND s.is_deleted = FALSE
                ORDER BY COALESCE(s.last_name, ''), COALESCE(s.first_name, '')
            """, (department_id,))
            staff_raw = staff_cursor.fetchall()
            staff = [{
                'id': row[0], 'employee_id': row[1], 'name': row[2],
                'position': row[3], 'is_active': row[4]
            } for row in staff_raw]
        finally:
            staff_cursor.close()
            staff_conn.close()

        # Get positions in this department
        positions_conn = get_db_connection()
        positions_cursor = positions_conn.cursor()
        try:
            positions_cursor.execute("""
                SELECT p.id, p.title, p.description, COUNT(s.id) as staff_count
                FROM positions p
                LEFT JOIN staff s ON p.id = s.position_id AND s.is_active = TRUE AND s.is_deleted = FALSE
                WHERE p.department_id = %s
                GROUP BY p.id, p.title, p.description
                ORDER BY p.title
            """, (department_id,))
            positions_raw = positions_cursor.fetchall()
            positions = [{
                'id': row[0], 'title': row[1], 'description': row[2], 'staff_count': row[3]
            } for row in positions_raw]
        finally:
            positions_cursor.close()
            positions_conn.close()

        return render_template('departments/view.html', department=department,
                             staff=staff or [], positions=positions or [])
    except Exception as e:
        flash(f'Error loading department details: {str(e)}', 'error')
        return redirect(url_for('departments.index'))
