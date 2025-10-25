from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import execute_query, execute_query_one
from .auth import login_required

locations_bp = Blueprint('locations', __name__)

@locations_bp.route('/')
@login_required
def index():
    """List all locations"""
    try:
        locations = execute_query("""
            SELECT id, name, address, city, state, zip_code, phone, email, created_at
            FROM locations
            ORDER BY name
        """, fetch=True)
        return render_template('locations/index.html', locations=locations or [])
    except Exception as e:
        flash(f'Error loading locations: {str(e)}', 'error')
        return render_template('locations/index.html', locations=[])

@locations_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    """Add new location"""
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        phone = request.form.get('phone')
        email = request.form.get('email')

        if not name:
            flash('Location name is required', 'error')
            return render_template('locations/add.html')

        try:
            execute_query("""
                INSERT INTO locations (name, address, city, state, zip_code, phone, email)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (name, address, city, state, zip_code, phone, email))
            flash('Location added successfully!', 'success')
            return redirect(url_for('locations.index'))
        except Exception as e:
            flash(f'Error adding location: {str(e)}', 'error')

    return render_template('locations/add.html')

@locations_bp.route('/edit/<location_id>', methods=['GET', 'POST'])
@login_required
def edit(location_id):
    """Edit location"""
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        zip_code = request.form.get('zip_code')
        phone = request.form.get('phone')
        email = request.form.get('email')

        if not name:
            flash('Location name is required', 'error')
            location = execute_query_one("SELECT * FROM locations WHERE id = %s", (location_id,))
            return render_template('locations/edit.html', location=location)

        try:
            execute_query("""
                UPDATE locations
                SET name = %s, address = %s, city = %s, state = %s, zip_code = %s, phone = %s, email = %s
                WHERE id = %s
            """, (name, address, city, state, zip_code, phone, email, location_id))
            flash('Location updated successfully!', 'success')
            return redirect(url_for('locations.index'))
        except Exception as e:
            flash(f'Error updating location: {str(e)}', 'error')

    # GET request - show edit form
    try:
        location = execute_query_one("SELECT * FROM locations WHERE id = %s", (location_id,))
        if not location:
            flash('Location not found', 'error')
            return redirect(url_for('locations.index'))
        return render_template('locations/edit.html', location=location)
    except Exception as e:
        flash(f'Error loading location: {str(e)}', 'error')
        return redirect(url_for('locations.index'))

@locations_bp.route('/delete/<location_id>', methods=['POST'])
@login_required
def delete(location_id):
    """Delete location"""
    try:
        execute_query("DELETE FROM locations WHERE id = %s", (location_id,))
        flash('Location deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting location: {str(e)}', 'error')
    return redirect(url_for('locations.index'))
