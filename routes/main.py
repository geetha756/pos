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
        'today_orders': 0
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

    except Exception as e:
        print(f"Error getting dashboard stats: {e}")

    return stats
