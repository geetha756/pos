from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one
import psycopg2
import uuid
import json

orders_bp = Blueprint('orders', __name__)

@orders_bp.route('/')
def index():
    """List all orders from all locations"""
    try:
        # Get filter parameters
        location_filter = request.args.get('location', '')
        status_filter = request.args.get('status', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        # Build query with filters
        query = """
            SELECT o.id, o.order_number, o.customer_name, o.customer_phone, o.order_type,
                   o.status, o.total_amount, o.created_at, o.updated_at,
                   l.name as location_name, l.city as location_city
            FROM orders o
            LEFT JOIN locations l ON o.location_id = l.id
            WHERE 1=1
        """
        params = []

        if location_filter:
            query += " AND o.location_id = %s"
            params.append(location_filter)

        if status_filter:
            query += " AND o.status = %s"
            params.append(status_filter)

        if date_from:
            query += " AND DATE(o.created_at) >= %s"
            params.append(date_from)

        if date_to:
            query += " AND DATE(o.created_at) <= %s"
            params.append(date_to)

        query += " ORDER BY o.created_at DESC"

        orders = execute_query(query, params, fetch=True)

        # Get locations for filter dropdown
        locations = execute_query("SELECT id, name, city FROM locations ORDER BY name", fetch=True)

        # Get order statistics
        stats = get_order_stats()

        return render_template('orders/index.html',
                             orders=orders or [],
                             locations=locations or [],
                             stats=stats,
                             filters={
                                 'location': location_filter,
                                 'status': status_filter,
                                 'date_from': date_from,
                                 'date_to': date_to
                             })

    except Exception as e:
        flash(f'Error loading orders: {str(e)}', 'error')
        return render_template('orders/index.html', orders=[], locations=[], stats={
            'total_orders': 0,
            'total_revenue': 0.0,
            'pending_orders': 0,
            'completed_orders': 0,
            'today_orders': 0,
            'today_revenue': 0.0
        }, filters={})

@orders_bp.route('/<order_id>')
def view(order_id):
    """View order details"""
    try:
        # Get order info
        order = execute_query_one("""
            SELECT o.*, l.name as location_name, l.city as location_city,
                   l.address as location_address
            FROM orders o
            LEFT JOIN locations l ON o.location_id = l.id
            WHERE o.id = %s
        """, (order_id,))

        if not order:
            flash('Order not found', 'error')
            return redirect(url_for('orders.index'))

        # Get order items
        order_items = execute_query("""
            SELECT oi.*, lm.price as location_price
            FROM order_items oi
            LEFT JOIN location_menu lm ON oi.location_menu_id = lm.id
            WHERE oi.order_id = %s
            ORDER BY oi.id
        """, (order_id,), fetch=True)

        return render_template('orders/view.html',
                             order=order,
                             order_items=order_items or [])

    except Exception as e:
        flash(f'Error loading order details: {str(e)}', 'error')
        return redirect(url_for('orders.index'))

@orders_bp.route('/<order_id>/status', methods=['POST'])
def update_status(order_id):
    """Update order status"""
    new_status = request.form.get('status')

    if new_status not in ['pending', 'preparing', 'ready', 'completed', 'cancelled']:
        flash('Invalid status', 'error')
        return redirect(url_for('orders.view', order_id=order_id))

    try:
        # Check if order exists
        existing_order = execute_query_one("SELECT id, status FROM orders WHERE id = %s", (order_id,))

        if not existing_order:
            flash('Order not found', 'error')
            return redirect(url_for('orders.index'))

        # Update the order status
        execute_query("""
            UPDATE orders
            SET status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_status, order_id))

        flash('Order status updated!', 'success')
    except Exception as e:
        flash(f'Error updating order status: {str(e)}', 'error')

    return redirect(url_for('orders.view', order_id=order_id))

@orders_bp.route('/stats')
def stats():
    """Get order statistics via AJAX"""
    try:
        stats = get_order_stats()
        return {'success': True, 'stats': stats}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_order_stats():
    """Get order statistics"""
    stats = {
        'total_orders': 0,
        'total_revenue': 0.0,
        'pending_orders': 0,
        'completed_orders': 0,
        'today_orders': 0,
        'today_revenue': 0.0
    }

    try:
        # Total orders and revenue
        result = execute_query_one("""
            SELECT COUNT(*) as count, COALESCE(SUM(total_amount), 0) as revenue
            FROM orders
            WHERE status != 'cancelled'
        """)
        if result:
            stats['total_orders'] = result['count']
            stats['total_revenue'] = float(result['revenue'])

        # Pending orders
        result = execute_query_one("""
            SELECT COUNT(*) as count
            FROM orders
            WHERE status IN ('pending', 'preparing')
        """)
        stats['pending_orders'] = result['count'] if result else 0

        # Completed orders
        result = execute_query_one("""
            SELECT COUNT(*) as count
            FROM orders
            WHERE status = 'completed'
        """)
        stats['completed_orders'] = result['count'] if result else 0

        # Today's stats
        result = execute_query_one("""
            SELECT COUNT(*) as count, COALESCE(SUM(total_amount), 0) as revenue
            FROM orders
            WHERE DATE(created_at) = CURRENT_DATE AND status != 'cancelled'
        """)
        if result:
            stats['today_orders'] = result['count']
            stats['today_revenue'] = float(result['revenue'])

    except Exception as e:
        print(f"Error getting order stats: {e}")

    return stats

@orders_bp.route('/api/create', methods=['POST'])
def api_create_order():
    """API endpoint to create a new order"""
    try:
        data = request.get_json()

        # Validate required fields
        required_fields = ['location_id', 'items']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400

        if not data['items']:
            return jsonify({'success': False, 'error': 'Order must contain at least one item'}), 400

        # Generate order number (simple timestamp-based for now)
        import time
        order_number = f"ORD{int(time.time())}"

        # Calculate total amount
        total_amount = sum(item['total_price'] for item in data['items'])

        # Create order
        order_id = str(uuid.uuid4())
        execute_query("""
            INSERT INTO orders (id, location_id, order_number, customer_name, customer_phone,
                              customer_email, order_type, total_amount, notes, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        """, (
            order_id,
            data['location_id'],
            order_number,
            None,  # No customer name
            None,  # No customer phone
            None,  # No customer email
            'dine-in',  # Default order type
            total_amount,
            None  # No notes
        ))

        # Add order items
        for item in data['items']:
            item_id = str(uuid.uuid4())
            execute_query("""
                INSERT INTO order_items (id, order_id, location_menu_id, master_menu_id,
                                       item_name, quantity, unit_price, total_price, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                item_id,
                order_id,
                item['location_menu_id'],
                item['master_menu_id'],
                item['item_name'],
                item['quantity'],
                item['unit_price'],
                item['total_price'],
                'Parcel' if item.get('is_parcel') else None
            ))

        return jsonify({
            'success': True,
            'order_id': order_id,
            'order_number': order_number,
            'message': 'Order created successfully'
        })

    except Exception as e:
        print(f"Error creating order: {e}")
        return jsonify({'success': False, 'error': 'Failed to create order'}), 500
