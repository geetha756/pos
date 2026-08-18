from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one
from .auth import login_required
from decimal import Decimal, InvalidOperation
import psycopg2

master_menu_bp = Blueprint('master_menu', __name__)

@master_menu_bp.route('/')
@login_required
def index():
    """List all master menu items with search and sort functionality"""
    try:
        # Get search and sort parameters
        search_query = request.args.get('search', '').strip()
        sort_by = request.args.get('sort', 'category_name')  # Default sort
        sort_order = request.args.get('order', 'asc')

        # Base query
        query = """
            SELECT id, name, description, category, is_active, image_data, created_at
            FROM master_menu
        """
        params = []

        # Add search filter if search query exists
        if search_query:
            query += """
                WHERE name ILIKE %s OR description ILIKE %s OR category ILIKE %s
            """
            search_param = f'%{search_query}%'
            params.extend([search_param, search_param, search_param])

        # Add sorting
        sort_column = {
            'name': 'name',
            'category_name': 'category, name',
            'status': 'is_active',
            'created': 'created_at'
        }.get(sort_by, 'category, name')

        if sort_order == 'desc':
            query += f" ORDER BY {sort_column} DESC"
        else:
            query += f" ORDER BY {sort_column} ASC"

        menu_items = execute_query(query, params, fetch=True)

        # Get unique categories for filter dropdown
        categories = execute_query("""
            SELECT DISTINCT category FROM master_menu
            WHERE category IS NOT NULL AND category != ''
            ORDER BY category
        """, fetch=True)
        categories = [cat['category'] for cat in categories] if categories else []

        return render_template('master_menu/index.html',
                             menu_items=menu_items or [],
                             search_query=search_query,
                             sort_by=sort_by,
                             sort_order=sort_order,
                             categories=categories)
    except Exception as e:
        flash(f'Error loading menu items: {str(e)}', 'error')
        return render_template('master_menu/index.html',
                             menu_items=[],
                             search_query='',
                             sort_by='category_name',
                             sort_order='asc',
                             categories=[])

@master_menu_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """Add new menu item"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        image_data = request.form.get('image_data')
        is_active = request.form.get('is_active') == 'on'

        if not name:
            flash('Name is required', 'error')
            return render_template('master_menu/add.html')

        try:
            execute_query("""
                INSERT INTO master_menu (name, description, category, image_data, is_active)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, description, category, image_data, is_active))
            flash('Menu item added successfully!', 'success')
            return redirect(url_for('master_menu.index'))
        except psycopg2.IntegrityError as e:
            if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                flash('A menu item with this name already exists. Please choose a different name.', 'error')
            else:
                flash(f'Error adding menu item: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error adding menu item: {str(e)}', 'error')

    return render_template('master_menu/add.html')

@master_menu_bp.route('/edit/<item_id>', methods=['GET', 'POST'])
@login_required
def edit(item_id):
    """Edit menu item"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        image_data = request.form.get('image_data')
        is_active = request.form.get('is_active') == 'on'

        if not name:
            flash('Name is required', 'error')
            item = execute_query_one("SELECT * FROM master_menu WHERE id = %s", (item_id,))
            return render_template('master_menu/edit.html', item=item)

        try:
            execute_query("""
                UPDATE master_menu
                SET name = %s, description = %s, category = %s, image_data = %s, is_active = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, description, category, image_data, is_active, item_id))
            flash('Menu item updated successfully!', 'success')
            return redirect(url_for('master_menu.index'))
        except psycopg2.IntegrityError as e:
            if 'unique constraint' in str(e).lower() or 'duplicate key' in str(e).lower():
                flash('A menu item with this name already exists. Please choose a different name.', 'error')
                item = execute_query_one("SELECT * FROM master_menu WHERE id = %s", (item_id,))
                return render_template('master_menu/edit.html', item=item)
            else:
                flash(f'Error updating menu item: {str(e)}', 'error')
        except Exception as e:
            flash(f'Error updating menu item: {str(e)}', 'error')

    # GET request - show edit form
    try:
        item = execute_query_one("SELECT * FROM master_menu WHERE id = %s", (item_id,))
        if not item:
            flash('Menu item not found', 'error')
            return redirect(url_for('master_menu.index'))
        return render_template('master_menu/edit.html', item=item)
    except Exception as e:
        flash(f'Error loading menu item: {str(e)}', 'error')
        return redirect(url_for('master_menu.index'))

@master_menu_bp.route('/delete/<item_id>', methods=['POST'])
@login_required
def delete(item_id):
    """Delete menu item"""
    try:
        execute_query("DELETE FROM master_menu WHERE id = %s", (item_id,))
        flash('Menu item deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting menu item: {str(e)}', 'error')
    return redirect(url_for('master_menu.index'))

@master_menu_bp.route('/<item_id>/recipe', methods=['GET', 'POST'])
@login_required
def recipe(item_id):
    """The bill-of-materials for one menu item: which raw ingredients (and how
    much of each) one unit of it consumes. This is what lets placing an order
    auto-deduct stock instead of relying on end-of-day manual usage counts —
    see database.recipe_consumption_ops(), called from routes/orders.py.
    An item with no rows here just isn't recipe-tracked yet; orders for it
    don't touch stock, same as before this feature existed."""
    item = execute_query_one("SELECT * FROM master_menu WHERE id = %s", (item_id,))
    if not item:
        flash('Menu item not found', 'error')
        return redirect(url_for('master_menu.index'))

    if request.method == 'POST':
        master_inventory_id = request.form.get('master_inventory_id')
        try:
            qty = Decimal(str(request.form.get('quantity_per_unit', '0')))
        except InvalidOperation:
            qty = Decimal('-1')

        if not master_inventory_id:
            flash('Choose an ingredient.', 'error')
        elif qty <= 0:
            flash('Quantity per unit must be greater than zero.', 'error')
        else:
            execute_query("""
                INSERT INTO recipe_items (master_menu_id, master_inventory_id, quantity_per_unit)
                VALUES (%s, %s, %s)
                ON CONFLICT (master_menu_id, master_inventory_id)
                DO UPDATE SET quantity_per_unit = EXCLUDED.quantity_per_unit, updated_at = CURRENT_TIMESTAMP
            """, (item_id, master_inventory_id, qty))
            flash('Recipe updated.', 'success')
        return redirect(url_for('master_menu.recipe', item_id=item_id))

    ingredients = execute_query("""
        SELECT ri.id, ri.quantity_per_unit, mi.id AS master_inventory_id, mi.name, mi.unit
        FROM recipe_items ri
        JOIN master_inventory mi ON mi.id = ri.master_inventory_id
        WHERE ri.master_menu_id = %s
        ORDER BY mi.name
    """, (item_id,), fetch=True) or []

    available_items = execute_query("""
        SELECT id, name, unit FROM master_inventory
        WHERE is_active = TRUE
          AND id NOT IN (SELECT master_inventory_id FROM recipe_items WHERE master_menu_id = %s)
        ORDER BY name
    """, (item_id,), fetch=True) or []

    return render_template('master_menu/recipe.html',
                            item=item, ingredients=ingredients, available_items=available_items)


@master_menu_bp.route('/<item_id>/recipe/<ingredient_id>/remove', methods=['POST'])
@login_required
def remove_recipe_item(item_id, ingredient_id):
    """Drop one ingredient from a menu item's recipe."""
    execute_query("DELETE FROM recipe_items WHERE id = %s AND master_menu_id = %s", (ingredient_id, item_id))
    flash('Ingredient removed from recipe.', 'success')
    return redirect(url_for('master_menu.recipe', item_id=item_id))


@master_menu_bp.route('/check-name', methods=['POST'])
@login_required
def check_name():
    """Check if a menu item name already exists"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()

        if not name:
            return jsonify({'exists': False})

        # Check if menu item name exists
        result = execute_query_one("SELECT id FROM master_menu WHERE name = %s", (name,))
        return jsonify({'exists': result is not None})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@master_menu_bp.route('/toggle/<item_id>', methods=['POST'])
@login_required
def toggle_status(item_id):
    """Toggle menu item active status"""
    try:
        execute_query("""
            UPDATE master_menu
            SET is_active = NOT is_active, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (item_id,))
        flash('Menu item status updated!', 'success')
    except Exception as e:
        flash(f'Error updating status: {str(e)}', 'error')
    return redirect(url_for('master_menu.index'))
