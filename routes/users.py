from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import execute_query, execute_query_one, create_api_key, revoke_api_key, record_audit_log
from .auth import login_required
from security import permission_required, get_or_create_current_user

users_bp = Blueprint('users', __name__)


@users_bp.route('/')
@login_required
@permission_required('users.view')
def index():
    users = execute_query(
        """
        SELECT u.*, COALESCE(p.title, '') AS position_title, COALESCE(d.name, '') AS department_name
        FROM users u
        LEFT JOIN positions p ON p.id=u.position_id
        LEFT JOIN departments d ON d.id=u.department_id
        ORDER BY u.created_at DESC
        """,
        fetch=True,
    ) or []
    return render_template('users/index.html', users=users)


@users_bp.route('/add', methods=['GET', 'POST'])
@login_required
@permission_required('users.create')
def add():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        full_name = request.form.get('full_name')
        picture_url = request.form.get('picture_url')
        position_id = request.form.get('position_id') or None
        department_id = request.form.get('department_id') or None
        location_id = request.form.get('location_id') or None
        if not email:
            flash('Email is required', 'error')
            return redirect(url_for('users.add'))
        execute_query(
            """
            INSERT INTO users (email, full_name, picture_url, position_id, department_id, location_id)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (email) DO UPDATE SET location_id = EXCLUDED.location_id
            """,
            (email, full_name, picture_url, position_id, department_id, location_id),
        )
        u = execute_query_one("SELECT * FROM users WHERE email=%s", (email,))
        record_audit_log(actor_user_id=None, actor_api_key_id=None, action='user.create', target_type='user', target_id=u['id'] if u else None, route=request.path, method=request.method, status_code=200, ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'), success=True, metadata={'email': email})
        flash('User created', 'success')
        return redirect(url_for('users.index'))

    positions = execute_query("SELECT id, title FROM positions WHERE is_active=TRUE ORDER BY title", fetch=True) or []
    departments = execute_query("SELECT id, name FROM departments WHERE is_active=TRUE ORDER BY name", fetch=True) or []
    locations = execute_query("SELECT id, name, city FROM locations ORDER BY name", fetch=True) or []
    return render_template('users/add.html', positions=positions, departments=departments, locations=locations)


@users_bp.route('/<user_id>/edit', methods=['GET', 'POST'])
@login_required
@permission_required('users.edit')
def edit(user_id):
    user = execute_query_one("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    if request.method == 'POST':
        full_name = request.form.get('full_name')
        picture_url = request.form.get('picture_url')
        is_active = True if request.form.get('is_active') == 'on' else False
        position_id = request.form.get('position_id') or None
        department_id = request.form.get('department_id') or None
        location_id = request.form.get('location_id') or None
        role = request.form.get('role')
        if role not in ('worker', 'manager', 'admin'):
            role = user.get('role') or 'worker'
        execute_query(
            """
            UPDATE users SET full_name=%s, picture_url=%s, is_active=%s, position_id=%s, department_id=%s, location_id=%s, role=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (full_name, picture_url, is_active, position_id, department_id, location_id, role, user_id),
        )
        record_audit_log(actor_user_id=None, actor_api_key_id=None, action='user.update', target_type='user', target_id=user_id, route=request.path, method=request.method, status_code=200, ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'), success=True, metadata={'fields': ['full_name','picture_url','is_active','position_id','department_id']})
        flash('User updated', 'success')
        return redirect(url_for('users.view', user_id=user_id))

    positions = execute_query("SELECT id, title FROM positions WHERE is_active=TRUE ORDER BY title", fetch=True) or []
    departments = execute_query("SELECT id, name FROM departments WHERE is_active=TRUE ORDER BY name", fetch=True) or []
    locations = execute_query("SELECT id, name, city FROM locations ORDER BY name", fetch=True) or []
    return render_template('users/edit.html', user=user, positions=positions, departments=departments, locations=locations)


@users_bp.route('/<user_id>/deactivate', methods=['POST'])
@login_required
@permission_required('users.delete')
def deactivate(user_id):
    """Soft-delete a user: flips is_active off instead of removing the row,
    so order/audit history that references them stays intact. Enforced at the
    auth layer (get_or_create_current_user) so it actually revokes access,
    not just hides them from this list."""
    target = execute_query_one("SELECT id, email, is_active FROM users WHERE id=%s", (user_id,))
    if not target:
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    current_user = get_or_create_current_user()
    if current_user and str(current_user['id']) == str(user_id):
        flash("You can't deactivate your own account.", 'error')
        return redirect(url_for('users.index'))

    execute_query("UPDATE users SET is_active=FALSE, updated_at=CURRENT_TIMESTAMP WHERE id=%s", (user_id,))
    record_audit_log(actor_user_id=current_user['id'] if current_user else None, actor_api_key_id=None,
                      action='user.deactivate', target_type='user', target_id=user_id, route=request.path,
                      method=request.method, status_code=200, ip_address=request.remote_addr,
                      user_agent=request.headers.get('User-Agent'), success=True, metadata={'email': target['email']})
    flash(f"User {target['email']} has been deactivated.", 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/<user_id>/reactivate', methods=['POST'])
@login_required
@permission_required('users.delete')
def reactivate(user_id):
    """Undo a deactivation — restores login access for the user."""
    target = execute_query_one("SELECT id, email FROM users WHERE id=%s", (user_id,))
    if not target:
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    current_user = get_or_create_current_user()
    execute_query("UPDATE users SET is_active=TRUE, updated_at=CURRENT_TIMESTAMP WHERE id=%s", (user_id,))
    record_audit_log(actor_user_id=current_user['id'] if current_user else None, actor_api_key_id=None,
                      action='user.reactivate', target_type='user', target_id=user_id, route=request.path,
                      method=request.method, status_code=200, ip_address=request.remote_addr,
                      user_agent=request.headers.get('User-Agent'), success=True, metadata={'email': target['email']})
    flash(f"User {target['email']} has been reactivated.", 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/<user_id>')
@login_required
@permission_required('users.view')
def view(user_id):
    user = execute_query_one(
        """
        SELECT u.*, p.title AS position_title, d.name AS department_name
        FROM users u
        LEFT JOIN positions p ON p.id=u.position_id
        LEFT JOIN departments d ON d.id=u.department_id
        WHERE u.id=%s
        """,
        (user_id,),
    )
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    # Effective permissions
    perms = execute_query(
        """
        SELECT p.code FROM permissions p
        """,
        fetch=True,
    ) or []
    return render_template('users/view.html', user=user, all_permissions=[r['code'] for r in perms])


@users_bp.route('/<user_id>/permissions', methods=['GET', 'POST'])
@login_required
@permission_required('users.manage_permissions')
def manage_permissions(user_id):
    user = execute_query_one("SELECT id, email FROM users WHERE id=%s", (user_id,))
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    if request.method == 'POST':
        # Incoming form: permission_id -> effect ('allow'|'deny'|'')
        rows = execute_query("SELECT id, code FROM permissions ORDER BY module, action", fetch=True) or []
        for r in rows:
            field = f"perm_{r['id']}"
            val = request.form.get(field)
            # Remove existing
            execute_query("DELETE FROM user_permissions WHERE user_id=%s AND permission_id=%s", (user_id, r['id']))
            if val in ('allow', 'deny'):
                execute_query(
                    "INSERT INTO user_permissions (user_id, permission_id, effect) VALUES (%s, %s, %s)",
                    (user_id, r['id'], val),
                )
        record_audit_log(actor_user_id=None, actor_api_key_id=None, action='user.manage_permissions', target_type='user', target_id=user_id, route=request.path, method=request.method, status_code=200, ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'), success=True, metadata={})
        flash('Permissions updated', 'success')
        return redirect(url_for('users.view', user_id=user_id))

    permissions = execute_query("SELECT id, code, module, action FROM permissions ORDER BY module, action", fetch=True) or []
    grants = execute_query("SELECT permission_id, effect FROM user_permissions WHERE user_id=%s", (user_id,), fetch=True) or []
    grant_map = {g['permission_id']: g['effect'] for g in grants}
    return render_template('users/permissions.html', user=user, permissions=permissions, grant_map=grant_map)


@users_bp.route('/<user_id>/api-keys', methods=['GET', 'POST'])
@login_required
@permission_required('users.manage_api_keys')
def api_keys(user_id):
    user = execute_query_one("SELECT id, email FROM users WHERE id=%s", (user_id,))
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    created_token = None
    if request.method == 'POST':
        name = request.form.get('name') or 'API Key'
        scopes = request.form.getlist('scopes')
        token, _row = create_api_key(user_id, name, scopes)
        created_token = token  # show once
        record_audit_log(actor_user_id=None, actor_api_key_id=None, action='user.api_key.create', target_type='user', target_id=user_id, route=request.path, method=request.method, status_code=200, ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'), success=True, metadata={'name': name})
        flash('API key created. Copy and store it safely; it will not be shown again.', 'success')

    keys = execute_query(
        """
        SELECT id, name, token_prefix, scopes, created_at, last_used_at, revoked_at
        FROM api_keys WHERE user_id=%s ORDER BY created_at DESC
        """,
        (user_id,),
        fetch=True,
    ) or []
    all_perms = execute_query("SELECT code FROM permissions ORDER BY module, action", fetch=True) or []
    return render_template('users/api_keys.html', user=user, keys=keys, created_token=created_token, all_permissions=[p['code'] for p in all_perms])


@users_bp.route('/api-keys/<key_id>/revoke', methods=['POST'])
@login_required
@permission_required('users.manage_api_keys')
def revoke_key(key_id):
    key = execute_query_one("SELECT id, user_id FROM api_keys WHERE id=%s", (key_id,))
    if not key:
        flash('API key not found', 'error')
        return redirect(url_for('users.index'))
    revoke_api_key(key_id)
    record_audit_log(actor_user_id=None, actor_api_key_id=None, action='user.api_key.revoke', target_type='api_key', target_id=key_id, route=request.path, method=request.method, status_code=200, ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'), success=True, metadata={})
    flash('API key revoked', 'success')
    return redirect(url_for('users.api_keys', user_id=key['user_id']))


@users_bp.route('/position-permissions', methods=['GET', 'POST'])
@login_required
@permission_required('users.manage_permissions')
def position_permissions():
    positions = execute_query("SELECT id, title FROM positions WHERE is_active=TRUE ORDER BY title", fetch=True) or []
    position_id = request.values.get('position_id') or (positions[0]['id'] if positions else None)
    if not position_id:
        flash('No positions available', 'warning')
        return render_template('users/role_permissions.html', mode='position', items=positions, permissions=[], grant_map={}, selected_id=None)

    if request.method == 'POST':
        rows = execute_query("SELECT id FROM permissions", fetch=True) or []
        for r in rows:
            field = f"perm_{r['id']}"
            val = request.form.get(field)
            execute_query("DELETE FROM position_permissions WHERE position_id=%s AND permission_id=%s", (position_id, r['id']))
            if val in ('allow','deny'):
                execute_query("INSERT INTO position_permissions (position_id, permission_id, effect) VALUES (%s,%s,%s)", (position_id, r['id'], val))
        flash('Position permissions updated', 'success')

    permissions = execute_query("SELECT id, code, module, action FROM permissions ORDER BY module, action", fetch=True) or []
    grants = execute_query("SELECT permission_id, effect FROM position_permissions WHERE position_id=%s", (position_id,), fetch=True) or []
    grant_map = {g['permission_id']: g['effect'] for g in grants}
    return render_template('users/role_permissions.html', mode='position', items=positions, permissions=permissions, grant_map=grant_map, selected_id=position_id)


@users_bp.route('/department-permissions', methods=['GET', 'POST'])
@login_required
@permission_required('users.manage_permissions')
def department_permissions():
    departments = execute_query("SELECT id, name FROM departments WHERE is_active=TRUE ORDER BY name", fetch=True) or []
    department_id = request.values.get('department_id') or (departments[0]['id'] if departments else None)
    if not department_id:
        flash('No departments available', 'warning')
        return render_template('users/role_permissions.html', mode='department', items=departments, permissions=[], grant_map={}, selected_id=None)

    if request.method == 'POST':
        rows = execute_query("SELECT id FROM permissions", fetch=True) or []
        for r in rows:
            field = f"perm_{r['id']}"
            val = request.form.get(field)
            execute_query("DELETE FROM department_permissions WHERE department_id=%s AND permission_id=%s", (department_id, r['id']))
            if val in ('allow','deny'):
                execute_query("INSERT INTO department_permissions (department_id, permission_id, effect) VALUES (%s,%s,%s)", (department_id, r['id'], val))
        flash('Department permissions updated', 'success')

    permissions = execute_query("SELECT id, code, module, action FROM permissions ORDER BY module, action", fetch=True) or []
    grants = execute_query("SELECT permission_id, effect FROM department_permissions WHERE department_id=%s", (department_id,), fetch=True) or []
    grant_map = {g['permission_id']: g['effect'] for g in grants}
    return render_template('users/role_permissions.html', mode='department', items=departments, permissions=permissions, grant_map=grant_map, selected_id=department_id)


@users_bp.route('/audit-logs')
@login_required
@permission_required('users.view_audit')
def audit_logs():
    email = request.args.get('email')
    limit = int(request.args.get('limit', '100'))
    params = []
    where = []
    if email:
        where.append("actor_user_id = (SELECT id FROM users WHERE email=%s)")
        params.append(email)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = execute_query(
        f"""
        SELECT al.*, u.email AS actor_email
        FROM audit_logs al
        LEFT JOIN users u ON u.id = al.actor_user_id
        {where_sql}
        ORDER BY al.created_at DESC
        LIMIT %s
        """,
        tuple(params + [limit]),
        fetch=True,
    ) or []
    return render_template('users/audit_logs.html', logs=rows, email=email, limit=limit)


