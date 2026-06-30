from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from database import execute_query, execute_query_one
from .auth import login_required
from security import scoped_location_id
import os, re

location_menu_bp = Blueprint('location_menu', __name__)


def _deny_other_store(location_id):
    """For a store manager, return a redirect if location_id isn't their store;
    otherwise None. Owners are never restricted."""
    store = scoped_location_id()
    if store and str(location_id) != store:
        flash('You can only manage your own store.', 'error')
        return redirect(url_for('location_menu.manage', location_id=store))
    return None

@location_menu_bp.route('/')
@login_required
def index():
    """List all locations for menu management"""
    # A store-scoped manager manages only their own store's menu.
    store = scoped_location_id()
    if store:
        return redirect(url_for('location_menu.manage', location_id=store))
    try:
        locations = execute_query("""
            SELECT id, name, city, state
            FROM locations
            ORDER BY name
        """, fetch=True)
        return render_template('location_menu/index.html', locations=locations or [])
    except Exception as e:
        flash(f'Error loading locations: {str(e)}', 'error')
        return render_template('location_menu/index.html', locations=[])

@location_menu_bp.route('/<location_id>')
@login_required
def manage(location_id):
    """Manage menu for a specific location"""
    # Store managers may only manage their own store's menu.
    store = scoped_location_id()
    if store and str(location_id) != store:
        flash('You can only manage your own store.', 'error')
        return redirect(url_for('location_menu.manage', location_id=store))
    try:
        # Get location info
        location = execute_query_one("SELECT * FROM locations WHERE id = %s", (location_id,))
        if not location:
            flash('Location not found', 'error')
            return redirect(url_for('location_menu.index'))

        # Get all master menu items
        master_menu = execute_query("""
            SELECT id, name, description, category, is_active, image_data
            FROM master_menu
            WHERE is_active = TRUE
            ORDER BY category, name
        """, fetch=True)

        # Get current location menu items (only active ones)
        location_menu = execute_query("""
            SELECT lm.id, mm.name, mm.description, lm.price, mm.category, lm.is_available,
                   lm.id as location_menu_id, COALESCE(lm.section, 'all') AS section,
                   lm.master_menu_id, mm.image_data
            FROM location_menu lm
            JOIN master_menu mm ON lm.master_menu_id = mm.id
            WHERE lm.location_id = %s AND lm.is_available = TRUE
        """, (location_id,), fetch=True)

        # Create a dict of assigned items for easy lookup
        assigned_items = {item['name']: item for item in location_menu or []}

        # Distinct existing categories to suggest while creating new items
        category_rows = execute_query(
            "SELECT DISTINCT category FROM master_menu WHERE category IS NOT NULL AND category <> '' ORDER BY category",
            fetch=True,
        ) or []
        categories = [r['category'] for r in category_rows]

        return render_template('location_menu/manage.html',
                             location=location,
                             master_menu=master_menu or [],
                             assigned_items=assigned_items,
                             categories=categories)

    except Exception as e:
        flash(f'Error loading location menu: {str(e)}', 'error')
        return redirect(url_for('location_menu.index'))

@location_menu_bp.route('/<location_id>/create-item', methods=['POST'])
@login_required
def create_item(location_id):
    """Let a location manager create a brand-new menu item (name + category +
    price) and add it straight to this store's menu. The catalog entry
    (master_menu) is reused if an item with the same name already exists, so
    stores can share items but keep their own price."""
    guard = _deny_other_store(location_id)
    if guard:
        return guard
    name = (request.form.get('name') or '').strip()
    category = (request.form.get('category') or '').strip() or None
    description = (request.form.get('description') or '').strip() or None
    price = request.form.get('price')
    section = (request.form.get('section') or 'all').strip().lower()
    if section not in ('morning', 'evening', 'all'):
        section = 'all'

    if not name:
        flash('Item name is required', 'error')
        return redirect(url_for('location_menu.manage', location_id=location_id))

    try:
        price = float(price) if price else 0.0
    except ValueError:
        flash('Price must be a number', 'error')
        return redirect(url_for('location_menu.manage', location_id=location_id))

    try:
        # Reuse a catalog item with the same name (case-insensitive), else create it.
        master = execute_query_one(
            "SELECT id FROM master_menu WHERE LOWER(name) = LOWER(%s)", (name,)
        )
        if master:
            master_id = master['id']
            # Make sure it's active and category is filled if it was blank.
            execute_query(
                "UPDATE master_menu SET is_active = TRUE, category = COALESCE(category, %s) WHERE id = %s",
                (category, master_id),
            )
        else:
            master = execute_query_one(
                """
                INSERT INTO master_menu (name, description, category, is_active)
                VALUES (%s, %s, %s, TRUE) RETURNING id
                """,
                (name, description, category),
            )
            master_id = master['id']

        # Add (or reactivate) the item on this store's menu.
        existing = execute_query_one(
            "SELECT id FROM location_menu WHERE location_id = %s AND master_menu_id = %s",
            (location_id, master_id),
        )
        if existing:
            execute_query(
                "UPDATE location_menu SET price = %s, is_available = TRUE, section = %s WHERE id = %s",
                (price, section, existing['id']),
            )
        else:
            execute_query(
                "INSERT INTO location_menu (location_id, master_menu_id, price, is_available, section) VALUES (%s, %s, %s, TRUE, %s)",
                (location_id, master_id, price, section),
            )
        flash(f'"{name}" added to this store\'s menu!', 'success')
    except Exception as e:
        flash(f'Error creating menu item: {str(e)}', 'error')

    return redirect(url_for('location_menu.manage', location_id=location_id))


@location_menu_bp.route('/<location_id>/add/<menu_item_id>', methods=['POST'])
@login_required
def add_item(location_id, menu_item_id):
    """Add menu item to location"""
    guard = _deny_other_store(location_id)
    if guard:
        return guard
    price = request.form.get('price')
    is_available = True  # Items are available by default when added

    try:
        # Check if item already exists (active or soft deleted)
        existing = execute_query_one("""
            SELECT id, is_available FROM location_menu
            WHERE location_id = %s AND master_menu_id = %s
        """, (location_id, menu_item_id))

        if existing:
            if existing['is_available']:
                # Item is already active
                flash('Menu item already assigned to this location', 'warning')
            else:
                # Item was soft deleted, reactivate it
                # Use provided price or default to 0 (price will be set at location level)
                if not price:
                    price = 0

                execute_query("""
                    UPDATE location_menu
                    SET price = %s, is_available = %s
                    WHERE id = %s
                """, (float(price), is_available, existing['id']))
                flash('Menu item re-added to location!', 'success')
        else:
            # Item doesn't exist at all, create new record
            # Use provided price or default to 0 (price will be set at location level)
            if not price:
                price = 0

            execute_query("""
                INSERT INTO location_menu (location_id, master_menu_id, price, is_available)
                VALUES (%s, %s, %s, %s)
            """, (location_id, menu_item_id, float(price), is_available))
            flash('Menu item added to location!', 'success')

    except Exception as e:
        flash(f'Error adding menu item: {str(e)}', 'error')

    return redirect(url_for('location_menu.manage', location_id=location_id))

@location_menu_bp.route('/<location_id>/update/<location_menu_id>', methods=['POST'])
@login_required
def update_item(location_id, location_menu_id):
    """Update location menu item"""
    guard = _deny_other_store(location_id)
    if guard:
        return guard
    price = request.form.get('price')
    is_available = True  # Items remain available when updated
    section = (request.form.get('section') or 'all').strip().lower()
    if section not in ('morning', 'evening', 'all'):
        section = 'all'

    try:
        execute_query("""
            UPDATE location_menu
            SET price = %s, is_available = %s, section = %s
            WHERE id = %s AND location_id = %s
        """, (float(price), is_available, section, location_menu_id, location_id))
        flash('Menu item updated!', 'success')
    except Exception as e:
        flash(f'Error updating menu item: {str(e)}', 'error')

    return redirect(url_for('location_menu.manage', location_id=location_id))

@location_menu_bp.route('/<location_id>/upload-image/<master_menu_id>', methods=['POST'])
@login_required
def upload_item_image(location_id, master_menu_id):
    """Upload (or replace) a dish photo for a menu item. Admin OR the store
    manager can do this from the Location Menu. The photo is resized + saved as
    a small JPEG and shown on the item everywhere it appears."""
    guard = _deny_other_store(location_id)
    if guard:
        return guard
    file = request.files.get('image')
    if not file or not file.filename:
        flash('Please choose an image to upload.', 'error')
        return redirect(url_for('location_menu.manage', location_id=location_id))
    try:
        from PIL import Image
        import time
        img = Image.open(file.stream).convert('RGB')
        w, h = img.size
        if w > 700:
            img = img.resize((700, int(h * 700 / w)), Image.LANCZOS)
        folder = os.path.join(current_app.static_folder, 'menu-images')
        os.makedirs(folder, exist_ok=True)
        fname = 'item-%s.jpg' % re.sub(r'[^a-zA-Z0-9-]', '', str(master_menu_id))
        img.save(os.path.join(folder, fname), 'JPEG', quality=85, optimize=True)
        # ?v=timestamp busts the service-worker/browser cache so the new photo
        # shows right away instead of the previously cached one.
        url = '/static/menu-images/%s?v=%d' % (fname, int(time.time()))
        execute_query(
            "UPDATE master_menu SET image_data = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (url, str(master_menu_id)))
        flash('Photo updated!', 'success')
    except Exception as e:
        flash('Could not process that image: %s' % e, 'error')
    return redirect(url_for('location_menu.manage', location_id=location_id))

@location_menu_bp.route('/<location_id>/remove/<location_menu_id>', methods=['POST'])
@login_required
def remove_item(location_id, location_menu_id):
    """Soft remove menu item from location (mark as unavailable)"""
    guard = _deny_other_store(location_id)
    if guard:
        return guard
    try:
        execute_query("""
            UPDATE location_menu
            SET is_available = FALSE
            WHERE id = %s AND location_id = %s
        """, (location_menu_id, location_id))
        flash('Menu item removed from location!', 'success')
    except Exception as e:
        flash(f'Error removing menu item: {str(e)}', 'error')

    return redirect(url_for('location_menu.manage', location_id=location_id))

@location_menu_bp.route('/<location_id>/place-order')
@login_required
def place_order(location_id):
    """Place order for a specific location"""
    try:
        # Get location info
        location = execute_query_one("SELECT * FROM locations WHERE id = %s", (location_id,))
        if not location:
            flash('Location not found', 'error')
            return redirect(url_for('location_menu.index'))

        # Get available menu items for this location
        menu_items = execute_query("""
            SELECT lm.id as location_menu_id, mm.id as master_menu_id, mm.name, mm.description,
                   lm.price, mm.category, lm.is_available
            FROM location_menu lm
            JOIN master_menu mm ON lm.master_menu_id = mm.id
            WHERE lm.location_id = %s AND lm.is_available = TRUE AND mm.is_active = TRUE
            ORDER BY mm.category, mm.name
        """, (location_id,), fetch=True)

        # Group items by category for better display
        items_by_category = {}
        for item in menu_items or []:
            category = item['category'] or 'Other'
            if category not in items_by_category:
                items_by_category[category] = []
            items_by_category[category].append(item)

        return render_template('location_menu/place_order.html',
                             location=location,
                             items_by_category=items_by_category)

    except Exception as e:
        flash(f'Error loading order page: {str(e)}', 'error')
        return redirect(url_for('location_menu.index'))