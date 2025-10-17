from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import execute_query, execute_query_one

location_menu_bp = Blueprint('location_menu', __name__)

@location_menu_bp.route('/')
def index():
    """List all locations for menu management"""
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
def manage(location_id):
    """Manage menu for a specific location"""
    try:
        # Get location info
        location = execute_query_one("SELECT * FROM locations WHERE id = %s", (location_id,))
        if not location:
            flash('Location not found', 'error')
            return redirect(url_for('location_menu.index'))

        # Get all master menu items
        master_menu = execute_query("""
            SELECT id, name, description, price, category, is_active
            FROM master_menu
            WHERE is_active = TRUE
            ORDER BY category, name
        """, fetch=True)

        # Get current location menu items
        location_menu = execute_query("""
            SELECT lm.id, mm.name, mm.description, lm.price, mm.category, lm.is_available, lm.location_menu_id
            FROM location_menu lm
            JOIN master_menu mm ON lm.master_menu_id = mm.id
            WHERE lm.location_id = %s
        """, (location_id,), fetch=True)

        # Create a dict of assigned items for easy lookup
        assigned_items = {item['name']: item for item in location_menu or []}

        return render_template('location_menu/manage.html',
                             location=location,
                             master_menu=master_menu or [],
                             assigned_items=assigned_items)

    except Exception as e:
        flash(f'Error loading location menu: {str(e)}', 'error')
        return redirect(url_for('location_menu.index'))

@location_menu_bp.route('/<location_id>/add/<menu_item_id>', methods=['POST'])
def add_item(location_id, menu_item_id):
    """Add menu item to location"""
    price = request.form.get('price')
    is_available = request.form.get('is_available') == 'on'

    try:
        # Check if item already exists
        existing = execute_query_one("""
            SELECT id FROM location_menu
            WHERE location_id = %s AND master_menu_id = %s
        """, (location_id, menu_item_id))

        if existing:
            flash('Menu item already assigned to this location', 'warning')
        else:
            # Get default price from master menu if not provided
            if not price:
                master_item = execute_query_one("SELECT price FROM master_menu WHERE id = %s", (menu_item_id,))
                price = master_item['price'] if master_item else 0

            execute_query("""
                INSERT INTO location_menu (location_id, master_menu_id, price, is_available)
                VALUES (%s, %s, %s, %s)
            """, (location_id, menu_item_id, float(price), is_available))
            flash('Menu item added to location!', 'success')

    except Exception as e:
        flash(f'Error adding menu item: {str(e)}', 'error')

    return redirect(url_for('location_menu.manage', location_id=location_id))

@location_menu_bp.route('/<location_id>/update/<location_menu_id>', methods=['POST'])
def update_item(location_id, location_menu_id):
    """Update location menu item"""
    price = request.form.get('price')
    is_available = request.form.get('is_available') == 'on'

    try:
        execute_query("""
            UPDATE location_menu
            SET price = %s, is_available = %s
            WHERE id = %s AND location_id = %s
        """, (float(price), is_available, location_menu_id, location_id))
        flash('Menu item updated!', 'success')
    except Exception as e:
        flash(f'Error updating menu item: {str(e)}', 'error')

    return redirect(url_for('location_menu.manage', location_id=location_id))

@location_menu_bp.route('/<location_id>/remove/<location_menu_id>', methods=['POST'])
def remove_item(location_id, location_menu_id):
    """Remove menu item from location"""
    try:
        execute_query("""
            DELETE FROM location_menu
            WHERE id = %s AND location_id = %s
        """, (location_menu_id, location_id))
        flash('Menu item removed from location!', 'success')
    except Exception as e:
        flash(f'Error removing menu item: {str(e)}', 'error')

    return redirect(url_for('location_menu.manage', location_id=location_id))
