from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from database import execute_query, execute_query_one, get_db_connection
from .auth import login_required
from .helpers import get_current_staff_id
import psycopg2
from datetime import datetime, date, timedelta
import uuid
import traceback

payroll_bp = Blueprint('payroll', __name__)

@payroll_bp.route('/')
@login_required
def index():
    """Payroll dashboard"""
    try:
        # Get payroll statistics
        stats = get_payroll_stats()

        # Get recent timesheets
        recent_timesheets = execute_query("""
            SELECT t.id, t.date, t.total_hours, t.status, t.clock_in, t.clock_out,
                   s.first_name || ' ' || s.last_name as employee_name
            FROM timesheets t
            JOIN staff s ON t.staff_id = s.id
            ORDER BY t.updated_at DESC
            LIMIT 10
        """, fetch=True)

        # Get pending leave requests
        pending_leave = execute_query("""
            SELECT lr.id, lr.start_date, lr.end_date, lr.total_days, lr.reason, lr.status,
                   s.first_name || ' ' || s.last_name as employee_name,
                   lt.name as leave_type
            FROM leave_requests lr
            JOIN staff s ON lr.staff_id = s.id
            JOIN leave_types lt ON lr.leave_type_id = lt.id
            WHERE lr.status = 'pending'
            ORDER BY lr.created_at DESC
            LIMIT 5
        """, fetch=True)

        return render_template('payroll/index.html',
                             stats=stats or {},
                             recent_timesheets=recent_timesheets or [],
                             pending_leave=pending_leave or [])

    except Exception as e:
        flash(f'Error loading payroll dashboard: {str(e)}', 'error')
        return render_template('payroll/index.html', stats={}, recent_timesheets=[], pending_leave=[])

def get_payroll_stats():
    """Get payroll dashboard statistics"""
    stats = {
        'total_employees': 0,
        'active_timesheets': 0,
        'pending_leave_requests': 0,
        'current_payroll_cycle': None,
        'total_payroll_expense': 0.0,
        'overtime_hours': 0.0
    }

    try:
        # Total active employees
        result = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE is_active = TRUE")
        stats['total_employees'] = result['count'] if result else 0

        # Active timesheets this week
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM timesheets
            WHERE date >= CURRENT_DATE - INTERVAL '7 days'
            AND status IN ('draft', 'submitted')
        """)
        stats['active_timesheets'] = result['count'] if result else 0

        # Pending leave requests
        result = execute_query_one("SELECT COUNT(*) as count FROM leave_requests WHERE status = 'pending'")
        stats['pending_leave_requests'] = result['count'] if result else 0

        # Current payroll cycle
        result = execute_query_one("""
            SELECT name FROM payroll_cycles
            WHERE CURRENT_DATE BETWEEN start_date AND end_date
            ORDER BY start_date DESC LIMIT 1
        """)
        stats['current_payroll_cycle'] = result['name'] if result else None

        # Total payroll expense (last month)
        result = execute_query_one("""
            SELECT COALESCE(SUM(net_pay), 0) as total FROM payroll_entries pe
            JOIN payroll_cycles pc ON pe.payroll_cycle_id = pc.id
            WHERE pc.end_date >= CURRENT_DATE - INTERVAL '30 days'
            AND pe.status = 'paid'
        """)
        stats['total_payroll_expense'] = result['total'] if result else 0.0

        # Overtime hours this week
        result = execute_query_one("""
            SELECT COALESCE(SUM(overtime_hours), 0) as total FROM timesheets
            WHERE date >= CURRENT_DATE - INTERVAL '7 days'
        """)
        stats['overtime_hours'] = result['total'] if result else 0.0

    except Exception as e:
        print(f"Error getting payroll stats: {e}")

    return stats

# Timesheet routes
@payroll_bp.route('/timesheets')
@login_required
def timesheets():
    """List all timesheets"""
    try:
        # Get filters from request
        staff_id = request.args.get('staff_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        status = request.args.get('status')

        # Build query
        query = """
            SELECT t.*, s.first_name || ' ' || s.last_name as employee_name,
                   pc.name as payroll_cycle_name
            FROM timesheets t
            JOIN staff s ON t.staff_id = s.id
            LEFT JOIN payroll_cycles pc ON t.payroll_cycle_id = pc.id
        """
        params = []
        conditions = []

        if staff_id:
            conditions.append("t.staff_id = %s")
            params.append(staff_id)

        if start_date:
            conditions.append("t.date >= %s")
            params.append(start_date)

        if end_date:
            conditions.append("t.date <= %s")
            params.append(end_date)

        if status:
            conditions.append("t.status = %s")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY t.date DESC, s.last_name, s.first_name"

        timesheets_data = execute_query(query, tuple(params), fetch=True)

        # Get staff list for filter
        staff_list = execute_query("SELECT id, first_name || ' ' || last_name as name FROM staff WHERE is_active = TRUE ORDER BY last_name, first_name", fetch=True)

        return render_template('payroll/timesheets/index.html',
                             timesheets=timesheets_data or [],
                             staff_list=staff_list or [],
                             filters={'staff_id': staff_id, 'start_date': start_date or '', 'end_date': end_date or '', 'status': status})

    except Exception as e:
        flash(f'Error loading timesheets: {str(e)}', 'error')
        return render_template('payroll/timesheets/index.html', timesheets=[], staff_list=[], filters={'staff_id': '', 'start_date': '', 'end_date': '', 'status': ''})

@payroll_bp.route('/timesheets/<timesheet_id>')
@login_required
def view_timesheet(timesheet_id):
    """View individual timesheet details"""
    try:
        # Get timesheet details
        timesheet = execute_query_one("""
            SELECT t.*, s.first_name || ' ' || s.last_name as employee_name,
                   s.email, s.employee_id, d.name as department_name,
                   pc.name as payroll_cycle_name
            FROM timesheets t
            JOIN staff s ON t.staff_id = s.id
            LEFT JOIN departments d ON s.department_id = d.id
            LEFT JOIN payroll_cycles pc ON t.payroll_cycle_id = pc.id
            WHERE t.id = %s
        """, (timesheet_id,))

        if not timesheet:
            flash('Timesheet not found', 'error')
            return redirect(url_for('payroll.timesheets'))

        # Get breaks for this timesheet
        breaks = execute_query("""
            SELECT * FROM breaks
            WHERE timesheet_id = %s
            ORDER BY start_time
        """, (timesheet_id,), fetch=True)

        return render_template('payroll/timesheets/view.html',
                             timesheet=timesheet,
                             breaks=breaks or [])

    except Exception as e:
        flash(f'Error loading timesheet: {str(e)}', 'error')
        return redirect(url_for('payroll.timesheets'))

@payroll_bp.route('/timesheets/<timesheet_id>/modal')
@login_required
def view_timesheet_modal(timesheet_id):
    """Get timesheet details for modal display"""
    try:
        # Get timesheet details
        timesheet = execute_query_one("""
            SELECT t.*, s.first_name || ' ' || s.last_name as employee_name,
                   s.email, s.employee_id, d.name as department_name,
                   pc.name as payroll_cycle_name
            FROM timesheets t
            JOIN staff s ON t.staff_id = s.id
            LEFT JOIN departments d ON s.department_id = d.id
            LEFT JOIN payroll_cycles pc ON t.payroll_cycle_id = pc.id
            WHERE t.id = %s
        """, (timesheet_id,))

        if not timesheet:
            return '<div class="alert alert-danger">Timesheet not found</div>'

        # Get breaks for this timesheet
        breaks = execute_query("""
            SELECT * FROM breaks
            WHERE timesheet_id = %s
            ORDER BY start_time
        """, (timesheet_id,), fetch=True)

        return render_template('payroll/timesheets/modal_content.html',
                             timesheet=timesheet,
                             breaks=breaks or [])

    except Exception as e:
        return f'<div class="alert alert-danger">Error loading timesheet: {str(e)}</div>'

@payroll_bp.route('/timesheets/<timesheet_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_timesheet(timesheet_id):
    """Edit timesheet"""
    try:
        # Get timesheet details
        timesheet = execute_query_one("""
            SELECT t.*, s.first_name || ' ' || s.last_name as employee_name,
                   s.email, s.employee_id, d.name as department_name,
                   pc.name as payroll_cycle_name
            FROM timesheets t
            JOIN staff s ON t.staff_id = s.id
            LEFT JOIN departments d ON s.department_id = d.id
            LEFT JOIN payroll_cycles pc ON t.payroll_cycle_id = pc.id
            WHERE t.id = %s
        """, (timesheet_id,))

        if not timesheet:
            flash('Timesheet not found', 'error')
            return redirect(url_for('payroll.timesheets'))

        if request.method == 'POST':
            # Update timesheet
            clock_in = request.form.get('clock_in')
            clock_out = request.form.get('clock_out')

            # Validate and parse times
            try:
                if clock_in:
                    clock_in_time = datetime.strptime(clock_in, '%H:%M').time()
                else:
                    clock_in_time = None

                if clock_out:
                    clock_out_time = datetime.strptime(clock_out, '%H:%M').time()
                else:
                    clock_out_time = None

                # Calculate hours if both times are provided
                if clock_in_time and clock_out_time:
                    # Combine with the timesheet date
                    clock_in_datetime = datetime.combine(timesheet['date'], clock_in_time)
                    clock_out_datetime = datetime.combine(timesheet['date'], clock_out_time)

                    # Handle overnight shifts (clock out next day)
                    if clock_out_datetime < clock_in_datetime:
                        clock_out_datetime += timedelta(days=1)

                    total_seconds = (clock_out_datetime - clock_in_datetime).total_seconds()
                    total_hours = total_seconds / 3600

                    # Simple break calculation (assume 30 minutes break for shifts over 5 hours)
                    break_hours = 0.5 if total_hours > 5 else 0
                    regular_hours = total_hours - break_hours
                else:
                    regular_hours = timesheet['regular_hours'] or 0
                    break_hours = timesheet['break_hours'] or 0
                    total_hours = regular_hours + break_hours

                execute_query("""
                    UPDATE timesheets
                    SET clock_in = %s, clock_out = %s, regular_hours = %s,
                        break_hours = %s, total_hours = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (clock_in_datetime if clock_in_time else None,
                      clock_out_datetime if clock_out_time else None,
                      regular_hours, break_hours, total_hours, timesheet_id))

                flash('Timesheet updated successfully!', 'success')
                return redirect(url_for('payroll.timesheets'))

            except ValueError as e:
                flash(f'Invalid time format: {str(e)}', 'error')

        # Get breaks for this timesheet
        breaks = execute_query("""
            SELECT * FROM breaks
            WHERE timesheet_id = %s
            ORDER BY start_time
        """, (timesheet_id,), fetch=True)

        return render_template('payroll/timesheets/edit.html',
                             timesheet=timesheet,
                             breaks=breaks or [])

    except Exception as e:
        flash(f'Error loading timesheet: {str(e)}', 'error')
        return redirect(url_for('payroll.timesheets'))

@payroll_bp.route('/timesheets/clock-in', methods=['POST'])
@login_required
def clock_in():
    """Clock in for current user"""
    try:
        # Get current user email from session
        user_email = session.get('user_id')

        if not user_email:
            return jsonify({'success': False, 'message': 'User not authenticated'}), 401

        # Look up staff record by email to get staff_id
        staff = execute_query_one("SELECT id FROM staff WHERE email = %s AND is_active = TRUE", (user_email,))

        if not staff:
            return jsonify({'success': False, 'message': 'Staff record not found'}), 404

        user_id = staff['id']

        # Check if user is already clocked in today
        today = date.today()
        existing_timesheet = execute_query_one("""
            SELECT id, clock_in FROM timesheets
            WHERE staff_id = %s AND date = %s AND clock_out IS NULL
        """, (user_id, today))

        if existing_timesheet:
            return jsonify({'success': False, 'message': 'Already clocked in today'}), 400

        # Create new timesheet entry
        timesheet_id = str(uuid.uuid4())
        execute_query("""
            INSERT INTO timesheets (id, staff_id, date, clock_in, status)
            VALUES (%s, %s, %s, %s, 'draft')
        """, (timesheet_id, user_id, today, datetime.now()))

        return jsonify({'success': True, 'message': 'Clocked in successfully'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@payroll_bp.route('/timesheets/clock-out', methods=['POST'])
@login_required
def clock_out():
    """Clock out for current user"""
    try:
        # Get current user email from session
        user_email = session.get('user_id')

        if not user_email:
            return jsonify({'success': False, 'message': 'User not authenticated'}), 401

        # Look up staff record by email to get staff_id
        staff = execute_query_one("SELECT id FROM staff WHERE email = %s AND is_active = TRUE", (user_email,))

        if not staff:
            return jsonify({'success': False, 'message': 'Staff record not found'}), 404

        user_id = staff['id']

        today = date.today()

        # Get today's timesheet
        timesheet = execute_query_one("""
            SELECT id, clock_in FROM timesheets
            WHERE staff_id = %s AND date = %s AND clock_out IS NULL
        """, (user_id, today))

        if not timesheet:
            return jsonify({'success': False, 'message': 'No active timesheet found'}), 400

        clock_out_time = datetime.now()
        clock_in_time = timesheet['clock_in']

        # Calculate hours
        total_seconds = (clock_out_time - clock_in_time).total_seconds()
        total_hours = total_seconds / 3600  # Convert to hours

        # Calculate break time (if any breaks exist)
        breaks_total = execute_query_one("""
            SELECT COALESCE(SUM(duration_minutes), 0) as total_break_minutes
            FROM breaks
            WHERE timesheet_id = %s AND end_time IS NOT NULL
        """, (timesheet['id'],))

        break_hours = (breaks_total['total_break_minutes'] / 60) if breaks_total else 0
        regular_hours = max(0, total_hours - break_hours)

        # Update timesheet
        execute_query("""
            UPDATE timesheets
            SET clock_out = %s, total_hours = %s, regular_hours = %s, break_hours = %s
            WHERE id = %s
        """, (clock_out_time, total_hours, regular_hours, break_hours, timesheet['id']))

        return jsonify({
            'success': True,
            'message': 'Clocked out successfully',
            'total_hours': round(total_hours, 2),
            'regular_hours': round(regular_hours, 2)
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@payroll_bp.route('/timesheets/start-break', methods=['POST'])
@login_required
def start_break():
    """Start a break for current user"""
    try:
        # Get current user email from session
        user_email = session.get('user_id')
        break_type = request.form.get('break_type', 'regular')

        if not user_email:
            return jsonify({'success': False, 'message': 'User not authenticated'}), 401

        # Look up staff record by email to get staff_id
        staff = execute_query_one("SELECT id FROM staff WHERE email = %s AND is_active = TRUE", (user_email,))

        if not staff:
            return jsonify({'success': False, 'message': 'Staff record not found'}), 404

        user_id = staff['id']

        today = date.today()

        # Get today's active timesheet
        timesheet = execute_query_one("""
            SELECT id FROM timesheets
            WHERE staff_id = %s AND date = %s AND clock_out IS NULL
        """, (user_id, today))

        if not timesheet:
            return jsonify({'success': False, 'message': 'No active timesheet found'}), 400

        # Check if there's already an active break
        active_break = execute_query_one("""
            SELECT id FROM breaks
            WHERE timesheet_id = %s AND end_time IS NULL
        """, (timesheet['id'],))

        if active_break:
            return jsonify({'success': False, 'message': 'Break already active'}), 400

        # Start new break
        execute_query("""
            INSERT INTO breaks (timesheet_id, break_type, start_time)
            VALUES (%s, %s, %s)
        """, (timesheet['id'], break_type, datetime.now()))

        return jsonify({'success': True, 'message': 'Break started'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@payroll_bp.route('/timesheets/end-break', methods=['POST'])
@login_required
def end_break():
    """End current break for user"""
    try:
        # Get current user email from session
        user_email = session.get('user_id')

        if not user_email:
            return jsonify({'success': False, 'message': 'User not authenticated'}), 401

        # Look up staff record by email to get staff_id
        staff = execute_query_one("SELECT id FROM staff WHERE email = %s AND is_active = TRUE", (user_email,))

        if not staff:
            return jsonify({'success': False, 'message': 'Staff record not found'}), 404

        user_id = staff['id']

        today = date.today()

        # Get today's active timesheet
        timesheet = execute_query_one("""
            SELECT id FROM timesheets
            WHERE staff_id = %s AND date = %s AND clock_out IS NULL
        """, (user_id, today))

        if not timesheet:
            return jsonify({'success': False, 'message': 'No active timesheet found'}), 400

        # Get active break
        active_break = execute_query_one("""
            SELECT id, start_time FROM breaks
            WHERE timesheet_id = %s AND end_time IS NULL
            ORDER BY start_time DESC LIMIT 1
        """, (timesheet['id'],))

        if not active_break:
            return jsonify({'success': False, 'message': 'No active break found'}), 400

        end_time = datetime.now()
        start_time = active_break['start_time']
        duration_minutes = int((end_time - start_time).total_seconds() / 60)

        # Update break
        execute_query("""
            UPDATE breaks
            SET end_time = %s, duration_minutes = %s
            WHERE id = %s
        """, (end_time, duration_minutes, active_break['id']))

        # Recalculate timesheet hours
        _recalculate_timesheet_hours(timesheet['id'])

        return jsonify({
            'success': True,
            'message': 'Break ended',
            'duration_minutes': duration_minutes
        })

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

def _recalculate_timesheet_hours(timesheet_id):
    """Recalculate hours for a timesheet after break changes"""
    try:
        # Get timesheet data
        timesheet = execute_query_one("""
            SELECT clock_in, clock_out FROM timesheets WHERE id = %s
        """, (timesheet_id,))

        if not timesheet or not timesheet['clock_out']:
            return

        # Calculate total hours
        total_seconds = (timesheet['clock_out'] - timesheet['clock_in']).total_seconds()
        total_hours = total_seconds / 3600

        # Calculate break time
        breaks_total = execute_query_one("""
            SELECT COALESCE(SUM(duration_minutes), 0) as total_break_minutes
            FROM breaks
            WHERE timesheet_id = %s AND end_time IS NOT NULL
        """, (timesheet_id,))

        break_hours = (breaks_total['total_break_minutes'] / 60) if breaks_total else 0
        regular_hours = max(0, total_hours - break_hours)

        # Update timesheet
        execute_query("""
            UPDATE timesheets
            SET total_hours = %s, regular_hours = %s, break_hours = %s
            WHERE id = %s
        """, (total_hours, regular_hours, break_hours, timesheet_id))

    except Exception as e:
        print(f"Error recalculating timesheet hours: {e}")

# Leave management routes
@payroll_bp.route('/leave')
@login_required
def leave():
    """Leave management dashboard"""
    try:
        # Get leave balances for all employees
        leave_balances = execute_query("""
            SELECT lb.*, s.first_name || ' ' || s.last_name as employee_name,
                   lt.name as leave_type_name, lt.color
            FROM leave_balances lb
            JOIN staff s ON lb.staff_id = s.id
            JOIN leave_types lt ON lb.leave_type_id = lt.id
            WHERE s.is_active = TRUE AND lt.is_active = TRUE
            ORDER BY s.last_name, s.first_name, lt.name
        """, fetch=True)

        # Get pending leave requests
        pending_requests = execute_query("""
            SELECT lr.*, s.first_name || ' ' || s.last_name as employee_name,
                   lt.name as leave_type_name, lt.color
            FROM leave_requests lr
            JOIN staff s ON lr.staff_id = s.id
            JOIN leave_types lt ON lr.leave_type_id = lt.id
            WHERE lr.status = 'pending'
            ORDER BY lr.created_at DESC
        """, fetch=True)

        # Count leave approvals completed this month
        approved_this_month = execute_query_one("""
            SELECT COUNT(*) as count
            FROM leave_requests
            WHERE status = 'approved'
              AND approved_at IS NOT NULL
              AND approved_at >= date_trunc('month', CURRENT_DATE)
              AND approved_at < date_trunc('month', CURRENT_DATE) + INTERVAL '1 month'
        """) or {'count': 0}

        return render_template('payroll/leave/index.html',
                             leave_balances=leave_balances or [],
                             pending_requests=pending_requests or [],
                             approved_this_month=int(approved_this_month['count']))

    except Exception as e:
        flash(f'Error loading leave management: {str(e)}', 'error')
        return render_template('payroll/leave/index.html', leave_balances=[], pending_requests=[])

@payroll_bp.route('/leave/request', methods=['GET', 'POST'])
@login_required
def leave_request():
    """Submit leave request"""
    if request.method == 'POST':
        staff_id = request.form.get('staff_id')
        leave_type_id = request.form.get('leave_type_id')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        reason = request.form.get('reason')

        if not all([staff_id, leave_type_id, start_date, end_date]):
            flash('All fields are required', 'error')
            return redirect(url_for('payroll.leave_request'))

        try:
            # Calculate total days
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()

            # Count business days (excluding weekends)
            total_days = 0
            current_date = start
            while current_date <= end:
                if current_date.weekday() < 5:  # Monday to Friday
                    total_days += 1
                current_date += timedelta(days=1)

            # Insert leave request
            execute_query("""
                INSERT INTO leave_requests (staff_id, leave_type_id, start_date, end_date, total_days, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (staff_id, leave_type_id, start_date, end_date, total_days, reason))

            flash('Leave request submitted successfully!', 'success')
            return redirect(url_for('payroll.leave'))

        except Exception as e:
            flash(f'Error submitting leave request: {str(e)}', 'error')

    # GET request - show form
    try:
        # Get staff list
        staff = execute_query("SELECT id, first_name || ' ' || last_name as name FROM staff WHERE is_active = TRUE ORDER BY last_name, first_name", fetch=True)

        # Get leave types
        leave_types = execute_query("SELECT id, name, description FROM leave_types WHERE is_active = TRUE ORDER BY name", fetch=True)

        return render_template('payroll/leave/request.html', staff=staff or [], leave_types=leave_types or [])

    except Exception as e:
        flash(f'Error loading leave request form: {str(e)}', 'error')
        return render_template('payroll/leave/request.html', staff=[], leave_types=[])

@payroll_bp.route('/leave/approve/<request_id>', methods=['POST'])
@login_required
def approve_leave(request_id):
    """Approve leave request"""
    try:
        approved_by = get_current_staff_id()

        if not approved_by:
            flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
            return redirect(url_for('payroll.leave'))

        execute_query("""
            UPDATE leave_requests
            SET status = 'approved', approved_by = %s, approved_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (approved_by, request_id))

        flash('Leave request approved!', 'success')

    except Exception as e:
        flash(f'Error approving leave request: {str(e)}', 'error')

    return redirect(url_for('payroll.leave'))

@payroll_bp.route('/leave/reject/<request_id>', methods=['POST'])
@login_required
def reject_leave(request_id):
    """Reject leave request"""
    try:
        comments = request.form.get('comments')
        approved_by = get_current_staff_id()

        if not approved_by:
            flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
            return redirect(url_for('payroll.leave'))

        execute_query("""
            UPDATE leave_requests
            SET status = 'rejected', approved_by = %s, approved_at = CURRENT_TIMESTAMP,
                comments = %s
            WHERE id = %s
        """, (approved_by, comments, request_id))

        flash('Leave request rejected!', 'success')

    except Exception as e:
        flash(f'Error rejecting leave request: {str(e)}', 'error')

    return redirect(url_for('payroll.leave'))

@payroll_bp.route('/leave/history/<staff_id>')
@login_required
def leave_history(staff_id):
    """View leave history for a specific employee"""
    try:
        # Get staff information
        staff_info = execute_query_one("""
            SELECT s.*, d.name as department_name, l.name as location_name
            FROM staff s
            LEFT JOIN departments d ON s.department_id = d.id
            LEFT JOIN locations l ON s.location_id = l.id
            WHERE s.id = %s AND s.is_active = TRUE
        """, (staff_id,))

        if not staff_info:
            flash('Employee not found', 'error')
            return redirect(url_for('payroll.leave'))

        # Get leave requests history
        leave_requests = execute_query("""
            SELECT lr.*, lt.name as leave_type_name, lt.color,
                   CASE
                       WHEN lr.approved_by IS NOT NULL THEN
                           (SELECT first_name || ' ' || last_name FROM staff WHERE id = lr.approved_by)
                       ELSE NULL
                   END as approved_by_name
            FROM leave_requests lr
            JOIN leave_types lt ON lr.leave_type_id = lt.id
            WHERE lr.staff_id = %s
            ORDER BY lr.created_at DESC
        """, (staff_id,), fetch=True)

        # Get current leave balances
        leave_balances = execute_query("""
            SELECT lb.*, lt.name as leave_type_name, lt.color
            FROM leave_balances lb
            JOIN leave_types lt ON lb.leave_type_id = lt.id
            WHERE lb.staff_id = %s AND lt.is_active = TRUE
            ORDER BY lt.name
        """, (staff_id,), fetch=True)

        # Calculate leave statistics
        total_requests = len(leave_requests) if leave_requests else 0
        approved_requests = len([r for r in leave_requests if r['status'] == 'approved']) if leave_requests else 0
        pending_requests = len([r for r in leave_requests if r['status'] == 'pending']) if leave_requests else 0
        rejected_requests = len([r for r in leave_requests if r['status'] == 'rejected']) if leave_requests else 0

        total_days_taken = sum([r['total_days'] for r in leave_requests if r['status'] == 'approved']) if leave_requests else 0

        return render_template('payroll/leave/history.html',
                             staff_info=staff_info,
                             leave_requests=leave_requests or [],
                             leave_balances=leave_balances or [],
                             stats={
                                 'total_requests': total_requests,
                                 'approved_requests': approved_requests,
                                 'pending_requests': pending_requests,
                                 'rejected_requests': rejected_requests,
                                 'total_days_taken': total_days_taken
                             })

    except Exception as e:
        flash(f'Error loading leave history: {str(e)}', 'error')
        return redirect(url_for('payroll.leave'))

@payroll_bp.route('/leave/types')
@login_required
def leave_types():
    """Manage leave types"""
    try:
        leave_types_data = execute_query("""
            SELECT lt.*,
                   COUNT(lr.id) as usage_count,
                   COUNT(CASE WHEN lr.status = 'approved' THEN 1 END) as approved_count
            FROM leave_types lt
            LEFT JOIN leave_requests lr ON lt.id = lr.leave_type_id
            GROUP BY lt.id
            ORDER BY lt.name
        """, fetch=True)

        return render_template('payroll/leave/types.html', leave_types=leave_types_data or [])

    except Exception as e:
        flash(f'Error loading leave types: {str(e)}', 'error')
        return render_template('payroll/leave/types.html', leave_types=[])

@payroll_bp.route('/leave/types/add', methods=['GET', 'POST'])
@login_required
def add_leave_type():
    """Add new leave type"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            code = request.form.get('code')
            description = request.form.get('description')
            is_paid = request.form.get('is_paid') == 'on'
            requires_approval = request.form.get('requires_approval') == 'on'
            max_days_per_year = request.form.get('max_days_per_year')
            carry_forward_days = request.form.get('carry_forward_days')
            color = request.form.get('color', '#007bff')

            if not all([name, code]):
                flash('Name and code are required', 'error')
                return redirect(url_for('payroll.add_leave_type'))

            # Check if code already exists
            existing = execute_query_one("SELECT id FROM leave_types WHERE code = %s", (code,))
            if existing:
                flash('Leave type code already exists', 'error')
                return redirect(url_for('payroll.add_leave_type'))

            execute_query("""
                INSERT INTO leave_types (name, code, description, is_paid, requires_approval,
                                       max_days_per_year, carry_forward_days, color)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, code, description, is_paid, requires_approval,
                  max_days_per_year, carry_forward_days, color))

            flash('Leave type added successfully!', 'success')
            return redirect(url_for('payroll.leave_types'))

        except Exception as e:
            flash(f'Error adding leave type: {str(e)}', 'error')

    return render_template('payroll/leave/types/add.html')

@payroll_bp.route('/leave/types/edit/<type_id>', methods=['GET', 'POST'])
@login_required
def edit_leave_type(type_id):
    """Edit leave type"""
    try:
        leave_type = execute_query_one("SELECT * FROM leave_types WHERE id = %s", (type_id,))
        if not leave_type:
            flash('Leave type not found', 'error')
            return redirect(url_for('payroll.leave_types'))

        if request.method == 'POST':
            name = request.form.get('name')
            code = request.form.get('code')
            description = request.form.get('description')
            is_paid = request.form.get('is_paid') == 'on'
            requires_approval = request.form.get('requires_approval') == 'on'
            max_days_per_year = request.form.get('max_days_per_year')
            carry_forward_days = request.form.get('carry_forward_days')
            color = request.form.get('color', '#007bff')
            is_active = request.form.get('is_active') == 'on'

            if not all([name, code]):
                flash('Name and code are required', 'error')
                return redirect(url_for('payroll.edit_leave_type', type_id=type_id))

            # Check if code already exists (excluding current type)
            existing = execute_query_one("SELECT id FROM leave_types WHERE code = %s AND id != %s", (code, type_id))
            if existing:
                flash('Leave type code already exists', 'error')
                return redirect(url_for('payroll.edit_leave_type', type_id=type_id))

            execute_query("""
                UPDATE leave_types
                SET name = %s, code = %s, description = %s, is_paid = %s,
                    requires_approval = %s, max_days_per_year = %s,
                    carry_forward_days = %s, color = %s, is_active = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, code, description, is_paid, requires_approval,
                  max_days_per_year, carry_forward_days, color, is_active, type_id))

            flash('Leave type updated successfully!', 'success')
            return redirect(url_for('payroll.leave_types'))

        return render_template('payroll/leave/types/edit.html', leave_type=leave_type)

    except Exception as e:
        flash(f'Error loading leave type: {str(e)}', 'error')
        return redirect(url_for('payroll.leave_types'))

@payroll_bp.route('/leave/types/delete/<type_id>', methods=['POST'])
@login_required
def delete_leave_type(type_id):
    """Delete leave type"""
    try:
        # Check if leave type is being used
        usage_count = execute_query_one("""
            SELECT COUNT(*) as count FROM leave_requests WHERE leave_type_id = %s
        """, (type_id,))

        if usage_count and usage_count['count'] > 0:
            flash('Cannot delete leave type that is being used in leave requests', 'error')
            return redirect(url_for('payroll.leave_types'))

        execute_query("DELETE FROM leave_types WHERE id = %s", (type_id,))
        flash('Leave type deleted successfully!', 'success')

    except Exception as e:
        flash(f'Error deleting leave type: {str(e)}', 'error')

    return redirect(url_for('payroll.leave_types'))

@payroll_bp.route('/leave/holidays')
@login_required
def holidays():
    """Manage holidays"""
    try:
        holidays_data = execute_query("""
            SELECT h.*,
                   EXTRACT(YEAR FROM h.date) as year,
                   CASE
                       WHEN h.is_recurring THEN 'Recurring'
                       ELSE 'One-time'
                   END as type_label
            FROM holidays h
            ORDER BY h.date DESC
        """, fetch=True)

        # Group by year for display
        holidays_by_year = {}
        if holidays_data:
            for holiday in holidays_data:
                year = holiday['year']
                if year not in holidays_by_year:
                    holidays_by_year[year] = []
                holidays_by_year[year].append(holiday)

        return render_template('payroll/leave/holidays.html',
                             holidays=holidays_data or [],
                             holidays_by_year=holidays_by_year)

    except Exception as e:
        flash(f'Error loading holidays: {str(e)}', 'error')
        return render_template('payroll/leave/holidays.html', holidays=[], holidays_by_year={})

@payroll_bp.route('/leave/holidays/add', methods=['GET', 'POST'])
@login_required
def add_holiday():
    """Add new holiday"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            date = request.form.get('date')
            description = request.form.get('description')
            is_recurring = request.form.get('is_recurring') == 'on'

            if not all([name, date]):
                flash('Name and date are required', 'error')
                return redirect(url_for('payroll.add_holiday'))

            execute_query("""
                INSERT INTO holidays (name, date, description, is_recurring)
                VALUES (%s, %s, %s, %s)
            """, (name, date, description, is_recurring))

            flash('Holiday added successfully!', 'success')
            return redirect(url_for('payroll.holidays'))

        except Exception as e:
            flash(f'Error adding holiday: {str(e)}', 'error')

    return render_template('payroll/leave/holidays/add.html')

@payroll_bp.route('/leave/holidays/edit/<holiday_id>', methods=['GET', 'POST'])
@login_required
def edit_holiday(holiday_id):
    """Edit holiday"""
    try:
        holiday = execute_query_one("SELECT * FROM holidays WHERE id = %s", (holiday_id,))
        if not holiday:
            flash('Holiday not found', 'error')
            return redirect(url_for('payroll.holidays'))

        if request.method == 'POST':
            name = request.form.get('name')
            date = request.form.get('date')
            description = request.form.get('description')
            is_recurring = request.form.get('is_recurring') == 'on'
            is_active = request.form.get('is_active') == 'on'

            if not all([name, date]):
                flash('Name and date are required', 'error')
                return redirect(url_for('payroll.edit_holiday', holiday_id=holiday_id))

            execute_query("""
                UPDATE holidays
                SET name = %s, date = %s, description = %s,
                    is_recurring = %s, is_active = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, date, description, is_recurring, is_active, holiday_id))

            flash('Holiday updated successfully!', 'success')
            return redirect(url_for('payroll.holidays'))

        return render_template('payroll/leave/holidays/edit.html', holiday=holiday)

    except Exception as e:
        flash(f'Error loading holiday: {str(e)}', 'error')
        return redirect(url_for('payroll.holidays'))

@payroll_bp.route('/leave/holidays/delete/<holiday_id>', methods=['POST'])
@login_required
def delete_holiday(holiday_id):
    """Delete holiday"""
    try:
        execute_query("DELETE FROM holidays WHERE id = %s", (holiday_id,))
        flash('Holiday deleted successfully!', 'success')

    except Exception as e:
        flash(f'Error deleting holiday: {str(e)}', 'error')

    return redirect(url_for('payroll.holidays'))

@payroll_bp.route('/leave/holidays/generate/<year>', methods=['POST'])
@login_required
def generate_recurring_holidays(year):
    """Generate recurring holidays for a specific year"""
    try:
        # Get all recurring holidays
        recurring_holidays = execute_query("""
            SELECT name, EXTRACT(MONTH FROM date) as month, EXTRACT(DAY FROM date) as day, description
            FROM holidays
            WHERE is_recurring = TRUE AND is_active = TRUE
        """, fetch=True)

        if recurring_holidays:
            generated_count = 0
            for holiday in recurring_holidays:
                try:
                    holiday_date = f"{year}-{holiday['month']:02d}-{holiday['day']:02d}"

                    # Check if holiday already exists for this year
                    existing = execute_query_one("""
                        SELECT id FROM holidays
                        WHERE name = %s AND EXTRACT(YEAR FROM date) = %s
                    """, (holiday['name'], year))

                    if not existing:
                        execute_query("""
                            INSERT INTO holidays (name, date, description, is_recurring, is_active)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (holiday['name'], holiday_date, holiday['description'], True, True))
                        generated_count += 1

                except Exception as e:
                    # Skip invalid dates (like Feb 29 on non-leap years)
                    continue

            flash(f'Generated {generated_count} recurring holidays for {year}!', 'success')
        else:
            flash('No recurring holidays found to generate', 'warning')

    except Exception as e:
        flash(f'Error generating holidays: {str(e)}', 'error')

    return redirect(url_for('payroll.holidays'))

@payroll_bp.route('/leave/balances')
@login_required
def leave_balances():
    """Manage leave balances"""
    try:
        # Get all staff with their leave balances
        staff_with_balances = execute_query("""
            SELECT s.id, s.first_name, s.last_name, s.employee_id, s.email,
                   s.department_id, d.name as department_name,
                   COUNT(DISTINCT lb.leave_type_id) as leave_types_count,
                   SUM(lb.allocated_days) as total_allocated,
                   SUM(lb.used_days) as total_used,
                   SUM(lb.remaining_days) as total_remaining
            FROM staff s
            LEFT JOIN departments d ON s.department_id = d.id
            LEFT JOIN leave_balances lb ON s.id = lb.staff_id
            WHERE s.is_active = TRUE
            GROUP BY s.id, s.first_name, s.last_name, s.employee_id, s.email, s.department_id, d.name
            ORDER BY s.first_name, s.last_name
        """, fetch=True)

        return render_template('payroll/leave/balances.html',
                             staff_list=staff_with_balances or [])

    except Exception as e:
        flash(f'Error loading leave balances: {str(e)}', 'error')
        return render_template('payroll/leave/balances.html', staff_list=[])

@payroll_bp.route('/leave/balances/edit/<staff_id>')
@login_required
def edit_leave_balances_form(staff_id):
    """Get edit form for leave balances"""
    try:
        # Get staff information
        staff = execute_query_one("""
            SELECT s.*, d.name as department_name
            FROM staff s
            LEFT JOIN departments d ON s.department_id = d.id
            WHERE s.id = %s AND s.is_active = TRUE
        """, (staff_id,))

        if not staff:
            return '<div class="alert alert-danger">Employee not found</div>'

        # Get all active leave types
        leave_types = execute_query("""
            SELECT lt.id, lt.name, lt.code, lt.max_days_per_year, lt.carry_forward_days
            FROM leave_types lt
            WHERE lt.is_active = TRUE
            ORDER BY lt.name
        """, fetch=True)

        # Get current balances for this staff
        current_balances = {}
        if leave_types:
            balances = execute_query("""
                SELECT leave_type_id, allocated_days, used_days, remaining_days
                FROM leave_balances
                WHERE staff_id = %s
            """, (staff_id,), fetch=True)

            for balance in balances:
                current_balances[balance['leave_type_id']] = balance

        return render_template('payroll/leave/balances/edit.html',
                             staff=staff,
                             leave_types=leave_types or [],
                             current_balances=current_balances)

    except Exception as e:
        return f'<div class="alert alert-danger">Error loading balances: {str(e)}</div>'

@payroll_bp.route('/leave/balances/update/<staff_id>', methods=['POST'])
@login_required
def update_leave_balance(staff_id):
    """Update leave balance for a specific employee"""
    try:
        # Verify staff exists
        staff = execute_query_one("SELECT * FROM staff WHERE id = %s AND is_active = TRUE", (staff_id,))
        if not staff:
            flash('Employee not found', 'error')
            return redirect(url_for('payroll.leave_balances'))

        # Get all active leave types
        leave_types = execute_query("""
            SELECT lt.id, lt.name, lt.code, lt.max_days_per_year, lt.carry_forward_days
            FROM leave_types lt
            WHERE lt.is_active = TRUE
            ORDER BY lt.name
        """, fetch=True)

        if not leave_types:
            flash('No active leave types found', 'warning')
            return redirect(url_for('payroll.leave_balances'))

        updated_count = 0

        for leave_type in leave_types:
            allocated_days = request.form.get(f'allocated_{leave_type["id"]}')
            if allocated_days is not None:
                allocated_days = float(allocated_days) if allocated_days else 0

                # Check if balance already exists
                existing_balance = execute_query_one("""
                    SELECT id FROM leave_balances
                    WHERE staff_id = %s AND leave_type_id = %s
                """, (staff_id, leave_type['id']))

                if existing_balance:
                    # Update existing balance
                    execute_query("""
                        UPDATE leave_balances
                        SET allocated_days = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE staff_id = %s AND leave_type_id = %s
                    """, (allocated_days, staff_id, leave_type['id']))
                else:
                    # Create new balance
                    execute_query("""
                        INSERT INTO leave_balances (staff_id, leave_type_id, allocated_days, used_days, remaining_days)
                        VALUES (%s, %s, %s, 0, %s)
                    """, (staff_id, leave_type['id'], allocated_days, allocated_days))

                updated_count += 1

        flash(f'Updated leave balances for {staff["first_name"]} {staff["last_name"]}!', 'success')
        return redirect(url_for('payroll.leave_balances'))

    except Exception as e:
        flash(f'Error updating leave balance: {str(e)}', 'error')
        return redirect(url_for('payroll.leave_balances'))

@payroll_bp.route('/leave/balances/recalculate', methods=['POST'])
@login_required
def recalculate_leave_balances():
    """Recalculate all leave balances based on approved leave requests"""
    try:
        # Get all active staff
        staff_list = execute_query("SELECT id FROM staff WHERE is_active = TRUE", fetch=True)

        if not staff_list:
            flash('No active employees found', 'warning')
            return redirect(url_for('payroll.leave_balances'))

        total_updated = 0

        for staff in staff_list:
            staff_id = staff['id']

            # Get all active leave types
            leave_types = execute_query("SELECT id, name FROM leave_types WHERE is_active = TRUE", fetch=True)

            for leave_type in leave_types:
                leave_type_id = leave_type['id']

                # Calculate used days from approved leave requests
                used_days = execute_query_one("""
                    SELECT COALESCE(SUM(total_days), 0) as used_days
                    FROM leave_requests
                    WHERE staff_id = %s AND leave_type_id = %s AND status = 'approved'
                """, (staff_id, leave_type_id))

                used_days = used_days['used_days'] if used_days else 0

                # Get current allocated days
                current_balance = execute_query_one("""
                    SELECT allocated_days FROM leave_balances
                    WHERE staff_id = %s AND leave_type_id = %s
                """, (staff_id, leave_type_id))

                allocated_days = current_balance['allocated_days'] if current_balance else 0
                remaining_days = allocated_days - used_days

                # Update or create balance
                if current_balance:
                    execute_query("""
                        UPDATE leave_balances
                        SET used_days = %s, remaining_days = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE staff_id = %s AND leave_type_id = %s
                    """, (used_days, remaining_days, staff_id, leave_type_id))
                else:
                    # Only create balance if there are allocated days or used days
                    if allocated_days > 0 or used_days > 0:
                        execute_query("""
                            INSERT INTO leave_balances (staff_id, leave_type_id, allocated_days, used_days, remaining_days)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (staff_id, leave_type_id, allocated_days, used_days, remaining_days))

                total_updated += 1

        flash(f'Recalculated leave balances for {len(staff_list)} employees!', 'success')
        return redirect(url_for('payroll.leave_balances'))

    except Exception as e:
        flash(f'Error recalculating leave balances: {str(e)}', 'error')
        return redirect(url_for('payroll.leave_balances'))

@payroll_bp.route('/timesheets/bulk-approve', methods=['POST'])
@login_required
def bulk_approve_timesheets():
    """Bulk approve multiple timesheets"""
    try:
        timesheet_ids = request.form.getlist('timesheet_ids[]')
        approved_by = request.form.get('approved_by')

        if not timesheet_ids:
            flash('No timesheets selected', 'warning')
            return redirect(url_for('payroll.timesheets'))

        # Update multiple timesheets
        placeholders = ','.join(['%s'] * len(timesheet_ids))
        execute_query(f"""
            UPDATE timesheets
            SET status = 'approved', approved_by = %s, approved_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders}) AND status = 'draft'
        """, [approved_by] + timesheet_ids)

        flash(f'Approved {len(timesheet_ids)} timesheets!', 'success')
        return redirect(url_for('payroll.timesheets'))

    except Exception as e:
        flash(f'Error approving timesheets: {str(e)}', 'error')
        return redirect(url_for('payroll.timesheets'))

@payroll_bp.route('/timesheets/bulk-reject', methods=['POST'])
@login_required
def bulk_reject_timesheets():
    """Bulk reject multiple timesheets"""
    try:
        timesheet_ids = request.form.getlist('timesheet_ids[]')
        rejected_by = request.form.get('rejected_by')
        rejection_reason = request.form.get('rejection_reason', '')

        if not timesheet_ids:
            flash('No timesheets selected', 'warning')
            return redirect(url_for('payroll.timesheets'))

        # Update multiple timesheets
        placeholders = ','.join(['%s'] * len(timesheet_ids))
        execute_query(f"""
            UPDATE timesheets
            SET status = 'rejected', approved_by = %s, approved_at = CURRENT_TIMESTAMP,
                comments = %s
            WHERE id IN ({placeholders}) AND status = 'draft'
        """, [rejected_by, rejection_reason] + timesheet_ids)

        flash(f'Rejected {len(timesheet_ids)} timesheets!', 'warning')
        return redirect(url_for('payroll.timesheets'))

    except Exception as e:
        flash(f'Error rejecting timesheets: {str(e)}', 'error')
        return redirect(url_for('payroll.timesheets'))

@payroll_bp.route('/timesheets/<timesheet_id>/approve', methods=['POST'])
@login_required
def approve_timesheet(timesheet_id):
    """Approve a single timesheet"""
    try:
        approved_by = request.form.get('approved_by')

        execute_query("""
            UPDATE timesheets
            SET status = 'approved', approved_by = %s, approved_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'draft'
        """, (approved_by, timesheet_id))

        return jsonify({'success': True, 'message': 'Timesheet approved successfully!'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Reporting routes
@payroll_bp.route('/reports')
@login_required
def reports():
    """Reports index page"""
    return render_template('payroll/reports/index.html')

@payroll_bp.route('/reports/leave')
@login_required
def leave_reports():
    """Leave reports and analytics"""
    try:
        export = request.args.get('export')

        # Leave usage summary by type
        leave_usage = execute_query("""
            SELECT lt.name as leave_type_name, lt.color,
                   COUNT(lr.id) as total_requests,
                   COUNT(CASE WHEN lr.status = 'approved' THEN 1 END) as approved_requests,
                   SUM(CASE WHEN lr.status = 'approved' THEN lr.total_days ELSE 0 END) as total_days_taken,
                   AVG(CASE WHEN lr.status = 'approved' THEN lr.total_days ELSE NULL END) as avg_days_per_request
            FROM leave_types lt
            LEFT JOIN leave_requests lr ON lt.id = lr.leave_type_id
            WHERE lt.is_active = TRUE
            GROUP BY lt.id, lt.name, lt.color
            ORDER BY total_days_taken DESC NULLS LAST
        """, fetch=True)

        # Leave requests by month (last 12 months)
        monthly_leave = execute_query("""
            SELECT
                TO_CHAR(lr.created_at, 'YYYY-MM') as month,
                TO_CHAR(lr.created_at, 'Month YYYY') as month_name,
                COUNT(lr.id) as total_requests,
                COUNT(CASE WHEN lr.status = 'approved' THEN 1 END) as approved_requests,
                SUM(CASE WHEN lr.status = 'approved' THEN lr.total_days ELSE 0 END) as total_days
            FROM leave_requests lr
            WHERE lr.created_at >= CURRENT_DATE - INTERVAL '12 months'
            GROUP BY TO_CHAR(lr.created_at, 'YYYY-MM'), TO_CHAR(lr.created_at, 'Month YYYY')
            ORDER BY month DESC
        """, fetch=True)

        # Department leave usage
        dept_leave = execute_query("""
            SELECT d.name as department_name,
                   COUNT(lr.id) as total_requests,
                   COUNT(CASE WHEN lr.status = 'approved' THEN 1 END) as approved_requests,
                   SUM(CASE WHEN lr.status = 'approved' THEN lr.total_days ELSE 0 END) as total_days_taken
            FROM departments d
            LEFT JOIN staff s ON d.id = s.department_id
            LEFT JOIN leave_requests lr ON s.id = lr.staff_id
            GROUP BY d.id, d.name
            ORDER BY total_days_taken DESC NULLS LAST
        """, fetch=True)

        if export == 'csv':
            import csv
            import io

            total_requests = sum([(u['total_requests'] or 0) for u in leave_usage]) if leave_usage else 0
            total_approved = sum([(u['approved_requests'] or 0) for u in leave_usage]) if leave_usage else 0
            total_days = sum([(u['total_days_taken'] or 0) for u in leave_usage]) if leave_usage else 0
            approval_rate = (total_approved / total_requests * 100) if total_requests else 0

            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow(['Leave Analytics Report'])
            writer.writerow(['Generated On', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
            writer.writerow([''])

            writer.writerow(['Summary'])
            writer.writerow(['Total Requests', total_requests])
            writer.writerow(['Total Approved', total_approved])
            writer.writerow(['Total Days Taken', f"{total_days:.1f}"])
            writer.writerow(['Approval Rate', f"{approval_rate:.2f}%"])
            writer.writerow([''])

            writer.writerow(['Leave Usage by Type'])
            writer.writerow(['Leave Type', 'Total Requests', 'Approved Requests', 'Total Days Taken', 'Avg Days/Request', 'Approval Rate %'])
            if leave_usage:
                for usage in leave_usage:
                    total_req = usage['total_requests'] or 0
                    approved_req = usage['approved_requests'] or 0
                    days_taken = usage['total_days_taken'] or 0
                    avg_days = usage['avg_days_per_request'] or 0
                    rate = (approved_req / total_req * 100) if total_req else 0
                    writer.writerow([
                        usage['leave_type_name'],
                        total_req,
                        approved_req,
                        f"{days_taken:.1f}",
                        f"{avg_days:.1f}",
                        f"{rate:.2f}"
                    ])
            writer.writerow([''])

            writer.writerow(['Monthly Leave Trends (Last 12 Months)'])
            writer.writerow(['Month', 'Total Requests', 'Approved', 'Total Days', 'Approval Rate %'])
            if monthly_leave:
                for month in monthly_leave:
                    total_req = month['total_requests'] or 0
                    approved_req = month['approved_requests'] or 0
                    days_taken = month['total_days'] or 0
                    rate = (approved_req / total_req * 100) if total_req else 0
                    writer.writerow([
                        month['month_name'],
                        total_req,
                        approved_req,
                        f"{days_taken:.1f}",
                        f"{rate:.2f}"
                    ])
            writer.writerow([''])

            writer.writerow(['Department Leave Usage'])
            writer.writerow(['Department', 'Total Requests', 'Approved Requests', 'Total Days Taken'])
            if dept_leave:
                for dept in dept_leave:
                    writer.writerow([
                        dept['department_name'],
                        dept['total_requests'] or 0,
                        dept['approved_requests'] or 0,
                        f"{(dept['total_days_taken'] or 0):.1f}"
                    ])

            output.seek(0)
            response = current_app.response_class(
                output.getvalue(),
                mimetype='application/vnd.ms-excel',
                direct_passthrough=True
            )
            filename = f"leave-analytics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            return response

        return render_template('payroll/reports/leave.html',
                             leave_usage=leave_usage or [],
                             monthly_leave=monthly_leave or [],
                             dept_leave=dept_leave or [])

    except Exception as e:
        flash(f'Error loading leave reports: {str(e)}', 'error')
        return render_template('payroll/reports/leave.html', leave_usage=[], monthly_leave=[], dept_leave=[])

@payroll_bp.route('/reports/timesheets')
@login_required
def timesheet_reports():
    """Timesheet reports and analytics"""
    try:
        # Timesheet summary by month
        monthly_hours = execute_query("""
            SELECT
                TO_CHAR(t.date, 'YYYY-MM') as month,
                TO_CHAR(t.date, 'Month YYYY') as month_name,
                COUNT(DISTINCT t.id) as total_entries,
                COUNT(DISTINCT t.staff_id) as active_employees,
                SUM(t.total_hours) as total_hours,
                AVG(t.total_hours) as avg_hours_per_entry,
                SUM(t.regular_hours) as regular_hours,
                SUM(t.break_hours) as break_hours
            FROM timesheets t
            WHERE t.date >= CURRENT_DATE - INTERVAL '12 months'
            GROUP BY TO_CHAR(t.date, 'YYYY-MM'), TO_CHAR(t.date, 'Month YYYY')
            ORDER BY month DESC
        """, fetch=True)

        # Department hours summary
        dept_hours = execute_query("""
            SELECT d.name as department_name,
                   COUNT(DISTINCT t.id) as total_entries,
                   COUNT(DISTINCT t.staff_id) as employees,
                   SUM(t.total_hours) as total_hours,
                   AVG(t.total_hours) as avg_hours_per_entry
            FROM departments d
            LEFT JOIN staff s ON d.id = s.department_id
            LEFT JOIN timesheets t ON s.id = t.staff_id
            WHERE t.date >= CURRENT_DATE - INTERVAL '3 months'
            GROUP BY d.id, d.name
            ORDER BY total_hours DESC NULLS LAST
        """, fetch=True)

        # Weekly hours trend (last 12 weeks)
        weekly_trend = execute_query("""
            SELECT
                TO_CHAR(t.date, 'IYYY-IW') as week,
                TO_CHAR(t.date, 'Mon DD, YYYY') as week_start,
                COUNT(DISTINCT t.id) as entries,
                SUM(t.total_hours) as total_hours,
                AVG(t.total_hours) as avg_hours
            FROM timesheets t
            WHERE t.date >= CURRENT_DATE - INTERVAL '12 weeks'
            GROUP BY TO_CHAR(t.date, 'IYYY-IW'), TO_CHAR(t.date, 'Mon DD, YYYY')
            ORDER BY week DESC
        """, fetch=True)

        return render_template('payroll/reports/timesheets.html',
                             monthly_hours=monthly_hours or [],
                             dept_hours=dept_hours or [],
                             weekly_trend=weekly_trend or [])

    except Exception as e:
        flash(f'Error loading timesheet reports: {str(e)}', 'error')
        return render_template('payroll/reports/timesheets.html', monthly_hours=[], dept_hours=[], weekly_trend=[])

# Payroll processing routes
@payroll_bp.route('/payroll-cycles', methods=['GET', 'POST'])
@login_required
def payroll_cycles():
    """List payroll cycles or create new one"""
    if request.method == 'POST':
        try:
            # Create new payroll cycle
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            cycle_name = request.form.get('cycle_name')

            if not all([start_date, end_date, cycle_name]):
                flash('All fields are required', 'error')
                return redirect(url_for('payroll.payroll_cycles'))

            # Check for overlapping cycles
            overlapping = execute_query_one("""
                SELECT id FROM payroll_cycles
                WHERE (start_date <= %s AND end_date >= %s)
                   OR (start_date <= %s AND end_date >= %s)
                   OR (start_date >= %s AND end_date <= %s)
            """, (end_date, start_date, start_date, end_date, start_date, end_date))

            if overlapping:
                flash('Payroll cycle dates overlap with existing cycle', 'error')
                return redirect(url_for('payroll.payroll_cycles'))

            cycle_id = str(uuid.uuid4())
            execute_query("""
                INSERT INTO payroll_cycles (id, name, start_date, end_date, status)
                VALUES (%s, %s, %s, %s, 'draft')
            """, (cycle_id, cycle_name, start_date, end_date))

            flash('Payroll cycle created successfully!', 'success')
            return redirect(url_for('payroll.payroll_cycles'))

        except Exception as e:
            flash(f'Error creating payroll cycle: {str(e)}', 'error')

    try:
        # Get all payroll cycles
        cycles = execute_query("""
            SELECT pc.*,
                   COUNT(p.id) as entries_count,
                   COALESCE(SUM(p.gross_pay), 0) as total_payroll,
                   COALESCE(SUM(p.net_pay), 0) as total_net_pay
            FROM payroll_cycles pc
            LEFT JOIN payroll_entries p ON pc.id = p.payroll_cycle_id
            GROUP BY pc.id
            ORDER BY pc.created_at DESC
        """, fetch=True)

        return render_template('payroll/payroll_cycles/index.html', cycles=cycles or [])

    except Exception as e:
        flash(f'Error loading payroll cycles: {str(e)}', 'error')
        return render_template('payroll/payroll_cycles/index.html', cycles=[])

@payroll_bp.route('/payroll-cycles/<cycle_id>')
@login_required
def view_payroll_cycle(cycle_id):
    """View detailed payroll cycle"""
    try:
        # Get cycle details
        cycle = execute_query_one("""
            SELECT * FROM payroll_cycles WHERE id = %s
        """, (cycle_id,))

        if not cycle:
            flash('Payroll cycle not found', 'error')
            return redirect(url_for('payroll.payroll_cycles'))

        # Get payroll entries for this cycle
        payroll_entries = execute_query("""
            SELECT p.*,
                   s.first_name, s.last_name, s.employee_id, s.email,
                   d.name as department_name,
                   pc.name as cycle_name
            FROM payroll_entries p
            JOIN staff s ON p.staff_id = s.id
            LEFT JOIN departments d ON s.department_id = d.id
            JOIN payroll_cycles pc ON p.payroll_cycle_id = pc.id
            WHERE p.payroll_cycle_id = %s
            ORDER BY s.first_name, s.last_name
        """, (cycle_id,), fetch=True)

        # Calculate totals
        totals = {
            'employees': len(payroll_entries) if payroll_entries else 0,
            'gross_pay': sum([p['gross_pay'] for p in payroll_entries]) if payroll_entries else 0,
            'net_pay': sum([p['net_pay'] for p in payroll_entries]) if payroll_entries else 0,
            'deductions': sum([p['gross_pay'] - p['net_pay'] for p in payroll_entries]) if payroll_entries else 0
        }

        return render_template('payroll/payroll_cycle_detail.html',
                             cycle=cycle,
                             payroll_entries=payroll_entries or [],
                             totals=totals)

    except Exception as e:
        flash(f'Error loading payroll cycle: {str(e)}', 'error')
        return redirect(url_for('payroll.payroll_cycles'))

def _run_payroll_processing(cycle_id):
    """Internal helper that processes a payroll cycle and returns (success, message)."""
    try:
        # Get cycle details
        cycle = execute_query_one("""
            SELECT * FROM payroll_cycles WHERE id = %s AND status = 'draft'
        """, (cycle_id,))

        if not cycle:
            return False, 'Payroll cycle not found or already processed.'

        # Get all active staff
        staff_list = execute_query("""
            SELECT s.id, s.first_name, s.last_name, s.employee_id,
                   COALESCE(s.hourly_rate, 15.00) as hourly_rate
            FROM staff s
            WHERE s.is_active = TRUE
            ORDER BY s.first_name, s.last_name
        """, fetch=True)

        if not staff_list:
            return False, 'No active employees found.'

        processed_count = 0

        for staff in staff_list:
            staff_id = staff['id']

            # Calculate hours worked in this cycle
            hours_worked = execute_query_one("""
                SELECT COALESCE(SUM(total_hours), 0) as hours
            FROM timesheets
                WHERE staff_id = %s
                  AND date >= %s
                  AND date <= %s
                  AND status = 'approved'
            """, (staff_id, cycle['start_date'], cycle['end_date']))

            hours = hours_worked['hours'] if hours_worked else 0

            if hours > 0:
                # Calculate pay
                hourly_rate = float(staff['hourly_rate'])
                gross_pay = hours * hourly_rate

                # Calculate deductions (simple example - 10% tax, 5% insurance)
                tax_deduction = gross_pay * 0.10
                insurance_deduction = gross_pay * 0.05
                total_deductions = tax_deduction + insurance_deduction
                net_pay = gross_pay - total_deductions

                # Check if payroll entry already exists
                existing = execute_query_one("""
                    SELECT id FROM payroll
                    WHERE staff_id = %s AND payroll_cycle_id = %s
                """, (staff_id, cycle_id))

                if existing:
                    # Update existing entry
                    execute_query("""
                        UPDATE payroll
                        SET hours_worked = %s, hourly_rate = %s, gross_pay = %s,
                            deductions = %s, net_pay = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE staff_id = %s AND payroll_cycle_id = %s
                    """, (hours, hourly_rate, gross_pay, total_deductions, net_pay, staff_id, cycle_id))
                else:
                    # Create new payroll entry
                    payroll_id = str(uuid.uuid4())
                    execute_query("""
                        INSERT INTO payroll (id, staff_id, payroll_cycle_id, hours_worked,
                                           hourly_rate, gross_pay, deductions, net_pay)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (payroll_id, staff_id, cycle_id, hours, hourly_rate, gross_pay,
                          total_deductions, net_pay))

                processed_count += 1

        # Update cycle status
        execute_query("""
            UPDATE payroll_cycles
            SET status = 'processed', processed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (cycle_id,))

        return True, f'Payroll processed for {processed_count} employees!'

    except Exception as e:
        return False, f'Error processing payroll: {str(e)}'


@payroll_bp.route('/payroll-cycles/<cycle_id>/process', methods=['POST'])
@login_required
def process_payroll_cycle(cycle_id):
    """Process payroll for a specific cycle via standard form submission."""
    success, message = _run_payroll_processing(cycle_id)
    flash(message, 'success' if success else 'error')

    if success:
        return redirect(url_for('payroll.view_payroll_cycle', cycle_id=cycle_id))
    return redirect(url_for('payroll.payroll_cycles'))


@payroll_bp.route('/process-payroll', methods=['POST'])
@login_required
def process_payroll():
    """Process the next available payroll cycle (used by the dashboard button)."""
    payload = request.get_json(silent=True) or {}
    cycle_id = payload.get('cycle_id')

    if not cycle_id:
        next_cycle = execute_query_one("""
            SELECT id FROM payroll_cycles
            WHERE status = 'draft'
            ORDER BY start_date ASC
            LIMIT 1
        """)
        if not next_cycle:
            return jsonify({
                'success': False,
                'message': 'No draft payroll cycles available to process.'
            }), 404
        cycle_id = next_cycle['id']

    success, message = _run_payroll_processing(cycle_id)
    status_code = 200 if success else 400

    return jsonify({
        'success': success,
        'message': message,
        'cycle_id': cycle_id
    }), status_code