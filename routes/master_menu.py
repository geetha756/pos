from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database import execute_query, execute_query_one
from .auth import login_required
import psycopg2

master_menu_bp = Blueprint('master_menu', __name__)

@master_menu_bp.route('/')
@login_required
def index():
    """List all master menu items"""
    try:
        menu_items = execute_query("""
            SELECT id, name, description, price, category, is_active, created_at
            FROM master_menu
            ORDER BY category, name
        """, fetch=True)
        return render_template('master_menu/index.html', menu_items=menu_items or [])
    except Exception as e:
        flash(f'Error loading menu items: {str(e)}', 'error')
        return render_template('master_menu/index.html', menu_items=[])

@master_menu_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """Add new menu item"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = request.form.get('price')
        category = request.form.get('category')
        is_active = request.form.get('is_active') == 'on'

        if not name or not price:
            flash('Name and price are required', 'error')
            return render_template('master_menu/add.html')

        try:
            execute_query("""
                INSERT INTO master_menu (name, description, price, category, is_active)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, description, float(price), category, is_active))
            flash('Menu item added successfully!', 'success')
            return redirect(url_for('master_menu.index'))
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
        price = request.form.get('price')
        category = request.form.get('category')
        is_active = request.form.get('is_active') == 'on'

        if not name or not price:
            flash('Name and price are required', 'error')
            item = execute_query_one("SELECT * FROM master_menu WHERE id = %s", (item_id,))
            return render_template('master_menu/edit.html', item=item)

        try:
            execute_query("""
                UPDATE master_menu
                SET name = %s, description = %s, price = %s, category = %s, is_active = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, description, float(price), category, is_active, item_id))
            flash('Menu item updated successfully!', 'success')
            return redirect(url_for('master_menu.index'))
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
