from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import (execute_query, execute_query_one, execute_transaction,
                      morning_end_time, set_setting)
from .auth import login_required
from .helpers import get_current_staff_id
from security import scoped_location_id, owner_required, is_store_manager
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
import uuid

inventory_bp = Blueprint('inventory', __name__)


def _ist_today():
    """Current date on the IST calendar (timestamps are stored in UTC)."""
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def _worker_can_edit(entry_location_id, entry_ist_date):
    """Owners/managers may edit any entry. A worker (store manager) may only edit
    their own store's entries dated today (IST); older records lock to the owner."""
    if not is_store_manager():
        return True
    store = scoped_location_id()
    if not store or str(entry_location_id) != str(store):
        return False
    return entry_ist_date == _ist_today()


def _allocate_stock_ops(location_id, item_name, quantity, unit, staff_id, purchase_id,
                         master_inventory_id=None, minimum_stock_level=None, note_prefix='Purchase'):
    """Find-or-create the catalog item (case-insensitive name match, unless an
    explicit master_inventory_id override is given) and return the
    location_inventory + inventory_transactions statements that add this
    purchase's quantity onto that location's stock. The caller runs these
    immediately (a single purchase) or batches them into one
    execute_transaction() call (the scanned-bill save), alongside its own
    store_purchases insert.

    This is the one code path shared by Add Groceries, the manual Purchases
    form, and the scanned-bill save — so their stock math can't drift apart.
    minimum_stock_level follows a "blank (None) means don't change" rule via
    SQL COALESCE, so recording a purchase never wipes out a threshold that
    was set earlier.
    """
    if master_inventory_id:
        mi_id = str(master_inventory_id)
        execute_query("UPDATE master_inventory SET is_active = TRUE WHERE id = %s", (mi_id,))
    else:
        mi = execute_query_one("SELECT id FROM master_inventory WHERE lower(name) = lower(%s)", (item_name,))
        if mi:
            mi_id = str(mi['id'])
            execute_query("UPDATE master_inventory SET unit = %s, is_active = TRUE WHERE id = %s", (unit, mi_id))
        else:
            row = execute_query_one(
                "INSERT INTO master_inventory (name, category, unit, is_active) "
                "VALUES (%s, 'groceries', %s, TRUE) RETURNING id",
                (item_name, unit))
            mi_id = str(row['id'])

    inv = execute_query_one(
        "SELECT current_stock FROM location_inventory WHERE location_id = %s AND master_inventory_id = %s",
        (location_id, mi_id))
    previous_stock = Decimal(str(inv['current_stock'])) if inv else Decimal('0')
    new_stock = previous_stock + quantity

    ops = [
        ("""INSERT INTO location_inventory (location_id, master_inventory_id, current_stock,
                                             minimum_stock_level, last_restock_date, last_restock_quantity)
            VALUES (%s, %s, %s, COALESCE(%s, 0), CURRENT_DATE, %s)
            ON CONFLICT (location_id, master_inventory_id)
            DO UPDATE SET current_stock = location_inventory.current_stock + EXCLUDED.current_stock,
                          minimum_stock_level = COALESCE(%s, location_inventory.minimum_stock_level),
                          last_restock_date = CURRENT_DATE,
                          last_restock_quantity = EXCLUDED.last_restock_quantity,
                          last_updated = CURRENT_TIMESTAMP""",
         (location_id, mi_id, quantity, minimum_stock_level, quantity, minimum_stock_level)),
        ("""INSERT INTO inventory_transactions
                (location_id, master_inventory_id, transaction_type, quantity,
                 previous_stock, new_stock, recorded_by, reference_id, reference_type, notes)
            VALUES (%s, %s, 'restock', %s, %s, %s, %s, %s, 'store_purchase', %s)""",
         (location_id, mi_id, quantity, previous_stock, new_stock, staff_id, purchase_id,
          f'{note_prefix}: {item_name}')),
    ]
    return mi_id, ops

# ===============================
# MASTER INVENTORY MANAGEMENT
# ===============================

@inventory_bp.route('/')
@login_required
def index():
    """Inventory landing: owners manage groceries, managers record usage."""
    if is_store_manager():
        return redirect(url_for('inventory.daily_usage'))
    return redirect(url_for('inventory.groceries'))

@inventory_bp.route('/master-inventory')
@login_required
@owner_required
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
@owner_required
def add_master_item():
    """Add new master inventory item"""
    if request.method == 'POST':
        try:
            data = request.form
            supplier_id = data.get('supplier_id') if data.get('supplier_id') else None

            name = data['name'].strip()
            description = data.get('description')
            category = data['category']
            unit = data['unit']
            min_order_quantity = float(data.get('min_order_quantity', 1))
            default_cost = float(data.get('default_cost_per_unit', 0))
            barcode = data.get('barcode')

            existing_item = execute_query_one("""
                SELECT id, is_active FROM master_inventory
                WHERE LOWER(name) = LOWER(%s)
            """, (name,))

            if existing_item:
                if existing_item['is_active']:
                    flash('An active item with this name already exists.', 'error')
                    return redirect(request.url)

                execute_query("""
                    UPDATE master_inventory SET
                        description = %s,
                        category = %s,
                        unit = %s,
                        supplier_id = %s,
                        min_order_quantity = %s,
                        default_cost_per_unit = %s,
                        barcode = %s,
                        is_active = TRUE,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    description, category, unit, supplier_id,
                    min_order_quantity, default_cost, barcode,
                    existing_item['id']
                ))

                flash('Existing item reactivated and updated successfully!', 'success')
                return redirect(url_for('inventory.master_inventory'))

            execute_query("""
                INSERT INTO master_inventory (
                    name, description, category, unit, supplier_id,
                    min_order_quantity, default_cost_per_unit, barcode
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                name, description, category, unit,
                supplier_id, min_order_quantity, default_cost, barcode
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
@owner_required
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
@owner_required
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
            # A store-scoped manager's purchase lists belong to their own store.
            store = scoped_location_id()
            if store:
                location_id = store
            staff_id = get_current_staff_id()

            if not staff_id:
                flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
                return redirect(url_for('inventory.purchase_lists'))

            # Create purchase list
            list_id = str(uuid.uuid4())
            execute_query("""
                INSERT INTO purchase_lists (
                    id, location_id, name, description, created_by,
                    status, priority, required_by_date
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                list_id, location_id, data['name'], data.get('description'),
                staff_id, 'draft', data.get('priority', 'normal'),
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
# STORE PURCHASES (worker-recorded spend log — does not affect stock)
# ===============================

@inventory_bp.route('/purchases', methods=['GET', 'POST'])
@login_required
def purchases():
    """Workers log what they bought (item, quantity, price) with an IST
    timestamp. Every purchase also allocates: it finds-or-creates the
    matching catalog item (case-insensitive name match) and adds the
    purchased quantity onto this location's stock, exactly like Add
    Groceries — see _allocate_stock_ops()."""
    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    store = scoped_location_id()
    location_id = store or request.values.get('location_id') or (str(locations[0]['id']) if locations else '')

    if request.method == 'POST':
        location_id = store or request.form.get('location_id') or ''
        item_name = (request.form.get('item_name') or '').strip()
        unit = (request.form.get('unit') or 'pieces').strip()
        staff_id = get_current_staff_id()

        try:
            quantity = Decimal(str(request.form.get('quantity', '0')))
        except InvalidOperation:
            quantity = Decimal('-1')
        try:
            price = Decimal(str(request.form.get('price', '0')))
        except InvalidOperation:
            price = Decimal('-1')

        if not location_id or not item_name:
            flash('Choose a location and enter an item name.', 'error')
        elif quantity <= 0:
            flash('Quantity must be greater than zero.', 'error')
        elif price <= 0:
            flash('Price must be greater than zero.', 'error')
        elif not staff_id:
            flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
        else:
            purchase_id = str(uuid.uuid4())
            mi_id, alloc_ops = _allocate_stock_ops(location_id, item_name, quantity, unit,
                                                    staff_id, purchase_id, note_prefix='Purchase')
            ops = [(
                """INSERT INTO store_purchases
                   (id, location_id, item_name, quantity, unit, price, recorded_by, master_inventory_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (purchase_id, location_id, item_name, quantity, unit, price, staff_id, mi_id)
            )] + alloc_ops
            execute_transaction(ops)
            flash(f'Recorded purchase: {quantity} {unit} of {item_name} — added to stock.', 'success')
        return redirect(url_for('inventory.purchases', location_id=location_id))

    query = """
        SELECT sp.*, l.name as location_name, s.first_name, s.last_name,
               e.first_name AS editor_first_name, e.last_name AS editor_last_name
        FROM store_purchases sp
        JOIN locations l ON sp.location_id = l.id
        LEFT JOIN staff s ON sp.recorded_by = s.id
        LEFT JOIN staff e ON sp.edited_by = e.id
    """
    params = []
    if location_id:
        query += " WHERE sp.location_id = %s"
        params.append(location_id)
    query += " ORDER BY sp.purchased_at DESC LIMIT 200"

    records = execute_query(query, params, fetch=True) or []
    # Mark which rows the current user may edit (owner: any; worker: own store, today).
    for r in records:
        p_date = (r['purchased_at'] + timedelta(hours=5, minutes=30)).date() if r.get('purchased_at') else None
        r['editable'] = _worker_can_edit(r['location_id'], p_date)

    master_inventory_items = execute_query("""
        SELECT id, name, category, unit FROM master_inventory
        WHERE is_active = TRUE ORDER BY category, name
    """, fetch=True) or []

    return render_template('inventory/purchases.html',
                         locations=locations, location_id=location_id, records=records,
                         master_inventory_items=master_inventory_items)


@inventory_bp.route('/purchases/scan', methods=['POST'])
@login_required
@owner_required
def scan_purchase_bill():
    """Send a photo of a handwritten purchase list to Gemini (ocr.py) and
    return a draft list of items for the user to review — nothing is saved
    here. See templates/inventory/purchases.html for the crop/review UI."""
    photo = request.files.get('photo')
    if not photo or not photo.filename:
        return jsonify({'success': False, 'error': 'No photo was received.'}), 400
    try:
        import ocr
        items = ocr.extract_purchase_items(photo.read(), mime_type=photo.mimetype or 'image/jpeg')
        return jsonify({'success': True, 'items': items})
    except Exception as e:
        print(f"OCR scan failed: {e}")
        return jsonify({'success': False, 'error': 'Could not read that photo. Please try again or enter items manually.'}), 500


@inventory_bp.route('/purchases/bulk', methods=['POST'])
@login_required
@owner_required
def confirm_scanned_purchases():
    """Save a reviewed/edited batch of purchase rows (from the scan-bill
    flow). Every row allocates stock: it finds-or-creates the matching
    catalog item (case-insensitive name match) and adds the purchased
    quantity onto this location's stock — same as Add Groceries and the
    manual Purchases form (_allocate_stock_ops()). A reviewer can still pick
    an explicit catalog item per row (useful when OCR text doesn't exactly
    match an existing name); it's an override, not a requirement — unmatched
    rows auto-create instead of silently going nowhere. Everything commits
    together in one transaction, or none of it does."""
    data = request.get_json(silent=True) or {}
    location_id = data.get('location_id') or scoped_location_id()
    rows = data.get('rows') or []

    if not location_id:
        return jsonify({'success': False, 'error': 'A location is required.'}), 400
    if not rows:
        return jsonify({'success': False, 'error': 'No rows to save.'}), 400

    staff_id = get_current_staff_id()
    if not staff_id:
        return jsonify({'success': False, 'error': 'Your account is not linked to a staff record.'}), 400

    ops = []
    for row in rows:
        item_name = (row.get('item_name') or '').strip()
        try:
            quantity = Decimal(str(row.get('quantity', '0')))
            price = Decimal(str(row.get('price', '0')))
        except InvalidOperation:
            return jsonify({'success': False, 'error': f'Invalid quantity/price for "{item_name}".'}), 400
        unit = (row.get('unit') or 'pieces').strip()
        master_inventory_id = row.get('master_inventory_id') or None

        if not item_name or quantity <= 0 or price <= 0:
            return jsonify({'success': False, 'error': f'"{item_name or "(unnamed row)"}" needs a name, quantity, and price greater than zero.'}), 400

        purchase_id = str(uuid.uuid4())
        mi_id, alloc_ops = _allocate_stock_ops(location_id, item_name, quantity, unit, staff_id,
                                                purchase_id, master_inventory_id=master_inventory_id,
                                                note_prefix='Scanned purchase')
        ops.append((
            """INSERT INTO store_purchases
               (id, location_id, item_name, quantity, unit, price, recorded_by, master_inventory_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (purchase_id, location_id, item_name, quantity, unit, price, staff_id, mi_id)
        ))
        ops.extend(alloc_ops)

    try:
        execute_transaction(ops)
    except Exception as e:
        print(f"Error saving scanned purchases: {e}")
        return jsonify({'success': False, 'error': 'Failed to save. Nothing was recorded — please try again.'}), 500

    return jsonify({'success': True, 'saved': len(rows)})


@inventory_bp.route('/purchases/<uuid:purchase_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_purchase(purchase_id):
    """Correct a purchase entry. Owners may edit any; a worker may only edit their
    own store's same-day entries. Edits stamp edited_at/edited_by for the admin."""
    purchase = execute_query_one(
        "SELECT sp.*, l.name AS location_name FROM store_purchases sp "
        "JOIN locations l ON sp.location_id = l.id WHERE sp.id = %s", (str(purchase_id),))
    if not purchase:
        flash('Purchase record not found.', 'error')
        return redirect(url_for('inventory.purchases'))

    p_date = (purchase['purchased_at'] + timedelta(hours=5, minutes=30)).date() if purchase.get('purchased_at') else None
    if not _worker_can_edit(purchase['location_id'], p_date):
        flash('You can only edit your store\'s entries from today. Ask the owner to change older records.', 'error')
        return redirect(url_for('inventory.purchases'))

    if request.method == 'POST':
        item_name = (request.form.get('item_name') or '').strip()
        unit = (request.form.get('unit') or 'pieces').strip()
        staff_id = get_current_staff_id()
        try:
            quantity = Decimal(str(request.form.get('quantity', '0')))
        except InvalidOperation:
            quantity = Decimal('-1')
        try:
            price = Decimal(str(request.form.get('price', '0')))
        except InvalidOperation:
            price = Decimal('-1')

        if not item_name:
            flash('Enter an item name.', 'error')
        elif quantity <= 0:
            flash('Quantity must be greater than zero.', 'error')
        elif price <= 0:
            flash('Price must be greater than zero.', 'error')
        else:
            execute_query(
                "UPDATE store_purchases SET item_name=%s, quantity=%s, unit=%s, price=%s, "
                "edited_at=CURRENT_TIMESTAMP, edited_by=%s WHERE id=%s",
                (item_name, quantity, unit, price, staff_id, str(purchase_id)))
            flash('Purchase updated.', 'success')
            return redirect(url_for('inventory.purchases', location_id=str(purchase['location_id'])))

    return render_template('inventory/edit_purchase.html', purchase=purchase)

@inventory_bp.route('/purchases/<uuid:purchase_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_purchase(purchase_id):
    """Remove a mistaken purchase entry (owner only)."""
    execute_query("DELETE FROM store_purchases WHERE id = %s", (str(purchase_id),))
    flash('Purchase record removed.', 'success')
    return redirect(url_for('inventory.purchases'))

def _valid_date(raw, fallback):
    """Accept only a real YYYY-MM-DD date; anything else falls back. Dates
    arrive from the query string, so a bookmarked/edited/crawled URL can
    carry junk — without this it reaches SQL (or strptime) and 500s the
    page instead of just showing the default window."""
    if not raw:
        return fallback
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date().isoformat()
    except (ValueError, TypeError):
        return fallback


def _analytics_window():
    """Default date window (1st of the current month -> today, IST) plus
    whatever the request overrides, and the location filter. Every analytics
    page reads its from/to/location the same way, so switching between them
    (via the launcher tiles) carries the same window forward. Values are
    validated here so no downstream page has to re-check them."""
    ist_today = _ist_today()
    date_from = _valid_date(request.args.get('date_from'), ist_today.replace(day=1).isoformat())
    date_to = _valid_date(request.args.get('date_to'), ist_today.isoformat())
    # A reversed range (from > to) returns nothing and looks like a bug to the
    # user; swap it so the page shows the range they clearly meant.
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    location_filter = request.args.get('location', '')
    return date_from, date_to, location_filter


def _analytics_where(date_from, date_to, location_filter, alias='o'):
    """The one WHERE clause every sales-analytics query is built on: not
    cancelled, within the IST calendar date range, optionally one location.
    Sharing this (instead of copy-pasting the filter into each query) is what
    guarantees every number on the Analytics pages agrees with every other."""
    where = (f"WHERE {alias}.status != 'cancelled'"
             f" AND DATE(to_ist({alias}.created_at)) >= %s"
             f" AND DATE(to_ist({alias}.created_at)) <= %s")
    params = [date_from, date_to]
    if location_filter:
        where += f" AND {alias}.location_id = %s"
        params.append(location_filter)
    return where, params


@inventory_bp.route('/analytics')
@login_required
@owner_required
def analytics():
    """Admin-only sales-revenue analytics. READ-ONLY: it only aggregates the
    existing orders table (no writes, no schema changes). Revenue is defined
    exactly as on the Orders page: SUM(total_amount) for orders that are not
    cancelled, on the IST calendar date."""
    date_from, date_to, location_filter = _analytics_window()
    where, params = _analytics_where(date_from, date_to, location_filter)

    stats = {'total_orders': 0, 'total_revenue': 0.0, 'avg_order_value': 0.0,
             'cash_orders': 0, 'cash_revenue': 0.0,
             'phonepe_orders': 0, 'phonepe_revenue': 0.0}
    by_location, by_day = [], []
    try:
        row = execute_query_one(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(o.total_amount), 0) AS revenue, "
            "COALESCE(SUM(CASE WHEN COALESCE(o.payment_method,'cash')='cash' THEN o.total_amount ELSE 0 END), 0) AS cash_revenue, "
            "COUNT(*) FILTER (WHERE COALESCE(o.payment_method,'cash')='cash') AS cash_orders, "
            "COALESCE(SUM(CASE WHEN o.payment_method='phonepe' THEN o.total_amount ELSE 0 END), 0) AS phonepe_revenue, "
            "COUNT(*) FILTER (WHERE o.payment_method='phonepe') AS phonepe_orders "
            "FROM orders o " + where, tuple(params))
        if row:
            stats['total_orders'] = row['orders']
            stats['total_revenue'] = float(row['revenue'])
            stats['cash_orders'] = row['cash_orders']
            stats['cash_revenue'] = float(row['cash_revenue'])
            stats['phonepe_orders'] = row['phonepe_orders']
            stats['phonepe_revenue'] = float(row['phonepe_revenue'])
            if row['orders']:
                stats['avg_order_value'] = stats['total_revenue'] / row['orders']

        by_location = execute_query(
            "SELECT l.name AS location_name, COUNT(*) AS orders, "
            "COALESCE(SUM(o.total_amount), 0) AS revenue "
            "FROM orders o LEFT JOIN locations l ON o.location_id = l.id " + where +
            " GROUP BY l.name ORDER BY revenue DESC", tuple(params), fetch=True) or []

        by_day = execute_query(
            "SELECT DATE(to_ist(o.created_at)) AS day, "
            "COUNT(*) AS orders, COALESCE(SUM(o.total_amount), 0) AS revenue "
            "FROM orders o " + where +
            " GROUP BY day ORDER BY day DESC", tuple(params), fetch=True) or []
    except Exception as e:
        flash(f'Error loading analytics: {str(e)}', 'error')

    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics.html',
                         stats=stats, by_location=by_location, by_day=by_day,
                         locations=locations, date_from=date_from, date_to=date_to,
                         location_filter=location_filter)


@inventory_bp.route('/analytics/sale-trend')
@login_required
@owner_required
def analytics_sale_trend():
    """Sales over time, two ways:
      1. Per calendar date (revenue store-wide, or units sold for one chosen
         menu item — "idli sales per day" is the ?item= filter below), each
         point labeled with its weekday.
      2. Per day-of-week, averaged across the whole window — "which day
         actually performs best," independent of how many Mondays vs
         Fridays happened to fall in the selected range.
    Both share the same date-range/location filter as the rest of Analytics."""
    date_from, date_to, location_filter = _analytics_window()
    where, params = _analytics_where(date_from, date_to, location_filter)
    item_filter = request.args.get('item', '')

    trend = []
    metric = 'units' if item_filter else 'revenue'
    selected_item_name = None
    try:
        if item_filter:
            row = execute_query_one("SELECT name FROM master_menu WHERE id = %s", (item_filter,))
            selected_item_name = row['name'] if row else None
            rows = execute_query(
                "SELECT DATE(to_ist(o.created_at)) AS day, COUNT(DISTINCT o.id) AS orders, "
                "COALESCE(SUM(oi.quantity), 0) AS units "
                "FROM order_items oi JOIN orders o ON oi.order_id = o.id " + where +
                " AND oi.master_menu_id = %s"
                " GROUP BY day ORDER BY day", tuple(params + [item_filter]), fetch=True) or []
            for r in rows:
                trend.append({'day': r['day'].isoformat(), 'label': r['day'].strftime('%a, %-d %b'),
                               'orders': r['orders'], 'value': int(r['units'])})
        else:
            rows = execute_query(
                "SELECT DATE(to_ist(o.created_at)) AS day, COUNT(*) AS orders, "
                "COALESCE(SUM(o.total_amount), 0) AS revenue "
                "FROM orders o " + where +
                " GROUP BY day ORDER BY day", tuple(params), fetch=True) or []
            for r in rows:
                trend.append({'day': r['day'].isoformat(), 'label': r['day'].strftime('%a, %-d %b'),
                               'orders': r['orders'], 'value': float(r['revenue'])})
    except Exception as e:
        flash(f'Error loading sale trend: {str(e)}', 'error')

    # Day-of-week performance — average revenue per weekday across the whole
    # window, normalized by how many times that weekday actually occurred in
    # the range (so 3 Fridays vs 2 Mondays doesn't just favor whichever day
    # happened to occur more often in the chosen dates).
    weekday_avg = []
    try:
        dow_rows = execute_query(
            "SELECT EXTRACT(DOW FROM to_ist(o.created_at))::int AS pg_dow, "
            "COALESCE(SUM(o.total_amount), 0) AS revenue, COUNT(*) AS orders "
            "FROM orders o " + where + " GROUP BY pg_dow", tuple(params), fetch=True) or []
        revenue_by_dow = {(r['pg_dow'] + 6) % 7: float(r['revenue']) for r in dow_rows}  # -> Mon=0..Sun=6
        orders_by_dow = {(r['pg_dow'] + 6) % 7: r['orders'] for r in dow_rows}

        occurrences = [0] * 7
        d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
        d_to = datetime.strptime(date_to, '%Y-%m-%d').date()
        d = d_from
        while d <= d_to:
            occurrences[d.weekday()] += 1
            d += timedelta(days=1)

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        for i, name in enumerate(day_names):
            occ = occurrences[i] or 1
            weekday_avg.append({
                'day': name, 'short': name[:3],
                'avg_revenue': revenue_by_dow.get(i, 0.0) / occ,
                'avg_orders': orders_by_dow.get(i, 0) / occ,
                'occurrences': occurrences[i],
            })
    except Exception as e:
        flash(f'Error loading day-of-week trend: {str(e)}', 'error')

    items = execute_query("SELECT id, name FROM master_menu WHERE is_active = TRUE ORDER BY name", fetch=True) or []
    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics_sale_trend.html',
                            trend=trend, metric=metric, selected_item_name=selected_item_name,
                            weekday_avg=weekday_avg, items=items, item_filter=item_filter,
                            locations=locations,
                            date_from=date_from, date_to=date_to, location_filter=location_filter)


def _ingredient_usage_for_menu_item(menu_id, qty):
    """Ingredients that item's recipe implies for `qty` units sold, ranked by
    quantity consumed — the direct answer to "what did selling this many of
    this item actually cost us in stock." Empty if the item has no recipe."""
    rows = execute_query(
        "SELECT mi.name, mi.unit, ri.quantity_per_unit "
        "FROM recipe_items ri JOIN master_inventory mi ON mi.id = ri.master_inventory_id "
        "WHERE ri.master_menu_id = %s", (str(menu_id),), fetch=True) or []
    usage = [{'name': r['name'], 'unit': r['unit'],
              'per_unit': float(r['quantity_per_unit']),
              'total_used': float(r['quantity_per_unit']) * qty} for r in rows]
    usage.sort(key=lambda u: u['total_used'], reverse=True)
    return usage


@inventory_bp.route('/analytics/item-trend')
@login_required
@owner_required
def analytics_item_trend():
    """Menu items ranked by quantity sold, not revenue — a kitchen judges
    'popular' by units going out the door, not money taken in. The top
    seller's ingredient usage is shown right here (no click needed) since
    "what's selling + what it's costing us in stock" is one question, not
    two — every other item is one click away from the same breakdown."""
    date_from, date_to, location_filter = _analytics_window()
    where, params = _analytics_where(date_from, date_to, location_filter)
    rows = []
    try:
        rows = execute_query(
            "SELECT oi.master_menu_id, oi.item_name, SUM(oi.quantity) AS qty, "
            "COALESCE(SUM(oi.total_price), 0) AS revenue "
            "FROM order_items oi JOIN orders o ON oi.order_id = o.id " + where +
            " GROUP BY oi.master_menu_id, oi.item_name ORDER BY qty DESC", tuple(params), fetch=True) or []
    except Exception as e:
        flash(f'Error loading item trend: {str(e)}', 'error')

    items = [{'item_name': r['item_name'], 'qty': int(r['qty']), 'revenue': float(r['revenue']),
              'master_menu_id': str(r['master_menu_id']) if r['master_menu_id'] else None} for r in rows]
    top_item = items[0] if items else None
    top_item_usage = []
    if top_item and top_item['master_menu_id']:
        top_item_usage = _ingredient_usage_for_menu_item(top_item['master_menu_id'], top_item['qty'])

    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics_item_trend.html',
                            items=items, top_item=top_item, top_item_usage=top_item_usage,
                            locations=locations,
                            date_from=date_from, date_to=date_to, location_filter=location_filter)


@inventory_bp.route('/analytics/item-trend/<uuid:menu_id>/usage')
@login_required
@owner_required
def analytics_item_usage(menu_id):
    """JSON: this item's quantity sold + ingredient usage, for the same
    date-range/location window — powers the click-to-drill-down on any bar
    in Item Trend, not just the top seller."""
    date_from, date_to, location_filter = _analytics_window()
    where, params = _analytics_where(date_from, date_to, location_filter)
    row = execute_query_one(
        "SELECT oi.item_name, SUM(oi.quantity) AS qty "
        "FROM order_items oi JOIN orders o ON oi.order_id = o.id " + where +
        " AND oi.master_menu_id = %s GROUP BY oi.item_name",
        tuple(params + [str(menu_id)]))
    if not row:
        return jsonify({'success': True, 'item_name': None, 'qty': 0, 'ingredients': []})
    qty = int(row['qty'])
    ingredients = _ingredient_usage_for_menu_item(menu_id, qty)
    return jsonify({'success': True, 'item_name': row['item_name'], 'qty': qty, 'ingredients': ingredients})


@inventory_bp.route('/analytics/peak-hours')
@login_required
@owner_required
def analytics_peak_hours():
    """Revenue through a single chosen day, hour by hour, plus what sold in
    the busiest hour. Defaults to the end of the current window (usually
    'today') so a bare click into the page shows something."""
    date_from, date_to, location_filter = _analytics_window()
    selected_date = _valid_date(request.args.get('date'), date_to)

    where = "WHERE o.status != 'cancelled' AND DATE(to_ist(o.created_at)) = %s"
    params = [selected_date]
    if location_filter:
        where += " AND o.location_id = %s"
        params.append(location_filter)

    by_hour_rows = []
    try:
        by_hour_rows = execute_query(
            "SELECT EXTRACT(HOUR FROM to_ist(o.created_at))::int AS hour, "
            "COUNT(*) AS orders, COALESCE(SUM(o.total_amount), 0) AS revenue "
            "FROM orders o " + where +
            " GROUP BY hour ORDER BY hour", tuple(params), fetch=True) or []
    except Exception as e:
        flash(f'Error loading peak hours: {str(e)}', 'error')

    # Every item sold in every hour, in one query — powers the hover tooltip
    # (each hour's own item breakdown, not just the peak hour's) and the
    # single-item label drawn above the peak point on the line.
    items_by_hour = {}
    try:
        item_hour_rows = execute_query(
            "SELECT EXTRACT(HOUR FROM to_ist(o.created_at))::int AS hour, "
            "oi.item_name, SUM(oi.quantity) AS qty "
            "FROM order_items oi JOIN orders o ON oi.order_id = o.id "
            "WHERE o.status != 'cancelled' AND DATE(to_ist(o.created_at)) = %s"
            + (" AND o.location_id = %s" if location_filter else "") +
            " GROUP BY hour, oi.item_name",
            tuple([selected_date] + ([location_filter] if location_filter else [])),
            fetch=True) or []
        for r in item_hour_rows:
            items_by_hour.setdefault(r['hour'], []).append({'name': r['item_name'], 'qty': r['qty']})
        for h in items_by_hour:
            items_by_hour[h].sort(key=lambda i: i['qty'], reverse=True)
    except Exception as e:
        flash(f'Error loading hourly items: {str(e)}', 'error')

    by_hour = {r['hour']: r for r in by_hour_rows}
    hours = []
    peak_hour, peak_revenue = None, -1.0
    for h in range(24):
        r = by_hour.get(h)
        revenue = float(r['revenue']) if r else 0.0
        orders = r['orders'] if r else 0
        top = items_by_hour.get(h, [None])[0]
        hours.append({'hour': h, 'orders': orders, 'revenue': revenue,
                       'items': items_by_hour.get(h, []),
                       'top_item': top['name'] if top else None,
                       'top_item_qty': top['qty'] if top else None})
        if revenue > peak_revenue:
            peak_revenue = revenue
            peak_hour = h

    # What sold in the peak hour, for the "Peak Hour" card — same data
    # already computed above, just picked out for that one hour.
    peak_items = items_by_hour.get(peak_hour, []) if peak_hour is not None else []

    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics_peak_hours.html',
                            hours=hours, peak_hour=peak_hour, peak_revenue=peak_revenue,
                            peak_items=peak_items, selected_date=selected_date,
                            locations=locations, date_from=date_from, date_to=date_to,
                            location_filter=location_filter)


def _daily_sales_consumption(date_from, date_to, location_filter):
    """The core chain this page exists for: SALES -> RECIPE -> GROCERY
    CONSUMPTION, computed fresh from real orders and real recipes — never a
    manual calculation, never hardcoded. Returns:
      period_items: [{item_name, qty, master_menu_id, has_recipe, ingredients:
          [{name, unit, per_unit, consumed}]}] — every item sold in the whole
          window, aggregated, each with its own recipe breakdown.
      period_grocery: [{master_inventory_id, name, unit, qty}] — every
          grocery's TOTAL consumption across all sold items, combined (this
          is "Total Rava consumed = 1.10 kg" from multiple items).
      days: same shape as period_items/period_grocery but split per calendar
          date (IST), most recent first — "for each date, what sold and what
          it consumed."
      no_recipe_items: [{item_name, qty}] — sold but no recipe configured,
          shown explicitly rather than silently dropped.
    Only sales in the given date range/location contribute, matching every
    other Analytics page's filter."""
    where, params = _analytics_where(date_from, date_to, location_filter)
    sold_rows = execute_query(
        "SELECT DATE(to_ist(o.created_at)) AS day, oi.master_menu_id, oi.item_name, "
        "SUM(oi.quantity) AS qty "
        "FROM order_items oi JOIN orders o ON oi.order_id = o.id " + where +
        " GROUP BY day, oi.master_menu_id, oi.item_name ORDER BY day, qty DESC",
        tuple(params), fetch=True) or []

    menu_ids = list({r['master_menu_id'] for r in sold_rows if r['master_menu_id']})
    recipe_by_menu = {}
    if menu_ids:
        recipe_rows = execute_query(
            "SELECT ri.master_menu_id, mi.id AS master_inventory_id, mi.name, mi.unit, "
            "ri.quantity_per_unit FROM recipe_items ri "
            "JOIN master_inventory mi ON mi.id = ri.master_inventory_id "
            "WHERE ri.master_menu_id = ANY(%s::uuid[]) ORDER BY mi.name",
            ([str(m) for m in menu_ids],), fetch=True) or []
        for r in recipe_rows:
            recipe_by_menu.setdefault(r['master_menu_id'], []).append({
                'master_inventory_id': str(r['master_inventory_id']),
                'name': r['name'], 'unit': r['unit'], 'per_unit': float(r['quantity_per_unit']),
            })

    def _ingredients_for(recipe, qty):
        return [{'name': ri['name'], 'unit': ri['unit'], 'per_unit': ri['per_unit'],
                  'consumed': ri['per_unit'] * qty} for ri in recipe]

    # --- Per-day breakdown ---
    days_map = {}
    for r in sold_rows:
        day_iso = r['day'].isoformat()
        qty = int(r['qty'])
        recipe = recipe_by_menu.get(r['master_menu_id']) if r['master_menu_id'] else None
        day = days_map.setdefault(day_iso, {
            'date': day_iso, 'label': r['day'].strftime('%a, %-d %b'),
            'sold_items': [], 'grocery_totals': {},
        })
        if recipe:
            ingredients = _ingredients_for(recipe, qty)
            day['sold_items'].append({'item_name': r['item_name'], 'qty': qty,
                                   'has_recipe': True, 'ingredients': ingredients})
            for ing in ingredients:
                slot = day['grocery_totals'].setdefault(ing['name'], dict(ing, qty=0.0))
                slot['qty'] += ing['consumed']
        else:
            day['sold_items'].append({'item_name': r['item_name'], 'qty': qty,
                                   'has_recipe': False, 'ingredients': []})

    days = []
    for d in days_map.values():
        d['grocery_totals'] = sorted(d['grocery_totals'].values(), key=lambda g: g['qty'], reverse=True)
        days.append(d)
    days.sort(key=lambda d: d['date'], reverse=True)

    # --- Period aggregate (sum of the days above, same numbers either way) ---
    item_totals = {}
    for r in sold_rows:
        key = r['master_menu_id'] or r['item_name']
        slot = item_totals.setdefault(key, {'item_name': r['item_name'], 'qty': 0,
                                              'master_menu_id': r['master_menu_id']})
        slot['qty'] += int(r['qty'])

    period_items, period_grocery_map, no_recipe_items = [], {}, []
    for slot in item_totals.values():
        recipe = recipe_by_menu.get(slot['master_menu_id']) if slot['master_menu_id'] else None
        if recipe:
            ingredients = _ingredients_for(recipe, slot['qty'])
            period_items.append({**slot, 'has_recipe': True, 'ingredients': ingredients})
            for ing in ingredients:
                pslot = period_grocery_map.setdefault(ing['name'], dict(ing, qty=0.0))
                pslot['qty'] += ing['consumed']
        else:
            period_items.append({**slot, 'has_recipe': False, 'ingredients': []})
            no_recipe_items.append({'item_name': slot['item_name'], 'qty': slot['qty']})

    period_items.sort(key=lambda x: x['qty'], reverse=True)
    period_grocery = sorted(period_grocery_map.values(), key=lambda g: g['qty'], reverse=True)
    no_recipe_items.sort(key=lambda x: x['qty'], reverse=True)

    return period_items, period_grocery, days, no_recipe_items


@inventory_bp.route('/analytics/inventory-trend')
@login_required
@owner_required
def analytics_inventory_trend():
    """DAILY SALES -> INGREDIENT CONSUMPTION -> INVENTORY USAGE. Answers:
    "we sold these many food items — which groceries did that consume, and
    how much of each?" Consumption is computed automatically from real sales
    x each item's recipe (Master Menu -> Recipe) so nobody has to do that
    arithmetic by hand. For context only (not the headline), each grocery
    also shows what's already logged in Record Usage for the same window, so
    a manager can see the calculated number before typing it in there —
    Record Usage itself is untouched; this page only reads it."""
    date_from, date_to, location_filter = _analytics_window()
    period_items, period_grocery, days, no_recipe_items = _daily_sales_consumption(
        date_from, date_to, location_filter)

    # Small secondary reference: what's already recorded in Record Usage for
    # each grocery in this window (by name, since period_grocery is keyed by
    # name — two ingredients never share a name).
    recorded = {}
    try:
        usage_where = "WHERE du.date >= %s AND du.date <= %s"
        usage_params = [date_from, date_to]
        if location_filter:
            usage_where += " AND du.location_id = %s"
            usage_params.append(location_filter)
        usage_rows = execute_query(
            "SELECT mi.name, COALESCE(SUM(du.used_quantity), 0) AS used "
            "FROM daily_inventory_usage du "
            "JOIN master_inventory mi ON du.master_inventory_id = mi.id " + usage_where +
            " GROUP BY mi.name", tuple(usage_params), fetch=True) or []
        recorded = {r['name']: float(r['used']) for r in usage_rows}
    except Exception as e:
        flash(f'Error loading Record Usage reference: {str(e)}', 'error')

    for g in period_grocery:
        g['recorded'] = recorded.get(g['name'])

    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics_inventory_trend.html',
                            period_items=period_items, period_grocery=period_grocery,
                            days=days, no_recipe_items=no_recipe_items, locations=locations,
                            date_from=date_from, date_to=date_to, location_filter=location_filter)


@inventory_bp.route('/analytics/stock-runway')
@login_required
@owner_required
def analytics_stock_runway():
    """How many days the remaining stock will last, measured against real
    restock-and-consume history rather than a flat average over whatever
    date range happens to be selected.

    Basis (?basis=):
      'purchase' (default) — the consumption window starts on the day this
          grocery was last restocked. That's the honest baseline: 20kg rice
          bought on Aug 1, 14kg consumed by Aug 14, is 1kg/day — averaging
          over days before the purchase would understate the burn rate.
      '14day' — normalize to the most recent 14 days instead, for a stable
          recent-demand rate when purchases are irregular.

    A "restock" is any stock addition, from either screen: the Purchases
    form (store_purchases) or Add Groceries (inventory_transactions, type
    'restock'). Both are unioned so neither path is invisible here.
    """
    date_from, date_to, location_filter = _analytics_window()
    basis = request.args.get('basis') or 'purchase'
    if basis not in ('purchase', '14day'):
        basis = 'purchase'

    where = "WHERE mi.is_active = TRUE"
    params = []
    if location_filter:
        where += " AND li.location_id = %s"
        params.append(location_filter)

    rows = []
    try:
        # window_start per ingredient: last restock date ('purchase' basis) or
        # a fixed 14-day lookback. Consumption is then summed from that start
        # through date_to, and averaged over the days actually elapsed.
        rows = execute_query(f"""
            WITH restocks AS (
                SELECT location_id, master_inventory_id,
                       purchased_at::date AS restock_date, quantity
                FROM store_purchases
                WHERE master_inventory_id IS NOT NULL AND purchased_at::date <= %s
                UNION ALL
                SELECT location_id, master_inventory_id,
                       transaction_date AS restock_date, quantity
                FROM inventory_transactions
                WHERE transaction_type = 'restock' AND transaction_date <= %s
            ),
            latest_restock AS (
                SELECT DISTINCT ON (location_id, master_inventory_id)
                       location_id, master_inventory_id, restock_date, quantity
                FROM restocks
                ORDER BY location_id, master_inventory_id, restock_date DESC
            )
            SELECT l.name AS location_name, mi.name, mi.unit,
                   li.current_stock,
                   lr.restock_date, lr.quantity AS purchased_qty,
                   COALESCE(u.consumed, 0) AS consumed,
                   u.window_start, u.window_end
            FROM location_inventory li
            JOIN master_inventory mi ON mi.id = li.master_inventory_id
            JOIN locations l ON l.id = li.location_id
            LEFT JOIN latest_restock lr
                   ON lr.location_id = li.location_id
                  AND lr.master_inventory_id = li.master_inventory_id
            LEFT JOIN LATERAL (
                SELECT SUM(du.used_quantity) AS consumed,
                       MIN(du.date) AS window_start, MAX(du.date) AS window_end
                FROM daily_inventory_usage du
                WHERE du.location_id = li.location_id
                  AND du.master_inventory_id = li.master_inventory_id
                  AND du.date <= %s
                  AND du.date >= CASE WHEN %s = '14day'
                                      THEN (%s::date - INTERVAL '13 days')::date
                                      ELSE COALESCE(lr.restock_date, %s::date) END
            ) u ON TRUE
            {where}
        """, tuple([date_to, date_to, date_to, basis, date_to, date_from] + params),
            fetch=True) or []
    except Exception as e:
        flash(f'Error loading stock runway: {str(e)}', 'error')

    ist_today = _ist_today()
    window_end_date = min(datetime.strptime(date_to, '%Y-%m-%d').date(), ist_today)

    runway = []
    for r in rows:
        current_stock = float(r['current_stock'] or 0)
        consumed = float(r['consumed'] or 0)
        restock_date = r['restock_date']

        # Days the consumption is spread over. On the purchase basis that's
        # (today - purchase date); on the 14-day basis it's a flat 14.
        if basis == '14day':
            days_elapsed = 14
            window_start = window_end_date - timedelta(days=13)
        else:
            window_start = restock_date or datetime.strptime(date_from, '%Y-%m-%d').date()
            days_elapsed = max((window_end_date - window_start).days + 1, 1)

        avg_daily = consumed / days_elapsed if days_elapsed else 0.0
        days_left = (current_stock / avg_daily) if avg_daily > 0 else None

        if days_left is None:
            status = 'unknown'
        elif days_left < 2:
            status = 'critical'
        elif days_left < 5:
            status = 'warning'
        else:
            status = 'good'

        runway.append({
            'location_name': r['location_name'], 'name': r['name'], 'unit': r['unit'],
            'current_stock': current_stock,
            'purchased_qty': float(r['purchased_qty']) if r['purchased_qty'] is not None else None,
            'restock_date': restock_date.isoformat() if restock_date else None,
            'consumed': consumed, 'days_elapsed': days_elapsed,
            'window_start': window_start.isoformat(),
            'avg_daily': avg_daily, 'days_left': days_left, 'status': status,
        })
    # Most urgent first; ingredients with no consumption rate sink to the bottom.
    runway.sort(key=lambda x: x['days_left'] if x['days_left'] is not None else float('inf'))

    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics_stock_runway.html',
                            runway=runway, locations=locations, basis=basis,
                            window_end=window_end_date.isoformat(),
                            date_from=date_from, date_to=date_to, location_filter=location_filter)


@inventory_bp.route('/analytics/category-mix', methods=['GET', 'POST'])
@login_required
@owner_required
def analytics_category_mix():
    """Revenue and quantity sold, grouped by menu category — which parts of
    the menu actually drive revenue, ranked as bars rather than a pie (easier
    to compare 4-5 categories as bar lengths than wedge angles).

    Each category is additionally split into the MORNING and EVENING service,
    side by side, so "are Tiffins earning more at breakfast or at snack time?"
    is answerable at a glance. The boundary between the two is the shared
    `meal_period_morning_end` setting (database.morning_end_time) — the same
    one the PDF sales report uses, editable from this page, so the two can
    never drift apart the way the old hard-coded literals did."""
    # Saving the meal boundary posts back to this same page.
    if request.method == 'POST':
        raw = (request.form.get('morning_end') or '').strip()
        try:
            hh, mm = raw.split(':')[:2]
            hh, mm = int(hh), int(mm)
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
            set_setting('meal_period_morning_end', f'{hh:02d}:{mm:02d}')
            flash(f'Morning service now ends at {hh:02d}:{mm:02d}. All reports use this boundary.', 'success')
        except (ValueError, AttributeError):
            flash('Enter a valid time in HH:MM format.', 'error')
        return redirect(url_for('inventory.analytics_category_mix',
                                 date_from=request.form.get('date_from'),
                                 date_to=request.form.get('date_to'),
                                 location=request.form.get('location')))

    date_from, date_to, location_filter = _analytics_window()
    where, params = _analytics_where(date_from, date_to, location_filter)
    morning_end = morning_end_time()

    rows = []
    try:
        # One pass, split by the configured boundary. The CASE mirrors the
        # sales report exactly: at/before the boundary = morning.
        rows = execute_query(
            "SELECT COALESCE(mm.category, 'Uncategorized') AS category, "
            "CASE WHEN to_ist(o.created_at)::time <= TIME %s THEN 'morning' ELSE 'evening' END AS period, "
            "COALESCE(SUM(oi.total_price), 0) AS revenue, COALESCE(SUM(oi.quantity), 0) AS qty "
            "FROM order_items oi JOIN orders o ON oi.order_id = o.id "
            "LEFT JOIN master_menu mm ON oi.master_menu_id = mm.id " + where +
            " GROUP BY category, period", tuple([morning_end] + params), fetch=True) or []
    except Exception as e:
        flash(f'Error loading category mix: {str(e)}', 'error')

    by_category = {}
    for r in rows:
        slot = by_category.setdefault(r['category'], {
            'category': r['category'], 'revenue': 0.0, 'qty': 0,
            'morning_revenue': 0.0, 'morning_qty': 0,
            'evening_revenue': 0.0, 'evening_qty': 0,
        })
        revenue, qty = float(r['revenue']), int(r['qty'])
        slot['revenue'] += revenue
        slot['qty'] += qty
        slot[f"{r['period']}_revenue"] += revenue
        slot[f"{r['period']}_qty"] += qty

    mix = sorted(by_category.values(), key=lambda c: c['revenue'], reverse=True)
    total_revenue = sum(c['revenue'] for c in mix) or 1.0
    for c in mix:
        c['pct'] = c['revenue'] / total_revenue * 100
        # Share of THIS category split between the two services (bars are
        # relative to the category, not the whole menu, so a small category
        # still shows a readable morning/evening ratio).
        cat_total = c['revenue'] or 1.0
        c['morning_pct'] = c['morning_revenue'] / cat_total * 100
        c['evening_pct'] = c['evening_revenue'] / cat_total * 100

    totals = {
        'morning_revenue': sum(c['morning_revenue'] for c in mix),
        'evening_revenue': sum(c['evening_revenue'] for c in mix),
        'morning_qty': sum(c['morning_qty'] for c in mix),
        'evening_qty': sum(c['evening_qty'] for c in mix),
    }

    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics_category_mix.html',
                            mix=mix, totals=totals, morning_end=morning_end, locations=locations,
                            date_from=date_from, date_to=date_to, location_filter=location_filter)


@inventory_bp.route('/analytics/profitability')
@login_required
@owner_required
def analytics_profitability():
    """What every other page here is missing: MARGIN, not just revenue.
    Cost-to-make is derived from recipe_items x each ingredient's average
    purchase price over the last 90 days (recent, not stale) — so it stays
    current automatically as your actual buying prices change, no manual
    cost entry to maintain. Items ranked by TOTAL PROFIT CONTRIBUTED
    (margin/unit x units sold in the window), not revenue or margin % alone —
    the number that actually answers "what's worth pushing." An item with no
    recipe, or a recipe ingredient with no recent purchase logged, shows as
    cost-unknown rather than a silently wrong number."""
    date_from, date_to, location_filter = _analytics_window()
    where, params = _analytics_where(date_from, date_to, location_filter)

    ingredient_costs, sales_rows = {}, []
    try:
        cost_rows = execute_query("""
            SELECT master_inventory_id, AVG(price / quantity) AS avg_unit_cost
            FROM store_purchases
            WHERE master_inventory_id IS NOT NULL AND quantity > 0
              AND purchased_at >= NOW() - INTERVAL '90 days'
            GROUP BY master_inventory_id
        """, fetch=True) or []
        ingredient_costs = {str(r['master_inventory_id']): Decimal(str(r['avg_unit_cost'])) for r in cost_rows}

        sales_rows = execute_query(
            "SELECT oi.master_menu_id, oi.item_name, SUM(oi.quantity) AS qty, "
            "COALESCE(SUM(oi.total_price), 0) AS revenue "
            "FROM order_items oi JOIN orders o ON oi.order_id = o.id " + where +
            " AND oi.master_menu_id IS NOT NULL "
            " GROUP BY oi.master_menu_id, oi.item_name ORDER BY revenue DESC",
            tuple(params), fetch=True) or []
    except Exception as e:
        flash(f'Error loading profitability: {str(e)}', 'error')

    # Recipe for every menu item that sold in this window, in one query.
    menu_ids = [r['master_menu_id'] for r in sales_rows]
    recipes_by_menu = {}
    if menu_ids:
        recipe_rows = execute_query(
            "SELECT master_menu_id, master_inventory_id, quantity_per_unit "
            "FROM recipe_items WHERE master_menu_id = ANY(%s::uuid[])",
            ([str(m) for m in menu_ids],), fetch=True) or []
        for r in recipe_rows:
            recipes_by_menu.setdefault(str(r['master_menu_id']), []).append(r)

    items = []
    for r in sales_rows:
        mm_id = str(r['master_menu_id'])
        qty = int(r['qty'])
        revenue = float(r['revenue'])
        avg_price = revenue / qty if qty else 0.0
        recipe = recipes_by_menu.get(mm_id)

        cost_per_unit = None
        if recipe:
            total_cost = Decimal('0')
            all_known = True
            for ri in recipe:
                unit_cost = ingredient_costs.get(str(ri['master_inventory_id']))
                if unit_cost is None:
                    all_known = False
                    break
                total_cost += unit_cost * Decimal(str(ri['quantity_per_unit']))
            if all_known:
                cost_per_unit = float(total_cost)

        entry = {'item_name': r['item_name'], 'qty': qty, 'revenue': revenue, 'avg_price': avg_price,
                  'has_recipe': bool(recipe), 'cost_per_unit': cost_per_unit}
        if cost_per_unit is not None:
            profit_per_unit = avg_price - cost_per_unit
            entry['profit_per_unit'] = profit_per_unit
            entry['margin_pct'] = (profit_per_unit / avg_price * 100) if avg_price else 0.0
            entry['total_profit'] = profit_per_unit * qty
        else:
            entry['profit_per_unit'] = entry['margin_pct'] = entry['total_profit'] = None
        items.append(entry)

    # Known-cost items ranked by total profit contributed (the headline view);
    # unknown-cost items listed separately so they don't get silently buried
    # at the bottom by a None sort key.
    known = sorted([i for i in items if i['cost_per_unit'] is not None],
                    key=lambda i: i['total_profit'], reverse=True)
    unknown = [i for i in items if i['cost_per_unit'] is None]

    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    return render_template('inventory/analytics_profitability.html',
                            known=known, unknown=unknown, locations=locations,
                            date_from=date_from, date_to=date_to, location_filter=location_filter)


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

        # A store-scoped manager only sees their own store's inventory.
        store = scoped_location_id()
        if store:
            location_id = store

        query = """
            SELECT li.*, mi.name as item_name, mi.category, mi.unit,
                   l.name as location_name,
                   CASE
                       WHEN li.current_stock <= 0 THEN 'out_of_stock'
                       WHEN li.current_stock <= li.minimum_stock_level THEN 'low_stock'
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
            query += " AND li.current_stock <= li.minimum_stock_level"

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

@inventory_bp.route('/groceries', methods=['GET', 'POST'])
@login_required
@owner_required
def groceries():
    """Clean admin flow: add a grocery purchase and allocate it to a location.
    Creates the grocery in the catalog if new, then adds the purchased quantity
    to that location's stock. The remaining stock here is the 'leftover' the
    owner sees after store managers record their usage."""
    locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []
    location_id = request.values.get('location_id') or (str(locations[0]['id']) if locations else '')

    if request.method == 'POST':
        location_id = request.form.get('location_id') or ''
        name = (request.form.get('name') or '').strip()
        unit = (request.form.get('unit') or 'unit').strip() or 'unit'
        staff_id = get_current_staff_id()
        try:
            qty = Decimal(str(request.form.get('quantity', '0')))
        except InvalidOperation:
            qty = Decimal('-1')
        min_stock_raw = (request.form.get('minimum_stock_level') or '').strip()
        try:
            min_stock = Decimal(min_stock_raw) if min_stock_raw else None
        except InvalidOperation:
            min_stock = None

        if not location_id or not name:
            flash('Choose a location and enter a grocery name.', 'error')
        elif qty <= 0:
            flash('Quantity must be greater than zero.', 'error')
        else:
            purchase_id = str(uuid.uuid4())
            mi_id, ops = _allocate_stock_ops(location_id, name, qty, unit, staff_id, purchase_id,
                                              minimum_stock_level=min_stock, note_prefix='Groceries')
            execute_transaction(ops)
            flash(f'Allocated {qty} {unit} of {name}.', 'success')
        return redirect(url_for('inventory.groceries', location_id=location_id))

    allocated = []
    low_count = 0
    if location_id:
        allocated = execute_query("""
            SELECT mi.name, mi.unit, li.current_stock, li.master_inventory_id,
                   li.minimum_stock_level, li.last_restock_date, li.last_restock_quantity,
                   CASE
                       WHEN li.current_stock <= 0 THEN 'out_of_stock'
                       WHEN li.current_stock <= li.minimum_stock_level THEN 'low_stock'
                       ELSE 'normal'
                   END AS stock_status
            FROM location_inventory li
            JOIN master_inventory mi ON mi.id = li.master_inventory_id
            WHERE li.location_id = %s AND mi.is_active = TRUE
            ORDER BY mi.name
        """, (location_id,), fetch=True) or []
        low_count = sum(1 for r in allocated if r['stock_status'] in ('low_stock', 'out_of_stock'))

    # Existing catalog items (name + unit) for the "type a name, get an
    # existing item's unit prefilled" autocomplete — steers a scanned-bill
    # name like "Panchadara (Sugar)" back onto the same catalog row as "Sugar"
    # instead of creating a near-duplicate.
    catalog_items = execute_query(
        "SELECT name, unit FROM master_inventory WHERE is_active = TRUE ORDER BY name",
        fetch=True) or []

    return render_template('inventory/groceries.html',
                           locations=locations, location_id=location_id, allocated=allocated,
                           low_count=low_count, catalog_items=catalog_items)

@inventory_bp.route('/groceries/<uuid:location_id>/<uuid:item_id>/remove', methods=['POST'])
@login_required
@owner_required
def remove_grocery(location_id, item_id):
    """Remove a grocery allocation from a location."""
    execute_query("DELETE FROM location_inventory WHERE location_id = %s AND master_inventory_id = %s",
                  (str(location_id), str(item_id)))
    flash('Grocery removed from this location.', 'success')
    return redirect(url_for('inventory.groceries', location_id=str(location_id)))

@inventory_bp.route('/location-inventory/<uuid:location_id>/assign', methods=['GET', 'POST'])
@login_required
@owner_required
def assign_location_inventory(location_id):
    """Assign master inventory items to a specific location."""
    store = scoped_location_id()
    if store and str(location_id) != store:
        flash('You can only manage your own store.', 'error')
        return redirect(url_for('inventory.location_inventory'))
    try:
        location = execute_query_one("SELECT id, name FROM locations WHERE id = %s", (str(location_id),))
        if not location:
            flash('Location not found', 'error')
            return redirect(url_for('inventory.location_inventory'))

        if request.method == 'POST':
            data = request.form
            master_inventory_id = data.get('master_inventory_id')

            if not master_inventory_id:
                flash('Please select an ingredient to assign.', 'error')
                return redirect(request.url)

            try:
                current_stock = Decimal(str(data.get('current_stock', 0)))
                minimum_stock = Decimal(str(data.get('minimum_stock_level', 0)))
            except InvalidOperation:
                flash('Invalid numeric value provided.', 'error')
                return redirect(request.url)

            if minimum_stock < 0 or current_stock < 0:
                flash('Stock levels cannot be negative.', 'error')
                return redirect(request.url)

            execute_query("""
                INSERT INTO location_inventory (
                    location_id, master_inventory_id, current_stock, minimum_stock_level
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (location_id, master_inventory_id)
                DO UPDATE SET
                    current_stock = EXCLUDED.current_stock,
                    minimum_stock_level = EXCLUDED.minimum_stock_level,
                    last_updated = CURRENT_TIMESTAMP
            """, (
                str(location_id), master_inventory_id, current_stock, minimum_stock
            ))

            flash('Ingredient assigned to location inventory.', 'success')
            return redirect(request.url)

        assigned_items = execute_query("""
            SELECT li.*, mi.name, mi.unit, mi.category
            FROM location_inventory li
            JOIN master_inventory mi ON li.master_inventory_id = mi.id
            WHERE li.location_id = %s
            ORDER BY mi.category, mi.name
        """, (str(location_id),), fetch=True) or []

        available_items = execute_query("""
            SELECT mi.id, mi.name, mi.category, mi.unit
            FROM master_inventory mi
            WHERE mi.is_active = TRUE
              AND mi.id NOT IN (
                  SELECT master_inventory_id
                  FROM location_inventory
                  WHERE location_id = %s
              )
            ORDER BY mi.category, mi.name
        """, (str(location_id),), fetch=True) or []

        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True) or []

        return render_template('inventory/location_inventory_assign.html',
                             location=location,
                             assigned_items=assigned_items,
                             available_items=available_items,
                             locations=locations)
    except Exception as e:
        flash(f'Error assigning inventory items: {str(e)}', 'error')
        return redirect(url_for('inventory.location_inventory'))

@inventory_bp.route('/location-inventory/<uuid:location_id>/<uuid:item_id>/unassign', methods=['POST'])
@login_required
@owner_required
def unassign_location_inventory(location_id, item_id):
    """Remove an ingredient assignment from a location."""
    try:
        execute_query("""
            DELETE FROM location_inventory
            WHERE location_id = %s AND master_inventory_id = %s
        """, (str(location_id), str(item_id)))

        flash('Ingredient unassigned from location inventory.', 'success')
    except Exception as e:
        flash(f'Error removing assignment: {str(e)}', 'error')

    return redirect(url_for('inventory.assign_location_inventory', location_id=location_id))

@inventory_bp.route('/location-inventory/<uuid:location_id>/<uuid:item_id>/adjust', methods=['GET', 'POST'])
@login_required
@owner_required
def adjust_inventory(location_id, item_id):
    """Adjust inventory stock levels"""
    store = scoped_location_id()
    if store and str(location_id) != store:
        flash('You can only manage your own store.', 'error')
        return redirect(url_for('inventory.location_inventory'))
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
            try:
                quantity = Decimal(str(request.form['quantity']))
            except (InvalidOperation, KeyError):
                flash('Invalid quantity value', 'error')
                return redirect(request.url)

            if quantity < 0:
                flash('Quantity must be positive', 'error')
                return redirect(request.url)

            reason = request.form['reason']
            notes = request.form.get('notes', '')

            current_stock = Decimal(str(inventory['current_stock']))
            staff_id = get_current_staff_id()

            if not staff_id:
                flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
                return redirect(request.url)

            # Calculate new stock
            if adjustment_type == 'add':
                new_stock = current_stock + quantity
            else:  # subtract
                new_stock = current_stock - quantity

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
            quantity_delta = quantity if adjustment_type == 'add' else -quantity
            execute_query("""
                INSERT INTO inventory_transactions (
                    location_id, master_inventory_id, transaction_type,
                    quantity, previous_stock, new_stock, recorded_by, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(location_id), str(item_id), 'adjustment',
                quantity_delta,
                current_stock, new_stock,
                staff_id, f"{reason}: {notes}"
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

        # Store managers only ever see their own store's records.
        store = scoped_location_id()
        if store:
            location_id = store

        # Get locations for filter
        locations = execute_query("SELECT id, name FROM locations ORDER BY name", fetch=True)

        # Get daily usage records
        query = """
            SELECT du.*, mi.name as item_name, mi.unit, l.name as location_name,
                   s.first_name, s.last_name,
                   e.first_name AS editor_first_name, e.last_name AS editor_last_name
            FROM daily_inventory_usage du
            JOIN master_inventory mi ON du.master_inventory_id = mi.id
            JOIN locations l ON du.location_id = l.id
            LEFT JOIN staff s ON du.recorded_by = s.id
            LEFT JOIN staff e ON du.edited_by = e.id
            WHERE du.date = %s
        """

        params = [selected_date]
        if location_id:
            query += " AND du.location_id = %s"
            params.append(location_id)

        query += " ORDER BY l.name, mi.name"

        usage_records = execute_query(query, params, fetch=True) or []
        # Mark which rows the current user may edit (owner: any; worker: own store, today).
        for r in usage_records:
            r['editable'] = _worker_can_edit(r['location_id'], r.get('date'))

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
        # Store managers can only record for their own store.
        store = scoped_location_id()
        if store:
            location_id = store
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
            consumed_data = {}  # store-manager simple mode: item_id -> qty used today
            staff_id = get_current_staff_id()

            if not staff_id:
                flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
                return redirect(request.url)

            def _f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            for key, value in request.form.items():
                if key.startswith('opening_'):
                    fv = _f(value)
                    if fv is not None:
                        usage_data[key.replace('opening_', '')] = {'opening': fv}
                elif key.startswith('closing_'):
                    item_id = key.replace('closing_', '')
                    fv = _f(value)
                    if item_id in usage_data and fv is not None:
                        usage_data[item_id]['closing'] = fv
                elif key.startswith('wastage_'):
                    fv = _f(value)
                    if fv is not None:
                        wastage_data[key.replace('wastage_', '')] = fv
                elif key.startswith('used_'):
                    fv = _f(value)
                    if fv is not None:
                        item_id = key.replace('used_', '')
                        # Convert grams->kg and ml->L so stock stays in its base unit.
                        unit = (request.form.get('unit_' + item_id) or '').strip().lower()
                        if unit in ('g', 'gram', 'grams', 'ml', 'milliliter', 'millilitre', 'millilitres'):
                            fv = fv / 1000.0
                        consumed_data[item_id] = fv

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
                used, wastage, staff_id
                ))

                # The end-of-day count is the new stock level, so the manager's
                # usage/wastage reduces the stock the owner sees.
                execute_query("""
                    UPDATE location_inventory
                    SET current_stock = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE location_id = %s AND master_inventory_id = %s
                """, (closing, location_id, item_id))

            # Simple consumption mode (store managers): "I used X of this item".
            # We subtract it from the current stock and add to today's usage.
            for item_id, qty in consumed_data.items():
                if not qty or qty <= 0:
                    continue
                cur = execute_query_one(
                    "SELECT current_stock FROM location_inventory WHERE location_id=%s AND master_inventory_id=%s",
                    (location_id, item_id))
                if not cur:
                    continue
                opening = float(cur['current_stock'])
                closing = max(opening - qty, 0)
                execute_query("""
                    INSERT INTO daily_inventory_usage (
                        location_id, master_inventory_id, date, opening_stock,
                        closing_stock, used_quantity, wastage_quantity, recorded_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, 0, %s)
                    ON CONFLICT (location_id, master_inventory_id, date)
                    DO UPDATE SET
                        used_quantity = daily_inventory_usage.used_quantity + EXCLUDED.used_quantity,
                        closing_stock = EXCLUDED.closing_stock,
                        recorded_by = EXCLUDED.recorded_by,
                        status = 'recorded'
                """, (location_id, item_id, record_date, opening, closing, qty, staff_id))
                execute_query("""
                    UPDATE location_inventory
                    SET current_stock = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE location_id = %s AND master_inventory_id = %s
                """, (closing, location_id, item_id))

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

@inventory_bp.route('/daily-usage/<uuid:usage_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_daily_usage(usage_id):
    """Correct a single usage record. Owners may edit any; a worker may only
    edit their own store's same-day entries. Unlike the record-usage form
    (which adds to today's total in simple mode), this SETS the values, so a
    typo can actually be fixed. Edits stamp edited_at/edited_by for the admin
    and recompute location_inventory.current_stock from the corrected closing
    stock, same as the original recording does."""
    record = execute_query_one("""
        SELECT du.*, mi.name AS item_name, mi.unit, l.name AS location_name
        FROM daily_inventory_usage du
        JOIN master_inventory mi ON du.master_inventory_id = mi.id
        JOIN locations l ON du.location_id = l.id
        WHERE du.id = %s
    """, (str(usage_id),))
    if not record:
        flash('Usage record not found.', 'error')
        return redirect(url_for('inventory.daily_usage'))

    if not _worker_can_edit(record['location_id'], record['date']):
        flash('You can only edit your store\'s entries from today. Ask the owner to change older records.', 'error')
        return redirect(url_for('inventory.daily_usage'))

    owner_view = not is_store_manager()

    if request.method == 'POST':
        staff_id = get_current_staff_id()
        if not staff_id:
            flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
            return redirect(request.url)

        def _f(v, default=None):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        opening = _f(request.form.get('opening_stock'), float(record['opening_stock'])) if owner_view else float(record['opening_stock'])
        wastage = _f(request.form.get('wastage_quantity'), float(record['wastage_quantity'] or 0)) if owner_view else float(record['wastage_quantity'] or 0)
        used = _f(request.form.get('used_quantity'))

        if used is None or used < 0:
            flash('Enter a valid used quantity.', 'error')
            return render_template('inventory/edit_daily_usage.html', record=record, owner_view=owner_view)

        closing = max(opening - used - wastage, 0)

        execute_query("""
            UPDATE daily_inventory_usage
            SET opening_stock = %s, closing_stock = %s, used_quantity = %s,
                wastage_quantity = %s, edited_at = CURRENT_TIMESTAMP, edited_by = %s
            WHERE id = %s
        """, (opening, closing, used, wastage, staff_id, str(usage_id)))

        # Keep the owner's stock view consistent with the corrected closing stock.
        execute_query("""
            UPDATE location_inventory
            SET current_stock = %s, last_updated = CURRENT_TIMESTAMP
            WHERE location_id = %s AND master_inventory_id = %s
        """, (closing, record['location_id'], record['master_inventory_id']))

        flash('Usage record updated.', 'success')
        return redirect(url_for('inventory.daily_usage', date=record['date'].isoformat(), location_id=str(record['location_id'])))

    return render_template('inventory/edit_daily_usage.html', record=record, owner_view=owner_view)

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

        # Store managers only ever see their own store's records.
        store = scoped_location_id()
        if store:
            location_id = store

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
        # Store managers can only record for their own store.
        store = scoped_location_id()
        if store:
            location_id = store
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
            staff_id = get_current_staff_id()

            if not staff_id:
                flash('Your account is not linked to a staff record. Please contact an administrator.', 'error')
                return redirect(request.url)

            def _i(v):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None
            for key, value in request.form.items():
                if key.startswith('prepared_'):
                    iv = _i(value)
                    if iv is not None:
                        leftover_data[key.replace('prepared_', '')] = {'prepared': iv}
                elif key.startswith('sold_'):
                    menu_item_id = key.replace('sold_', '')
                    iv = _i(value)
                    if menu_item_id in leftover_data and iv is not None:
                        leftover_data[menu_item_id]['sold'] = iv
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
                    leftover, disposal, staff_id
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
            WHERE li.current_stock <= li.minimum_stock_level
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
