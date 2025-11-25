from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one, get_db_connection
from .auth import login_required
import psycopg2

positions_bp = Blueprint('positions', __name__)

@positions_bp.route('/')
@login_required
def index():
    """List all positions"""
    try:
        # Get positions with department and staff count information
        positions_conn = get_db_connection()
        positions_cursor = positions_conn.cursor()
        try:
            positions_cursor.execute("""
                SELECT p.id, p.title, p.description, p.department_id, p.salary_min, p.salary_max,
                       p.is_active, p.created_at, p.updated_at,
                       d.name as department_name,
                       COUNT(s.id) as staff_count
                FROM positions p
                LEFT JOIN departments d ON p.department_id = d.id
                LEFT JOIN staff s ON p.id = s.position_id AND s.is_active = TRUE
                GROUP BY p.id, p.title, p.description, p.department_id, p.salary_min, p.salary_max,
                         p.is_active, p.created_at, p.updated_at, d.name
                ORDER BY p.title
            """)
            positions_raw = positions_cursor.fetchall()
            # Convert to dict format
            positions = [{
                'id': row[0], 'title': row[1], 'description': row[2], 'department_id': row[3],
                'salary_min': row[4], 'salary_max': row[5], 'is_active': row[6],
                'created_at': row[7], 'updated_at': row[8], 'department_name': row[9], 'staff_count': row[10]
            } for row in positions_raw]
        finally:
            positions_cursor.close()
            positions_conn.close()

        # Get departments for filter dropdown
        departments = execute_query("SELECT id, name FROM departments ORDER BY name", fetch=True)

        stats = {
            'total': len(positions) if positions else 0,
            'active': sum(1 for pos in positions if pos.get('is_active')) if positions else 0,
            'filled': sum(1 for pos in positions if (pos.get('staff_count') or 0) > 0) if positions else 0,
            'staff_total': sum((pos.get('staff_count') or 0) for pos in positions) if positions else 0
        }

        return render_template('positions/index.html',
                               positions=positions or [],
                               departments=departments or [],
                               position_stats=stats)
    except Exception as e:
        flash(f'Error loading positions: {str(e)}', 'error')
        return render_template('positions/index.html', positions=[], departments=[], position_stats={'total': 0, 'active': 0, 'filled': 0, 'staff_total': 0})

@positions_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """Add new position"""
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        department_id = request.form.get('department_id') or None
        salary_min = request.form.get('salary_min') or None
        salary_max = request.form.get('salary_max') or None

        if not title:
            flash('Position title is required', 'error')
            return render_template('positions/add.html')

        try:
            execute_query("""
                INSERT INTO positions (title, description, department_id, salary_min, salary_max)
                VALUES (%s, %s, %s, %s, %s)
            """, (title, description, department_id, salary_min, salary_max))
            flash('Position added successfully!', 'success')
            return redirect(url_for('positions.index'))
        except psycopg2.IntegrityError as e:
            if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                flash('A position with this title already exists. Please choose a different title.', 'error')
            else:
                flash(f'Error adding position: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error adding position: {str(e)}', 'error')

    # Get departments for dropdown
    try:
        departments = execute_query("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name", fetch=True)
    except Exception as e:
        departments = []

    return render_template('positions/add.html', departments=departments or [])

@positions_bp.route('/edit/<position_id>', methods=['GET', 'POST'])
@login_required
def edit(position_id):
    """Edit position"""
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        department_id = request.form.get('department_id') or None
        salary_min = request.form.get('salary_min') or None
        salary_max = request.form.get('salary_max') or None
        is_active = request.form.get('is_active') == 'on'

        if not title:
            flash('Position title is required', 'error')
            position = execute_query_one("SELECT * FROM positions WHERE id = %s", (position_id,))
            return render_template('positions/edit.html', position=position)

        try:
            execute_query("""
                UPDATE positions
                SET title = %s, description = %s, department_id = %s,
                    salary_min = %s, salary_max = %s, is_active = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (title, description, department_id, salary_min, salary_max, is_active, position_id))
            flash('Position updated successfully!', 'success')
            return redirect(url_for('positions.index'))
        except psycopg2.IntegrityError as e:
            if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                flash('A position with this title already exists. Please choose a different title.', 'error')
                position = execute_query_one("SELECT * FROM positions WHERE id = %s", (position_id,))
                return render_template('positions/edit.html', position=position)
            else:
                flash(f'Error updating position: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error updating position: {str(e)}', 'error')

    # GET request - show edit form
    try:
        position = execute_query_one("""
            SELECT p.*,
                   d.name as department_name
            FROM positions p
            LEFT JOIN departments d ON p.department_id = d.id
            WHERE p.id = %s
        """, (position_id,))

        if not position:
            flash('Position not found', 'error')
            return redirect(url_for('positions.index'))

        # Get departments for dropdown
        departments = execute_query("SELECT id, name FROM departments WHERE is_active = TRUE ORDER BY name", fetch=True)

        return render_template('positions/edit.html', position=position,
                             departments=departments or [])
    except Exception as e:
        flash(f'Error loading position: {str(e)}', 'error')
        return redirect(url_for('positions.index'))

@positions_bp.route('/check-title', methods=['POST'])
@login_required
def check_title():
    """Check if a position title already exists"""
    try:
        data = request.get_json()
        title = data.get('title', '').strip()
        exclude_id = data.get('exclude_id')  # For edit operations

        if not title:
            return jsonify({'exists': False})

        query = "SELECT id FROM positions WHERE title = %s"
        params = (title,)

        if exclude_id:
            query += " AND id != %s"
            params = (title, exclude_id)

        result = execute_query_one(query, params)
        return jsonify({'exists': result is not None})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@positions_bp.route('/delete/<position_id>', methods=['POST'])
@login_required
def delete(position_id):
    """Delete position"""
    try:
        # Check if position has staff assigned
        staff_count = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE position_id = %s", (position_id,))
        if staff_count and staff_count['count'] > 0:
            flash('Cannot delete position with assigned staff. Please reassign staff first.', 'error')
            return redirect(url_for('positions.index'))

        execute_query("DELETE FROM positions WHERE id = %s", (position_id,))
        flash('Position deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting position: {str(e)}', 'error')
    return redirect(url_for('positions.index'))

@positions_bp.route('/view/<position_id>')
@login_required
def view(position_id):
    """View position details"""
    try:
        # Get position info
        position_conn = get_db_connection()
        position_cursor = position_conn.cursor()
        try:
            position_cursor.execute("""
                SELECT p.id, p.title, p.description, p.department_id, p.salary_min, p.salary_max,
                       p.is_active, p.created_at, p.updated_at,
                       d.name as department_name
                FROM positions p
                LEFT JOIN departments d ON p.department_id = d.id
                WHERE p.id = %s
            """, (position_id,))
            position_raw = position_cursor.fetchone()
            if position_raw:
                position = {
                    'id': position_raw[0], 'title': position_raw[1], 'description': position_raw[2],
                    'department_id': position_raw[3], 'salary_min': position_raw[4], 'salary_max': position_raw[5],
                    'is_active': position_raw[6], 'created_at': position_raw[7], 'updated_at': position_raw[8],
                    'department_name': position_raw[9]
                }
            else:
                position = None
        finally:
            position_cursor.close()
            position_conn.close()

        if not position:
            flash('Position not found', 'error')
            return redirect(url_for('positions.index'))

        # Get staff in this position
        staff_conn = get_db_connection()
        staff_cursor = staff_conn.cursor()
        try:
            staff_cursor.execute("""
                SELECT s.id, s.employee_id, COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') as name,
                       COALESCE(d.name, 'No Department') as department, s.is_active
                FROM staff s
                LEFT JOIN departments d ON s.department_id = d.id
                WHERE s.position_id = %s
                ORDER BY COALESCE(s.last_name, ''), COALESCE(s.first_name, '')
            """, (position_id,))
            staff_raw = staff_cursor.fetchall()
            staff = [{
                'id': row[0], 'employee_id': row[1], 'name': row[2],
                'department': row[3], 'is_active': row[4]
            } for row in staff_raw]
        finally:
            staff_cursor.close()
            staff_conn.close()

        return render_template('positions/view.html', position=position, staff=staff or [])
    except Exception as e:
        flash(f'Error loading position details: {str(e)}', 'error')
        return redirect(url_for('positions.index'))
