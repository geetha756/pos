from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one, execute_transaction
from .auth import login_required
from security import scoped_location_id, get_or_create_current_user
import psycopg2
import uuid
import json

orders_bp = Blueprint('orders', __name__)


@orders_bp.route('/new')
@login_required
def new_order():
    """Point-of-sale screen: the manager picks a location, then builds and
    places an order from that location's menu. Submits to /orders/api/create."""
    try:
        locations = execute_query(
            "SELECT id, name, city FROM locations ORDER BY name", fetch=True
        ) or []

        selected_location = request.args.get('location', '')
        # A store-scoped manager is locked to their own store.
        store = scoped_location_id()
        if store:
            selected_location = store
        menu_items = []
        if selected_location:
            menu_items = execute_query(
                """
                SELECT lm.id AS location_menu_id,
                       lm.master_menu_id,
                       mm.name,
                       mm.category,
                       mm.image_data,
                       lm.price,
                       COALESCE(lm.section, 'all') AS section
                FROM location_menu lm
                JOIN master_menu mm ON mm.id = lm.master_menu_id
                WHERE lm.location_id = %s
                  AND lm.is_available = TRUE
                  AND mm.is_active = TRUE
                ORDER BY mm.category NULLS LAST, mm.name
                """,
                (selected_location,),
                fetch=True,
            ) or []

        return render_template(
            'orders/new.html',
            locations=locations,
            menu_items=menu_items,
            selected_location=selected_location,
        )
    except Exception as e:
        flash(f'Error loading order screen: {str(e)}', 'error')
        return render_template('orders/new.html', locations=[], menu_items=[], selected_location='')


@orders_bp.route('/<order_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_order(order_id):
    """Edit an already-placed order. Saving marks the order as edited so the
    admin sees an 'Edited' marker. Store-scoped managers can only edit their
    own store's orders."""
    order = execute_query_one("SELECT * FROM orders WHERE id = %s", (order_id,))
    if not order:
        if request.method == 'POST':
            return jsonify({'success': False, 'error': 'Order not found'}), 404
        flash('Order not found', 'error')
        return redirect(url_for('orders.index'))

    store = scoped_location_id()
    if store and str(order['location_id']) != store:
        if request.method == 'POST':
            return jsonify({'success': False, 'error': "You can only edit your own store's orders"}), 403
        flash("You can only edit your own store's orders", 'error')
        return redirect(url_for('orders.index'))

    if request.method == 'POST':
        data = request.get_json() or {}
        items = data.get('items') or []
        if not items:
            return jsonify({'success': False, 'error': 'Order must contain at least one item'}), 400
        try:
            total_amount = sum(item['total_price'] for item in items)
            customer_name = (data.get('customer_name') or '').strip() or None
            customer_phone = (data.get('customer_phone') or '').strip() or None
            order_type = data.get('order_type') or order.get('order_type') or 'dine-in'
            user = get_or_create_current_user()
            editor = user['id'] if user else None

            # Replace the order's items with the edited set
            execute_query("DELETE FROM order_items WHERE order_id = %s", (order_id,))
            for item in items:
                execute_query("""
                    INSERT INTO order_items (id, order_id, location_menu_id, master_menu_id,
                                           item_name, quantity, unit_price, total_price)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    str(uuid.uuid4()), order_id, item['location_menu_id'], item['master_menu_id'],
                    item['item_name'], item['quantity'], item['unit_price'], item['total_price']
                ))

            execute_query("""
                UPDATE orders
                SET customer_name = %s, customer_phone = %s, order_type = %s,
                    total_amount = %s, edited_at = CURRENT_TIMESTAMP, edited_by = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (customer_name, customer_phone, order_type, total_amount, editor, order_id))

            return jsonify({'success': True, 'order_id': order_id})
        except Exception as e:
            print(f"Error editing order: {e}")
            return jsonify({'success': False, 'error': 'Failed to save order'}), 500

    # GET: render the edit screen (current items pre-loaded + the store's menu)
    items = execute_query(
        "SELECT location_menu_id, master_menu_id, item_name, quantity, unit_price, total_price "
        "FROM order_items WHERE order_id = %s", (order_id,), fetch=True
    ) or []
    menu_items = execute_query("""
        SELECT lm.id AS location_menu_id, lm.master_menu_id, mm.name, mm.category, lm.price
        FROM location_menu lm
        JOIN master_menu mm ON mm.id = lm.master_menu_id
        WHERE lm.location_id = %s AND lm.is_available = TRUE AND mm.is_active = TRUE
        ORDER BY mm.category NULLS LAST, mm.name
    """, (str(order['location_id']),), fetch=True) or []
    return render_template('orders/edit_order.html', order=order, items=items, menu_items=menu_items)


@orders_bp.route('/')
@login_required
def index():
    """List all orders from all locations"""
    try:
        # Get filter parameters
        location_filter = request.args.get('location', '')
        status_filter = request.args.get('status', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')

        # A store-scoped manager can only ever see their own location.
        store = scoped_location_id()
        if store:
            location_filter = store
        else:
            # Orders page is locked to Amaravathi only — no cross-location
            # view and no "All Locations" option for any role.
            amaravathi = execute_query_one("SELECT id FROM locations WHERE name = %s", ('Amaravathi',))
            if amaravathi:
                location_filter = str(amaravathi['id'])

        # Shared WHERE clause for both the count and the page query.
        where = " WHERE 1=1"
        params = []
        if location_filter:
            where += " AND o.location_id = %s"; params.append(location_filter)
        if status_filter:
            where += " AND o.status = %s"; params.append(status_filter)
        # created_at is stored in UTC; compare on the IST calendar date (UTC+5:30)
        # so a date range matches what the manager sees on the clock.
        if date_from:
            where += " AND DATE(o.created_at + INTERVAL '5 hours 30 minutes') >= %s"; params.append(date_from)
        if date_to:
            where += " AND DATE(o.created_at + INTERVAL '5 hours 30 minutes') <= %s"; params.append(date_to)

        # Pagination — never load the whole table (it grows forever in a busy store).
        try:
            page = max(1, int(request.args.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        per_page = 50
        total = (execute_query_one("SELECT COUNT(*) AS c FROM orders o" + where, tuple(params)) or {}).get('c', 0)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)

        query = ("""
            SELECT o.id, o.order_number, o.customer_name, o.customer_phone, o.order_type,
                   o.status, o.total_amount, o.created_at, o.updated_at, o.edited_at, o.payment_method,
                   l.name as location_name, l.city as location_city
            FROM orders o
            LEFT JOIN locations l ON o.location_id = l.id"""
            + where + " ORDER BY o.created_at DESC LIMIT %s OFFSET %s")
        orders = execute_query(query, tuple(params) + (per_page, (page - 1) * per_page), fetch=True)

        # Get locations for filter dropdown — locked to a single location
        # (the store manager's own store, or Amaravathi), never "All Locations".
        locations = execute_query("SELECT id, name, city FROM locations WHERE id = %s", (location_filter,), fetch=True) if location_filter else []

        # Stats follow the selected date range (default: today).
        stats = get_order_stats(location_filter, date_from, date_to)

        return render_template('orders/index.html',
                             orders=orders or [],
                             locations=locations or [],
                             stats=stats,
                             page=page, total_pages=total_pages, total_orders=total,
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
            'cancelled_orders': 0,
            'completed_orders': 0,
            'today_orders': 0,
            'today_revenue': 0.0,
            'cash_orders': 0,
            'cash_revenue': 0.0,
            'phonepe_orders': 0,
            'phonepe_revenue': 0.0,
            'period_label': 'Today',
        }, filters={})

@orders_bp.route('/report.pdf')
@login_required
def sales_report_pdf():
    """Downloadable sales report for a date range: plates sold + revenue per
    item, split into Morning / Evening sections, plus Cash vs PhonePe totals."""
    from datetime import date as _date
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from flask import make_response

    NEXT = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    SAME = dict(new_x=XPos.RIGHT, new_y=YPos.TOP)

    store = scoped_location_id()
    location_id = store or (request.args.get('location') or None)
    if not location_id:
        flash('Pick a store to download its sales report.', 'error')
        return redirect(url_for('orders.index'))
    date_from = request.args.get('date_from') or _date.today().isoformat()
    date_to = request.args.get('date_to') or _date.today().isoformat()

    loc = execute_query_one("SELECT name FROM locations WHERE id = %s", (location_id,))
    loc_name = loc['name'] if loc else 'Store'

    # Every figure comes from order_items of COMPLETED orders only (cancelled
    # orders are never counted), so the per-item breakdown and the Cash/PhonePe
    # payment totals always reconcile to the exact same grand total.
    rows = execute_query("""
        SELECT DATE(o.created_at + INTERVAL '5 hours 30 minutes') AS day,
               CASE WHEN (o.created_at + INTERVAL '5 hours 30 minutes')::time <= TIME '13:00:00'
                    THEN 'morning' ELSE 'evening' END AS section,
               oi.item_name, SUM(oi.quantity) AS plates, SUM(oi.total_price) AS revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        LEFT JOIN location_menu lm ON lm.id = oi.location_menu_id
        WHERE o.status = 'completed' AND o.location_id = %s
          AND DATE(o.created_at + INTERVAL '5 hours 30 minutes') >= %s
          AND DATE(o.created_at + INTERVAL '5 hours 30 minutes') <= %s
        GROUP BY DATE(o.created_at + INTERVAL '5 hours 30 minutes'),
                 CASE WHEN (o.created_at + INTERVAL '5 hours 30 minutes')::time <= TIME '13:00:00'
                      THEN 'morning' ELSE 'evening' END, oi.item_name
        ORDER BY day, section, oi.item_name
    """, (location_id, date_from, date_to), fetch=True) or []

    pay = execute_query("""
        SELECT COALESCE(o.payment_method, 'cash') AS pm,
               COUNT(DISTINCT o.id) AS orders, COALESCE(SUM(oi.total_price), 0) AS total
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        WHERE o.status = 'completed' AND o.location_id = %s
          AND DATE(o.created_at + INTERVAL '5 hours 30 minutes') >= %s
          AND DATE(o.created_at + INTERVAL '5 hours 30 minutes') <= %s
        GROUP BY COALESCE(o.payment_method, 'cash')
    """, (location_id, date_from, date_to), fetch=True) or []

    from collections import OrderedDict
    days = OrderedDict()
    for r in rows:
        days.setdefault(str(r['day']), OrderedDict()).setdefault(r['section'], []).append(r)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Sip & Snack - Sales Report', align='C', **NEXT)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 6, loc_name, align='C', **NEXT)
    period = date_from if date_from == date_to else f'{date_from}  to  {date_to}'
    pdf.cell(0, 6, f'Period: {period}', align='C', **NEXT)
    pdf.ln(3)

    grand_plates, grand_rev = 0, 0.0
    SECTION_LABELS = [('morning', 'Morning'), ('evening', 'Evening'), ('all', 'Both / Uncategorised')]

    def section_table(title, items):
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_fill_color(235, 235, 235)
        pdf.cell(0, 7, '   ' + title, fill=True, **NEXT)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(110, 6, 'Item', border=1, **SAME)
        pdf.cell(30, 6, 'Plates', border=1, align='R', **SAME)
        pdf.cell(50, 6, 'Revenue (Rs.)', border=1, align='R', **NEXT)
        pdf.set_font('Helvetica', '', 10)
        sp, sr = 0, 0.0
        for it in items:
            p = int(it['plates'] or 0); rv = float(it['revenue'] or 0)
            sp += p; sr += rv
            pdf.cell(110, 6, str(it['item_name'])[:55], border=1, **SAME)
            pdf.cell(30, 6, str(p), border=1, align='R', **SAME)
            pdf.cell(50, 6, f'{rv:.2f}', border=1, align='R', **NEXT)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(110, 6, 'Subtotal', border=1, **SAME)
        pdf.cell(30, 6, str(sp), border=1, align='R', **SAME)
        pdf.cell(50, 6, f'{sr:.2f}', border=1, align='R', **NEXT)
        return sp, sr

    if not rows:
        pdf.set_font('Helvetica', '', 11)
        pdf.cell(0, 8, 'No sales in this period.', **NEXT)

    # One block per day: Morning / Evening / Both, then a day total.
    for day, secs in days.items():
        pdf.ln(2)
        pdf.set_font('Helvetica', 'B', 13)
        pdf.set_fill_color(21, 122, 94); pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 8, '  ' + day, fill=True, **NEXT)
        pdf.set_text_color(0, 0, 0)
        day_p, day_r = 0, 0.0
        for key, lbl in SECTION_LABELS:
            if secs.get(key):
                sp, sr = section_table(lbl, secs[key])
                day_p += sp; day_r += sr
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_fill_color(225, 240, 234)
        pdf.cell(110, 7, 'Day total - ' + day, border=1, fill=True, **SAME)
        pdf.cell(30, 7, str(day_p), border=1, align='R', fill=True, **SAME)
        pdf.cell(50, 7, f'{day_r:.2f}', border=1, align='R', fill=True, **NEXT)
        grand_plates += day_p; grand_rev += day_r

    pdf.ln(4)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_fill_color(17, 24, 39); pdf.set_text_color(255, 255, 255)
    pdf.cell(110, 9, 'GRAND TOTAL (all days)', border=1, fill=True, **SAME)
    pdf.cell(30, 9, str(grand_plates), border=1, align='R', fill=True, **SAME)
    pdf.cell(50, 9, f'{grand_rev:.2f}', border=1, align='R', fill=True, **NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    pm = {r['pm']: r for r in pay}
    cash_t = float(pm['cash']['total']) if 'cash' in pm else 0.0
    cash_n = int(pm['cash']['orders']) if 'cash' in pm else 0
    ppe_t = float(pm['phonepe']['total']) if 'phonepe' in pm else 0.0
    ppe_n = int(pm['phonepe']['orders']) if 'phonepe' in pm else 0
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 8, 'Payment Summary (whole period)', **NEXT)
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(100, 7, f'Cash  ({cash_n} orders)', border=1, **SAME)
    pdf.cell(60, 7, f'Rs. {cash_t:.2f}', border=1, align='R', **NEXT)
    pdf.cell(100, 7, f'PhonePe  ({ppe_n} orders)', border=1, **SAME)
    pdf.cell(60, 7, f'Rs. {ppe_t:.2f}', border=1, align='R', **NEXT)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(100, 7, 'Total Collected', border=1, **SAME)
    pdf.cell(60, 7, f'Rs. {cash_t + ppe_t:.2f}', border=1, align='R', **NEXT)

    out = bytes(pdf.output())
    resp = make_response(out)
    resp.headers['Content-Type'] = 'application/pdf'
    fname = f'sales_{loc_name}_{date_from}_to_{date_to}.pdf'.replace(' ', '_')
    resp.headers['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp

@orders_bp.route('/<order_id>')
@login_required
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
@login_required
def update_status(order_id):
    """Update order status. Returns JSON when called via AJAX (the in-app
    Cancel button) so a flaky mobile network shows a friendly retry instead of
    a full-page navigation failing with 'site can't be reached'."""
    new_status = request.form.get('status')
    wants_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if new_status not in ['pending', 'preparing', 'ready', 'completed', 'cancelled']:
        if wants_json:
            return jsonify({'success': False, 'error': 'Invalid status'}), 400
        flash('Invalid status', 'error')
        return redirect(url_for('orders.view', order_id=order_id))

    # A store-scoped manager may only touch their own store's orders.
    store = scoped_location_id()

    try:
        existing_order = execute_query_one(
            "SELECT id, status, location_id FROM orders WHERE id = %s", (order_id,))

        if not existing_order:
            if wants_json:
                return jsonify({'success': False, 'error': 'Order not found'}), 404
            flash('Order not found', 'error')
            return redirect(url_for('orders.index'))

        if store and str(existing_order['location_id']) != store:
            if wants_json:
                return jsonify({'success': False, 'error': "Not your store's order"}), 403
            flash("You can only manage your own store's orders", 'error')
            return redirect(url_for('orders.index'))

        execute_query("""
            UPDATE orders
            SET status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_status, order_id))

        if wants_json:
            return jsonify({'success': True, 'status': new_status})
        flash('Order status updated!', 'success')
    except Exception as e:
        if wants_json:
            return jsonify({'success': False, 'error': 'Failed to update status'}), 500
        flash(f'Error updating order status: {str(e)}', 'error')

    return redirect(url_for('orders.view', order_id=order_id))

@orders_bp.route('/stats')
@login_required
def stats():
    """Get order statistics via AJAX"""
    try:
        stats = get_order_stats()
        return {'success': True, 'stats': stats}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_order_stats(location_id=None, date_from=None, date_to=None):
    """Order stats for a single store, scoped to a date range. When no dates are
    given it defaults to TODAY, so the cards always describe a specific period
    and change as the manager picks a date range."""
    stats = {
        'total_orders': 0,
        'total_revenue': 0.0,
        'pending_orders': 0,
        'cancelled_orders': 0,
        'completed_orders': 0,
        'today_orders': 0,
        'today_revenue': 0.0,
        'cash_orders': 0,
        'cash_revenue': 0.0,
        'phonepe_orders': 0,
        'phonepe_revenue': 0.0,
        'period_label': 'Today',
    }

    loc_sql = " AND location_id = %s" if location_id else ""
    loc_param = [location_id] if location_id else []

    # Date window on the IST calendar (created_at is UTC; +5:30 = IST), so the
    # totals match the dates the manager actually picks.
    if date_from or date_to:
        df = date_from or date_to
        dt = date_to or date_from
        date_sql = (" AND DATE(created_at + INTERVAL '5 hours 30 minutes') >= %s"
                    " AND DATE(created_at + INTERVAL '5 hours 30 minutes') <= %s")
        date_param = [df, dt]
        stats['period_label'] = df if df == dt else f'{df} to {dt}'
    else:
        date_sql = " AND DATE(created_at + INTERVAL '5 hours 30 minutes') = (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date"
        date_param = []

    where = date_sql + loc_sql
    params = tuple(date_param + loc_param)

    try:
        # Orders + revenue (sales = everything not cancelled) in the period
        result = execute_query_one(
            "SELECT COUNT(*) AS count, COALESCE(SUM(total_amount), 0) AS revenue "
            "FROM orders WHERE status != 'cancelled'" + where, params)
        if result:
            stats['total_orders'] = result['count']
            stats['total_revenue'] = float(result['revenue'])
            stats['today_orders'] = result['count']
            stats['today_revenue'] = float(result['revenue'])

        result = execute_query_one(
            "SELECT COUNT(*) AS count FROM orders WHERE status = 'cancelled'" + where, params)
        stats['cancelled_orders'] = result['count'] if result else 0

        result = execute_query_one(
            "SELECT COUNT(*) AS count FROM orders WHERE status = 'completed'" + where, params)
        stats['completed_orders'] = result['count'] if result else 0

        # Payment split (admin-only card) — same "sales = not cancelled" scope as total_orders.
        result = execute_query_one(
            "SELECT COUNT(*) AS count, COALESCE(SUM(total_amount), 0) AS revenue "
            "FROM orders WHERE status != 'cancelled' AND COALESCE(payment_method, 'cash') = 'cash'" + where, params)
        stats['cash_orders'] = result['count'] if result else 0
        stats['cash_revenue'] = float(result['revenue']) if result else 0.0

        result = execute_query_one(
            "SELECT COUNT(*) AS count, COALESCE(SUM(total_amount), 0) AS revenue "
            "FROM orders WHERE status != 'cancelled' AND payment_method = 'phonepe'" + where, params)
        stats['phonepe_orders'] = result['count'] if result else 0
        stats['phonepe_revenue'] = float(result['revenue']) if result else 0.0
    except Exception as e:
        print(f"Error getting order stats: {e}")

    return stats

@orders_bp.route('/api/create', methods=['POST'])
@login_required
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

        # Generate a unique order number. Milliseconds + a short random suffix so
        # two orders placed in the same second (busy counter / concurrent
        # managers) can't collide on the unique order_number constraint.
        import time
        order_number = f"ORD{int(time.time() * 1000)}{uuid.uuid4().hex[:3].upper()}"

        # Calculate total amount
        total_amount = sum(item['total_price'] for item in data['items'])

        # Optional order details (sent by the POS screen; external/API callers
        # may omit them and keep the previous defaults).
        customer_name = (data.get('customer_name') or '').strip() or None
        customer_phone = (data.get('customer_phone') or '').strip() or None
        order_type = data.get('order_type') or 'dine-in'
        notes = (data.get('notes') or '').strip() or None
        payment_method = (data.get('payment_method') or 'cash').strip().lower()
        if payment_method not in ('cash', 'phonepe'):
            payment_method = 'cash'

        # Idempotency: the app sends a client-generated id with each order so a
        # retried / queued offline order can NEVER create a duplicate. If we've
        # already saved this id, return that order instead of making a new one.
        client_order_id = (data.get('client_order_id') or '').strip() or None
        if client_order_id:
            existing = execute_query_one(
                "SELECT id, order_number FROM orders WHERE client_order_id = %s", (client_order_id,))
            if existing:
                return jsonify({'success': True, 'order_id': str(existing['id']),
                                'order_number': existing['order_number'], 'duplicate': True})

        # Create order
        order_id = str(uuid.uuid4())
        # POS sales are final the moment they're placed, so an order starts as
        # 'completed' (shown as "Success"). Cancelling sets 'cancelled';
        # editing keeps it a sale but stamps edited_at (shown as "Edited").
        ops = [(
            """INSERT INTO orders (id, location_id, order_number, customer_name, customer_phone,
                              customer_email, order_type, total_amount, notes, status, payment_method, client_order_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'completed', %s, %s)""",
            (order_id, data['location_id'], order_number, customer_name, customer_phone,
             None, order_type, total_amount, notes, payment_method, client_order_id)
        )]
        for item in data['items']:
            ops.append((
                """INSERT INTO order_items (id, order_id, location_menu_id, master_menu_id,
                                       item_name, quantity, unit_price, total_price, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (str(uuid.uuid4()), order_id, item['location_menu_id'], item['master_menu_id'],
                 item['item_name'], item['quantity'], item['unit_price'], item['total_price'],
                 'Parcel' if item.get('is_parcel') else None)
            ))
        # All-or-nothing: the order and ALL its items commit together, so a
        # failed item insert can never leave a total-without-items "ghost" order.
        try:
            execute_transaction(ops)
        except Exception:
            # If a concurrent retry of the same offline order already inserted
            # this client_order_id (unique index), return that order — no dup.
            if client_order_id:
                ex = execute_query_one(
                    "SELECT id, order_number FROM orders WHERE client_order_id = %s", (client_order_id,))
                if ex:
                    return jsonify({'success': True, 'order_id': str(ex['id']),
                                    'order_number': ex['order_number'], 'duplicate': True})
            raise

        return jsonify({
            'success': True,
            'order_id': order_id,
            'order_number': order_number,
            'message': 'Order created successfully'
        })

    except Exception as e:
        print(f"Error creating order: {e}")
        return jsonify({'success': False, 'error': 'Failed to create order'}), 500
