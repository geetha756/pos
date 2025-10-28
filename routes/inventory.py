from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one
from .auth import login_required
from datetime import datetime, date
import uuid

inventory_bp = Blueprint('inventory', __name__)

# ===============================
# MASTER INVENTORY MANAGEMENT
# ===============================

@inventory_bp.route('/')
@login_required
def index():
    """Inventory module landing - redirect to Location Inventory"""
    return redirect(url_for('inventory.location_inventory'))

@inventory_bp.route('/master-inventory')
@login_required
def master_inventory():
    """List all master inventory items"""
    try:
        search = request.args.get('search', '')
        category = request.args.get('category', '')

        query = """
            SELECT mi.*, s.name as supplier_name, s.contact_person as supplier_contact,
                   COUNT(li.location_id) as location_count
            FROM master_inventory mi
            LEFT JOIN suppliers s ON mi.supplier_id = s.id
            LEFT JOIN location_inventory li ON mi.id = li.master_inventory_id
            WHERE mi.is_active = TRUE
        """

        params = []
        if search:
            query += " AND (mi.name ILIKE %s OR mi.description ILIKE %s)"
            params.extend([f'%{search}%', f'%{search}%'])

        if category:
            query += " AND mi.category = %s"
            params.append(category)

        query += " GROUP BY mi.id, s.name, s.contact_person ORDER BY mi.name"

        items = execute_query(query, params, fetch=True)

        # Get categories for filter
        categories = execute_query("""
            SELECT DISTINCT category FROM master_inventory
            WHERE is_active = TRUE ORDER BY category
        """, fetch=True)

        return render_template('inventory/master_inventory.html', items=items, categories=categories,
                             search=search, selected_category=category)
    except Exception as e:
        flash(f'Error loading master inventory: {str(e)}', 'error')
        return render_template('inventory/master_inventory.html', items=[], categories=[])

@inventory_bp.route('/master-inventory/add', methods=['GET', 'POST'])
@login_required
def add_master_item():
    """Add new master inventory item"""
    if request.method == 'POST':
        try:
            data = request.form
            supplier_id = data.get('supplier_id') if data.get('supplier_id') else None

            execute_query("""
                INSERT INTO master_inventory (
                    name, description, category, unit, supplier_id,
                    min_order_quantity, default_cost_per_unit, barcode
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['name'], data.get('description'), data['category'], data['unit'],
                supplier_id,
                float(data.get('min_order_quantity', 1)),
                float(data.get('default_cost_per_unit', 0)),
                data.get('barcode')
            ))

            flash('Master inventory item added successfully!', 'success')
            return redirect(url_for('inventory.master_inventory'))
        except Exception as e:
            flash(f'Error adding item: {str(e)}', 'error')

    # Get suppliers for dropdown
    suppliers = execute_query("SELECT id, name, contact_person FROM suppliers WHERE is_active = TRUE ORDER BY name", fetch=True)
    return render_template('inventory/master_inventory_form.html', item=None, suppliers=suppliers)

@inventory_bp.route('/master-inventory/<uuid:item_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_master_item(item_id):
    """Edit master inventory item"""
    if request.method == 'POST':
        try:
            data = request.form
            supplier_id = data.get('supplier_id') if data.get('supplier_id') else None

            execute_query("""
                UPDATE master_inventory SET
                    name = %s, description = %s, category = %s, unit = %s,
                    supplier_id = %s,
                    min_order_quantity = %s, default_cost_per_unit = %s,
                    barcode = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                data['name'], data.get('description'), data['category'], data['unit'],
                supplier_id,
                float(data.get('min_order_quantity', 1)),
                float(data.get('default_cost_per_unit', 0)),
                data.get('barcode'), item_id
            ))

            flash('Master inventory item updated successfully!', 'success')
            return redirect(url_for('inventory.master_inventory'))
        except Exception as e:
            flash(f'Error updating item: {str(e)}', 'error')

    try:
        item = execute_query_one("SELECT * FROM master_inventory WHERE id = %s", (str(item_id),))
        if not item:
            flash('Item not found', 'error')
            return redirect(url_for('inventory.master_inventory'))
    except Exception as e:
        flash(f'Error loading item: {str(e)}', 'error')
        return redirect(url_for('inventory.master_inventory'))

    # Get suppliers for dropdown
    suppliers = execute_query("SELECT id, name, contact_person FROM suppliers WHERE is_active = TRUE ORDER BY name", fetch=True)
    return render_template('inventory/master_inventory_form.html', item=item, suppliers=suppliers)

@inventory_bp.route('/master-inventory/<uuid:item_id>/delete', methods=['POST'])
@login_required
def delete_master_item(item_id):
    """Delete master inventory item"""
    try:
        execute_query("UPDATE master_inventory SET is_active = FALSE WHERE id = %s", (str(item_id),))
        flash('Master inventory item deactivated successfully!', 'success')
    except Exception as e:
        flash(f'Error deactivating item: {str(e)}', 'error')

    return redirect(url_for('inventory.master_inventory'))

# ===============================
# SUPPLIERS MANAGEMENT
# ===============================

@inventory_bp.route('/suppliers')
@login_required
def suppliers():
    """List all suppliers"""
    try:
        search = request.args.get('search', '')
        status = request.args.get('status', 'active')

        query = """
            SELECT s.*,
                   COUNT(mi.id) as items_count,
                   COUNT(CASE WHEN mi.is_active = TRUE THEN 1 END) as active_items_count
            FROM suppliers s
            LEFT JOIN master_inventory mi ON s.id = mi.supplier_id
        """

        conditions = []
        params = []

        if search:
            conditions.append("(s.name ILIKE %s OR s.contact_person ILIKE %s OR s.email ILIKE %s)")
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

        if status == 'active':
            conditions.append("s.is_active = TRUE")
        elif status == 'inactive':
            conditions.append("s.is_active = FALSE")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " GROUP BY s.id ORDER BY s.name"

        suppliers_list = execute_query(query, params, fetch=True)

        return render_template('inventory/suppliers.html', suppliers=suppliers_list,
                             search=search, selected_status=status)
    except Exception as e:
        flash(f'Error loading suppliers: {str(e)}', 'error')
        return render_template('inventory/suppliers.html', suppliers=[], search='', selected_status='active')

@inventory_bp.route('/suppliers/add', methods=['GET', 'POST'])
@login_required
def add_supplier():
    """Add new supplier"""
    if request.method == 'POST':
        try:
            data = request.form

            execute_query("""
                INSERT INTO suppliers (
                    name, contact_person, email, phone, address, city, state, zip_code,
                    payment_terms, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['name'], data.get('contact_person'), data.get('email'),
                data.get('phone'), data.get('address'), data.get('city'),
                data.get('state'), data.get('zip_code'), data.get('payment_terms'),
                data.get('notes')
            ))

            flash('Supplier added successfully!', 'success')
            return redirect(url_for('inventory.suppliers'))
        except Exception as e:
            flash(f'Error adding supplier: {str(e)}', 'error')

    return render_template('inventory/supplier_form.html', supplier=None)

@inventory_bp.route('/suppliers/<uuid:supplier_id>')
@login_required
def view_supplier(supplier_id):
    """View supplier details"""
    try:
        # Get supplier info
        supplier = execute_query_one("SELECT * FROM suppliers WHERE id = %s", (str(supplier_id),))

        if not supplier:
            flash('Supplier not found', 'error')
            return redirect(url_for('inventory.suppliers'))

        # Get supplier's inventory items
        items = execute_query("""
            SELECT mi.*, COUNT(li.location_id) as location_count
            FROM master_inventory mi
            LEFT JOIN location_inventory li ON mi.id = li.master_inventory_id
            WHERE mi.supplier_id = %s AND mi.is_active = TRUE
            GROUP BY mi.id
            ORDER BY mi.name
        """, (str(supplier_id),), fetch=True)

        return render_template('inventory/supplier_detail.html',
                             supplier=supplier, items=items)
    except Exception as e:
        flash(f'Error loading supplier: {str(e)}', 'error')
        return redirect(url_for('inventory.suppliers'))

@inventory_bp.route('/suppliers/<uuid:supplier_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_supplier(supplier_id):
    """Edit supplier"""
    if request.method == 'POST':
        try:
            data = request.form

            execute_query("""
                UPDATE suppliers SET
                    name = %s, contact_person = %s, email = %s, phone = %s,
                    address = %s, city = %s, state = %s, zip_code = %s,
                    payment_terms = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                data['name'], data.get('contact_person'), data.get('email'),
                data.get('phone'), data.get('address'), data.get('city'),
                data.get('state'), data.get('zip_code'), data.get('payment_terms'),
                data.get('notes'), str(supplier_id)
            ))

            flash('Supplier updated successfully!', 'success')
            return redirect(url_for('inventory.view_supplier', supplier_id=supplier_id))
        except Exception as e:
            flash(f'Error updating supplier: {str(e)}', 'error')

    try:
        supplier = execute_query_one("SELECT * FROM suppliers WHERE id = %s", (str(supplier_id),))
        if not supplier:
            flash('Supplier not found', 'error')
            return redirect(url_for('inventory.suppliers'))
    except Exception as e:
        flash(f'Error loading supplier: {str(e)}', 'error')
        return redirect(url_for('inventory.suppliers'))

    return render_template('inventory/supplier_form.html', supplier=supplier)

@inventory_bp.route('/suppliers/<uuid:supplier_id>/toggle-status', methods=['POST'])
@login_required
def toggle_supplier_status(supplier_id):
    """Toggle supplier active/inactive status"""
    try:
        # Get current status
        supplier = execute_query_one("SELECT is_active FROM suppliers WHERE id = %s", (str(supplier_id),))
        if not supplier:
            flash('Supplier not found', 'error')
            return redirect(url_for('inventory.suppliers'))

        new_status = not supplier['is_active']
        status_text = 'activated' if new_status else 'deactivated'

        execute_query("UPDATE suppliers SET is_active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                     (new_status, str(supplier_id)))

        flash(f'Supplier {status_text} successfully!', 'success')
    except Exception as e:
        flash(f'Error updating supplier status: {str(e)}', 'error')

    return redirect(url_for('inventory.suppliers'))

# ===============================
# PURCHASE LISTS MANAGEMENT
# ===============================

@inventory_bp.route('/purchase-lists')
@login_required
def purchase_lists():
    """List all purchase lists"""
    try:
        search = request.args.get('search', '')
        location_id = request.args.get('location_id', '')
        status = request.args.get('status', '')

        query = """
            SELECT pl.*, l.name as location_name, s.first_name, s.last_name,
                   COUNT(pli.id) as item_count
            FROM purchase_lists pl
            JOIN locations l ON pl.location_id = l.id
            LEFT JOIN staff s ON pl.created_by = s.id
            LEFT JOIN purchase_list_items pli ON pl.id = pli.purchase_list_id
            GROUP BY pl.id, l.name, s.first_name, s.last_name
        """

        conditions = []
        params = []

        if search:
            conditions.append("(pl.name ILIKE %s OR pl.description ILIKE %s)")
            params.extend([f'%{search}%', f'%{search}%'])

        if location_id:
            conditions.append("pl.location_id = %s")
            params.append(location_id)

        if status:
            conditions.append("pl.status = %s")
            params.append(status)

        if conditions:
            query += " HAVING " + " AND ".join(conditions)

        query += " ORDER BY pl.created_at DESC"

        lists = execute_query(query, params, fetch=True)

        # Get locations for filter
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []

        return render_template('inventory/purchase_lists.html', lists=lists, locations=locations,
                             search=search, selected_location=location_id, selected_status=status)
    except Exception as e:
        flash(f'Error loading purchase lists: {str(e)}', 'error')
        return render_template('inventory/purchase_lists.html', lists=[], locations=[])

@inventory_bp.route('/purchase-lists/add', methods=['GET', 'POST'])
@login_required
def add_purchase_list():
    """Create new purchase list"""
    if request.method == 'POST':
        try:
            data = request.form
            location_id = data['location_id']

            # Create purchase list
            list_id = str(uuid.uuid4())
            execute_query("""
                INSERT INTO purchase_lists (
                    id, location_id, name, description, created_by,
                    status, priority, required_by_date
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                list_id, location_id, data['name'], data.get('description'),
                request.session.get('user_id'), 'draft', data.get('priority', 'normal'),
                data.get('required_by_date') or None
            ))

            flash('Purchase list created successfully!', 'success')
            return redirect(url_for('inventory.edit_purchase_list', list_id=list_id))
        except Exception as e:
            flash(f'Error creating purchase list: {str(e)}', 'error')

    # Get locations
    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)
    return render_template('inventory/purchase_list_form.html', list=None, locations=locations)

@inventory_bp.route('/purchase-lists/<uuid:list_id>')
@login_required
def view_purchase_list(list_id):
    """View purchase list details"""
    try:
        # Get purchase list info
        purchase_list = execute_query_one("""
            SELECT pl.*, l.name as location_name, s.first_name, s.last_name
            FROM purchase_lists pl
            JOIN locations l ON pl.location_id = l.id
            LEFT JOIN staff s ON pl.created_by = s.id
            WHERE pl.id = %s
        """, (str(list_id),))

        if not purchase_list:
            flash('Purchase list not found', 'error')
            return redirect(url_for('inventory.purchase_lists'))

        # Get purchase list items
        items = execute_query("""
            SELECT pli.*, mi.name as item_name, mi.unit, mi.default_cost_per_unit
            FROM purchase_list_items pli
            JOIN master_inventory mi ON pli.master_inventory_id = mi.id
            WHERE pli.purchase_list_id = %s
            ORDER BY mi.name
        """, (str(list_id),), fetch=True)

        return render_template('inventory/purchase_list_detail.html',
                             purchase_list=purchase_list, items=items)
    except Exception as e:
        flash(f'Error loading purchase list: {str(e)}', 'error')
        return redirect(url_for('inventory.purchase_lists'))

@inventory_bp.route('/purchase-lists/<uuid:list_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_purchase_list(list_id):
    """Edit purchase list and add/remove items"""
    try:
        # Get purchase list
        purchase_list = execute_query_one("""
            SELECT pl.*, l.name as location_name
            FROM purchase_lists pl
            JOIN locations l ON pl.location_id = l.id
            WHERE pl.id = %s
        """, (str(list_id),))

        if not purchase_list:
            flash('Purchase list not found', 'error')
            return redirect(url_for('inventory.purchase_lists'))

        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'add_item':
                # Add item to purchase list
                master_inventory_id = request.form['master_inventory_id']
                quantity = float(request.form['quantity'])

                # Get cost from master inventory
                item = execute_query_one("""
                    SELECT default_cost_per_unit FROM master_inventory
                    WHERE id = %s
                """, (master_inventory_id,))

                cost_per_unit = item['default_cost_per_unit'] if item else 0
                total_cost = quantity * cost_per_unit

                execute_query("""
                    INSERT INTO purchase_list_items (
                        purchase_list_id, master_inventory_id, quantity_requested,
                        cost_per_unit, total_cost
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (purchase_list_id, master_inventory_id)
                    DO UPDATE SET
                        quantity_requested = EXCLUDED.quantity_requested,
                        cost_per_unit = EXCLUDED.cost_per_unit,
                        total_cost = EXCLUDED.total_cost
                """, (str(list_id), master_inventory_id, quantity, cost_per_unit, total_cost))

                # Update total cost
                update_purchase_list_total(list_id)

                flash('Item added to purchase list!', 'success')

            elif action == 'update_status':
                new_status = request.form['status']
                execute_query("""
                    UPDATE purchase_lists SET status = %s,
                    updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (new_status, str(list_id)))

                flash(f'Purchase list status updated to {new_status}!', 'success')

        # Get current items
        items = execute_query("""
            SELECT pli.*, mi.name as item_name, mi.unit, mi.category
            FROM purchase_list_items pli
            JOIN master_inventory mi ON pli.master_inventory_id = mi.id
            WHERE pli.purchase_list_id = %s
            ORDER BY mi.category, mi.name
        """, (str(list_id),), fetch=True)

        # Get available inventory items (not already in this list)
        existing_item_ids = [str(item['master_inventory_id']) for item in items]
        if existing_item_ids:
            placeholder = ','.join(['%s'] * len(existing_item_ids))
            available_items = execute_query(f"""
                SELECT id, name, category, unit, default_cost_per_unit
                FROM master_inventory
                WHERE is_active = TRUE AND id NOT IN ({placeholder})
                ORDER BY category, name
            """, existing_item_ids, fetch=True)
        else:
            available_items = execute_query("""
                SELECT id, name, category, unit, default_cost_per_unit
                FROM master_inventory
                WHERE is_active = TRUE
                ORDER BY category, name
            """, fetch=True)

        return render_template('inventory/purchase_list_edit.html',
                             purchase_list=purchase_list, items=items,
                             available_items=available_items)
    except Exception as e:
        flash(f'Error editing purchase list: {str(e)}', 'error')
        return redirect(url_for('inventory.purchase_lists'))

@inventory_bp.route('/purchase-lists/<uuid:list_id>/items/<uuid:item_id>/remove', methods=['POST'])
@login_required
def remove_purchase_item(list_id, item_id):
    """Remove item from purchase list"""
    try:
        execute_query("""
            DELETE FROM purchase_list_items
            WHERE purchase_list_id = %s AND master_inventory_id = %s
        """, (str(list_id), str(item_id)))

        # Update total cost
        update_purchase_list_total(list_id)

        flash('Item removed from purchase list!', 'success')
    except Exception as e:
        flash(f'Error removing item: {str(e)}', 'error')

    return redirect(url_for('inventory.edit_purchase_list', list_id=list_id))

# ===============================
# LOCATION INVENTORY MANAGEMENT
# ===============================

@inventory_bp.route('/location-inventory')
@login_required
def location_inventory():
    """View inventory across all locations"""
    try:
        location_id = request.args.get('location_id', '')
        category = request.args.get('category', '')
        alert_only = request.args.get('alert_only', '') == '1'

        query = """
            SELECT li.*, mi.name as item_name, mi.category, mi.unit,
                   l.name as location_name,
                   CASE
                       WHEN li.current_stock <= li.reorder_point THEN 'low_stock'
                       WHEN li.current_stock = 0 THEN 'out_of_stock'
                       ELSE 'normal'
                   END as stock_status
            FROM location_inventory li
            JOIN master_inventory mi ON li.master_inventory_id = mi.id
            JOIN locations l ON li.location_id = l.id
            WHERE mi.is_active = TRUE
        """

        params = []
        if location_id:
            query += " AND li.location_id = %s"
            params.append(location_id)

        if category:
            query += " AND mi.category = %s"
            params.append(category)

        if alert_only:
            query += " AND li.current_stock <= li.reorder_point"

        query += " ORDER BY l.name, mi.category, mi.name"

        inventory = execute_query(query, params, fetch=True)

        # Get locations and categories for filters
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)
        categories = execute_query("""
            SELECT DISTINCT mi.category
            FROM master_inventory mi
            JOIN location_inventory li ON mi.id = li.master_inventory_id
            ORDER BY mi.category
        """, fetch=True)

        return render_template('inventory/location_inventory.html',
                             inventory=inventory, locations=locations, categories=categories,
                             selected_location=location_id, selected_category=category,
                             alert_only=alert_only)
    except Exception as e:
        flash(f'Error loading location inventory: {str(e)}', 'error')
        return render_template('inventory/location_inventory.html', inventory=[], locations=[], categories=[])

@inventory_bp.route('/location-inventory/<uuid:location_id>/<uuid:item_id>/adjust', methods=['GET', 'POST'])
@login_required
def adjust_inventory(location_id, item_id):
    """Adjust inventory stock levels"""
    try:
        # Get current inventory info
        inventory = execute_query_one("""
            SELECT li.*, mi.name as item_name, mi.unit, l.name as location_name
            FROM location_inventory li
            JOIN master_inventory mi ON li.master_inventory_id = mi.id
            JOIN locations l ON li.location_id = l.id
            WHERE li.location_id = %s AND li.master_inventory_id = %s
        """, (str(location_id), str(item_id)))

        if not inventory:
            flash('Inventory item not found', 'error')
            return redirect(url_for('inventory.location_inventory'))

        if request.method == 'POST':
            adjustment_type = request.form['adjustment_type']
            quantity = float(request.form['quantity'])
            reason = request.form['reason']
            notes = request.form.get('notes', '')

            # Calculate new stock
            if adjustment_type == 'add':
                new_stock = inventory['current_stock'] + quantity
            else:  # subtract
                new_stock = inventory['current_stock'] - quantity

            if new_stock < 0:
                flash('Cannot reduce stock below zero', 'error')
                return redirect(request.url)

            # Update inventory
            execute_query("""
                UPDATE location_inventory
                SET current_stock = %s, last_updated = CURRENT_TIMESTAMP
                WHERE location_id = %s AND master_inventory_id = %s
            """, (new_stock, str(location_id), str(item_id)))

            # Record transaction
            execute_query("""
                INSERT INTO inventory_transactions (
                    location_id, master_inventory_id, transaction_type,
                    quantity, previous_stock, new_stock, recorded_by, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(location_id), str(item_id), 'adjustment',
                quantity if adjustment_type == 'add' else -quantity,
                inventory['current_stock'], new_stock,
                request.session.get('user_id'), f"{reason}: {notes}"
            ))

            flash('Inventory adjusted successfully!', 'success')
            return redirect(url_for('inventory.location_inventory'))

        return render_template('inventory/adjust_inventory.html', inventory=inventory)
    except Exception as e:
        flash(f'Error adjusting inventory: {str(e)}', 'error')
        return redirect(url_for('inventory.location_inventory'))

# ===============================
# DAILY USAGE TRACKING
# ===============================

@inventory_bp.route('/daily-usage')
@login_required
def daily_usage():
    """View and record daily inventory usage"""
    try:
        selected_date = request.args.get('date', date.today().isoformat())
        location_id = request.args.get('location_id', '')

        # Get locations for filter
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)

        # Get daily usage records
        query = """
            SELECT du.*, mi.name as item_name, mi.unit, l.name as location_name,
                   s.first_name, s.last_name
            FROM daily_inventory_usage du
            JOIN master_inventory mi ON du.master_inventory_id = mi.id
            JOIN locations l ON du.location_id = l.id
            LEFT JOIN staff s ON du.recorded_by = s.id
            WHERE du.date = %s
        """

        params = [selected_date]
        if location_id:
            query += " AND du.location_id = %s"
            params.append(location_id)

        query += " ORDER BY l.name, mi.name"

        usage_records = execute_query(query, params, fetch=True) or []

        return render_template('inventory/daily_usage.html',
                             usage_records=usage_records, locations=locations,
                             selected_date=selected_date, selected_location=location_id)
    except Exception as e:
        flash(f'Error loading daily usage: {str(e)}', 'error')
        return render_template('inventory/daily_usage.html', usage_records=[], locations=[])

@inventory_bp.route('/daily-usage/record', methods=['GET', 'POST'])
@login_required
def record_daily_usage():
    """Record daily inventory usage for a location"""
    try:
        location_id = request.args.get('location_id')
        record_date = request.args.get('date', date.today().isoformat())

        if not location_id:
            flash('Location is required', 'error')
            return redirect(url_for('inventory.daily_usage'))

        # Get location info
        location = execute_query_one("SELECT * FROM locations WHERE id = %s", (location_id,))
        if not location:
            flash('Location not found', 'error')
            return redirect(url_for('inventory.daily_usage'))

        if request.method == 'POST':
            # Process the form submission
            usage_data = {}
            wastage_data = {}

            for key, value in request.form.items():
                if key.startswith('opening_'):
                    item_id = key.replace('opening_', '')
                    usage_data[item_id] = {'opening': float(value)}
                elif key.startswith('closing_'):
                    item_id = key.replace('closing_', '')
                    if item_id in usage_data:
                        usage_data[item_id]['closing'] = float(value)
                elif key.startswith('wastage_'):
                    item_id = key.replace('wastage_', '')
                    wastage_data[item_id] = float(value)

            # Save usage records
            for item_id, data in usage_data.items():
                opening = data['opening']
                closing = data.get('closing', opening)
                wastage = wastage_data.get(item_id, 0)
                used = opening - closing - wastage

                execute_query("""
                    INSERT INTO daily_inventory_usage (
                        location_id, master_inventory_id, date, opening_stock,
                        closing_stock, used_quantity, wastage_quantity, recorded_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (location_id, master_inventory_id, date)
                    DO UPDATE SET
                        opening_stock = EXCLUDED.opening_stock,
                        closing_stock = EXCLUDED.closing_stock,
                        used_quantity = EXCLUDED.used_quantity,
                        wastage_quantity = EXCLUDED.wastage_quantity,
                        recorded_by = EXCLUDED.recorded_by,
                        status = 'recorded'
                """, (
                    location_id, item_id, record_date, opening, closing,
                    used, wastage, request.session.get('user_id')
                ))

            flash('Daily usage recorded successfully!', 'success')
            return redirect(url_for('inventory.daily_usage', date=record_date, location_id=location_id))

        # Get inventory items for this location
        inventory_items = execute_query("""
            SELECT li.*, mi.name, mi.unit, mi.category
            FROM location_inventory li
            JOIN master_inventory mi ON li.master_inventory_id = mi.id
            WHERE li.location_id = %s AND mi.is_active = TRUE
            ORDER BY mi.category, mi.name
        """, (location_id,), fetch=True)

        # Check if records already exist for today
        existing_records = execute_query("""
            SELECT master_inventory_id, opening_stock, closing_stock, wastage_quantity
            FROM daily_inventory_usage
            WHERE location_id = %s AND date = %s
        """, (location_id, record_date), fetch=True)

        existing_data = {str(r['master_inventory_id']): r for r in existing_records}

        return render_template('inventory/record_usage.html',
                             location=location, inventory_items=inventory_items,
                             record_date=record_date, existing_data=existing_data)
    except Exception as e:
        flash(f'Error recording daily usage: {str(e)}', 'error')
        return redirect(url_for('inventory.daily_usage'))

# ===============================
# LEFTOVER FOOD TRACKING
# ===============================

@inventory_bp.route('/leftover-food')
@login_required
def leftover_food():
    """Track leftover food from menu items"""
    try:
        selected_date = request.args.get('date', date.today().isoformat())
        location_id = request.args.get('location_id', '')

        # Get locations for filter
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []

        # Get leftover food records
        query = """
            SELECT lft.*, mi.name as menu_item_name, l.name as location_name,
                   s.first_name, s.last_name
            FROM leftover_food_tracking lft
            JOIN master_menu mi ON lft.master_menu_id = mi.id
            JOIN locations l ON lft.location_id = l.id
            LEFT JOIN staff s ON lft.recorded_by = s.id
            WHERE lft.date = %s
        """

        params = [selected_date]
        if location_id:
            query += " AND lft.location_id = %s"
            params.append(location_id)

        query += " ORDER BY l.name, mi.name"

        leftover_records = execute_query(query, params, fetch=True) or []

        return render_template('inventory/leftover_food.html',
                             leftover_records=leftover_records, locations=locations,
                             selected_date=selected_date, selected_location=location_id)
    except Exception as e:
        flash(f'Error loading leftover food tracking: {str(e)}', 'error')
        return render_template('inventory/leftover_food.html', leftover_records=[], locations=[])

@inventory_bp.route('/leftover-food/record', methods=['GET', 'POST'])
@login_required
def record_leftover_food():
    """Record leftover food for menu items"""
    try:
        location_id = request.args.get('location_id')
        record_date = request.args.get('date', date.today().isoformat())

        if not location_id:
            flash('Location is required', 'error')
            return redirect(url_for('inventory.leftover_food'))

        # Get location info
        location = execute_query_one("SELECT * FROM locations WHERE id = %s", (location_id,))
        if not location:
            flash('Location not found', 'error')
            return redirect(url_for('inventory.leftover_food'))

        if request.method == 'POST':
            # Process leftover food data
            leftover_data = {}

            for key, value in request.form.items():
                if key.startswith('prepared_'):
                    menu_item_id = key.replace('prepared_', '')
                    leftover_data[menu_item_id] = {'prepared': int(value)}
                elif key.startswith('sold_'):
                    menu_item_id = key.replace('sold_', '')
                    if menu_item_id in leftover_data:
                        leftover_data[menu_item_id]['sold'] = int(value)
                elif key.startswith('disposal_'):
                    menu_item_id = key.replace('disposal_', '')
                    if menu_item_id in leftover_data:
                        leftover_data[menu_item_id]['disposal'] = value

            # Save leftover records
            for menu_item_id, data in leftover_data.items():
                prepared = data['prepared']
                sold = data.get('sold', 0)
                leftover = prepared - sold
                disposal = data.get('disposal', 'discarded')

                execute_query("""
                    INSERT INTO leftover_food_tracking (
                        location_id, master_menu_id, date, quantity_prepared,
                        quantity_sold, quantity_leftover, disposal_method, recorded_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (location_id, master_menu_id, date)
                    DO UPDATE SET
                        quantity_prepared = EXCLUDED.quantity_prepared,
                        quantity_sold = EXCLUDED.quantity_sold,
                        quantity_leftover = EXCLUDED.quantity_leftover,
                        disposal_method = EXCLUDED.disposal_method,
                        recorded_by = EXCLUDED.recorded_by
                """, (
                    location_id, menu_item_id, record_date, prepared, sold,
                    leftover, disposal, request.session.get('user_id')
                ))

            flash('Leftover food data recorded successfully!', 'success')
            return redirect(url_for('inventory.leftover_food', date=record_date, location_id=location_id))

        # Get menu items available at this location
        menu_items = execute_query("""
            SELECT lm.master_menu_id as id, mm.name, mm.category
            FROM location_menu lm
            JOIN master_menu mm ON lm.master_menu_id = mm.id
            WHERE lm.location_id = %s AND mm.is_active = TRUE
            ORDER BY mm.category, mm.name
        """, (location_id,), fetch=True)

        # Check if records already exist for today
        existing_records = execute_query("""
            SELECT master_menu_id, quantity_prepared, quantity_sold, disposal_method
            FROM leftover_food_tracking
            WHERE location_id = %s AND date = %s
        """, (location_id, record_date), fetch=True)

        existing_data = {str(r['master_menu_id']): r for r in existing_records}

        return render_template('inventory/record_leftover.html',
                             location=location, menu_items=menu_items,
                             record_date=record_date, existing_data=existing_data)
    except Exception as e:
        flash(f'Error recording leftover food: {str(e)}', 'error')
        return redirect(url_for('inventory.leftover_food'))

# ===============================
# HELPER FUNCTIONS
# ===============================

def get_inventory_stats():
    """Get inventory dashboard statistics"""
    stats = {
        'total_master_items': 0,
        'total_locations': 0,
        'total_inventory_value': 0.0,
        'low_stock_items': 0,
        'active_purchase_lists': 0,
        'pending_alerts': 0,
        'today_usage_records': 0,
        'today_leftover_records': 0
    }

    try:
        # Total master inventory items
        result = execute_query_one("SELECT COUNT(*) as count FROM master_inventory WHERE is_active = TRUE")
        stats['total_master_items'] = result['count'] if result else 0

        # Total locations with inventory
        result = execute_query_one("SELECT COUNT(DISTINCT location_id) as count FROM location_inventory")
        stats['total_locations'] = result['count'] if result else 0

        # Total inventory value
        result = execute_query_one("""
            SELECT COALESCE(SUM(li.current_stock * mi.default_cost_per_unit), 0) as total
            FROM location_inventory li
            JOIN master_inventory mi ON li.master_inventory_id = mi.id
        """)
        stats['total_inventory_value'] = float(result['total']) if result else 0.0

        # Low stock items
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM location_inventory li
            WHERE li.current_stock <= li.reorder_point
        """)
        stats['low_stock_items'] = result['count'] if result else 0

        # Active purchase lists
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM purchase_lists
            WHERE status IN ('draft', 'submitted', 'approved')
        """)
        stats['active_purchase_lists'] = result['count'] if result else 0

        # Pending alerts
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM inventory_alerts
            WHERE is_resolved = FALSE
        """)
        stats['pending_alerts'] = result['count'] if result else 0

        # Today's usage records
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM daily_inventory_usage
            WHERE date = CURRENT_DATE
        """)
        stats['today_usage_records'] = result['count'] if result else 0

        # Today's leftover records
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM leftover_food_tracking
            WHERE date = CURRENT_DATE
        """)
        stats['today_leftover_records'] = result['count'] if result else 0

    except Exception as e:
        print(f"Error getting inventory stats: {e}")

    return stats

def update_purchase_list_total(list_id):
    """Update the total estimated cost of a purchase list"""
    try:
        result = execute_query_one("""
            SELECT COALESCE(SUM(total_cost), 0) as total
            FROM purchase_list_items
            WHERE purchase_list_id = %s
        """, (str(list_id),))

        total = result['total'] if result else 0.0

        execute_query("""
            UPDATE purchase_lists
            SET total_estimated_cost = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (total, str(list_id)))
    except Exception as e:
        print(f"Error updating purchase list total: {e}")
