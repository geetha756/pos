from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import execute_query, execute_query_one
from .auth import login_required
import psycopg2

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    """Main dashboard page"""
    try:
        # Get dashboard statistics
        stats = get_dashboard_stats()
        return render_template('dashboard.html', stats=stats)
    except Exception as e:
        flash(f'Database error: {str(e)}', 'error')
        return render_template('dashboard.html', stats={'locations': 0, 'menu_items': 0, 'orders': 0, 'total_revenue': 0.0})


def get_dashboard_stats():
    """Get dashboard statistics"""
    stats = {
        'locations': 0,
        'menu_items': 0,
        'orders': 0,
        'total_revenue': 0.0,
        'pending_orders': 0,
        'today_orders': 0,
        'staff': 0,
        'active_staff': 0,
        'departments': 0,
        'positions': 0,
        'total_employees': 0,
        'active_timesheets': 0,
        'pending_leave_requests': 0,
        'total_payroll_expense': 0.0,
        # Users & Access
        'users': 0,
        'active_users': 0,
        # Inventory
        'total_master_items': 0,
        'low_stock_items': 0,
        'active_purchase_lists': 0,
        'suppliers': 0
    }

    try:
        # Count locations
        result = execute_query_one("SELECT COUNT(*) as count FROM locations")
        stats['locations'] = result['count'] if result else 0

        # Count master menu items
        result = execute_query_one("SELECT COUNT(*) as count FROM master_menu WHERE is_active = TRUE")
        stats['menu_items'] = result['count'] if result else 0

        # Count total orders
        result = execute_query_one("SELECT COUNT(*) as count FROM orders")
        stats['orders'] = result['count'] if result else 0

        # Total revenue
        result = execute_query_one("SELECT COALESCE(SUM(total_amount), 0) as total FROM orders WHERE status != 'cancelled'")
        stats['total_revenue'] = float(result['total']) if result else 0.0

        # Pending orders
        result = execute_query_one("SELECT COUNT(*) as count FROM orders WHERE status IN ('pending', 'preparing')")
        stats['pending_orders'] = result['count'] if result else 0

        # Today's orders
        result = execute_query_one("SELECT COUNT(*) as count FROM orders WHERE DATE(created_at) = CURRENT_DATE")
        stats['today_orders'] = result['count'] if result else 0

        # Total staff count
        result = execute_query_one("SELECT COUNT(*) as count FROM staff")
        stats['staff'] = result['count'] if result else 0

        # Active staff count
        result = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE is_active = TRUE")
        stats['active_staff'] = result['count'] if result else 0

        # Department count
        result = execute_query_one("SELECT COUNT(*) as count FROM departments WHERE is_active = TRUE")
        stats['departments'] = result['count'] if result else 0

        # Position count
        result = execute_query_one("SELECT COUNT(*) as count FROM positions WHERE is_active = TRUE")
        stats['positions'] = result['count'] if result else 0

        # Users & Access statistics
        result = execute_query_one("SELECT COUNT(*) as count FROM users")
        stats['users'] = result['count'] if result else 0

        result = execute_query_one("SELECT COUNT(*) as count FROM users WHERE is_active = TRUE")
        stats['active_users'] = result['count'] if result else 0

        # Payroll statistics
        # Total employees (from staff table)
        result = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE is_active = TRUE")
        stats['total_employees'] = result['count'] if result else 0

        # Active timesheets (draft or submitted this week)
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM timesheets
            WHERE date >= CURRENT_DATE - INTERVAL '7 days'
            AND status IN ('draft', 'submitted')
        """)
        stats['active_timesheets'] = result['count'] if result else 0

        # Pending leave requests
        result = execute_query_one("SELECT COUNT(*) as count FROM leave_requests WHERE status = 'pending'")
        stats['pending_leave_requests'] = result['count'] if result else 0

        # Total payroll expense (last 30 days)
        result = execute_query_one("""
            SELECT COALESCE(SUM(net_pay), 0) as total FROM payroll_entries pe
            JOIN payroll_cycles pc ON pe.payroll_cycle_id = pc.id
            WHERE pc.end_date >= CURRENT_DATE - INTERVAL '30 days'
            AND pe.status = 'paid'
        """)
        stats['total_payroll_expense'] = result['total'] if result else 0.0

        # Inventory statistics
        result = execute_query_one("SELECT COUNT(*) as count FROM master_inventory WHERE is_active = TRUE")
        stats['total_master_items'] = result['count'] if result else 0

        result = execute_query_one("""
            SELECT COUNT(*) as count FROM location_inventory
            WHERE current_stock <= reorder_point
        """)
        stats['low_stock_items'] = result['count'] if result else 0

        result = execute_query_one("""
            SELECT COUNT(*) as count FROM purchase_lists
            WHERE status IN ('draft', 'submitted', 'approved')
        """)
        stats['active_purchase_lists'] = result['count'] if result else 0

        result = execute_query_one("SELECT COUNT(*) as count FROM suppliers WHERE is_active = TRUE")
        stats['suppliers'] = result['count'] if result else 0

    except Exception as e:
        print(f"Error getting dashboard stats: {e}")

    return stats
