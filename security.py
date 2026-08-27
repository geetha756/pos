import os
from functools import wraps
from typing import Set, Dict, Any, Optional, List

from flask import session, redirect, url_for, flash, request, g

from database import (
    execute_query,
    execute_query_one,
    upsert_user_from_session,
    record_audit_log,
    init_user_admin_schema,
    seed_permissions_if_needed,
)


def init_security_schema_and_seed():
    init_user_admin_schema()
    seed_permissions_if_needed()


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
# Three simple access levels. Each user has exactly one role (column on `users`).
# Roles map to permission codes from the seeded catalog (e.g. 'inventory.view').
#   - admin   : everything, including user administration
#   - manager : everything except the user-administration module
#   - worker  : minimal self-service (dashboard + clock-in/out + leave request)
ROLE_WORKER = 'worker'
ROLE_MANAGER = 'manager'
ROLE_ADMIN = 'admin'
VALID_ROLES = (ROLE_WORKER, ROLE_MANAGER, ROLE_ADMIN)

# Permission codes granted to a "worker" — which in this business is the
# STORE MANAGER who runs a location: they place orders and own the staff
# journey (staff records, attendance/timesheets, leave) plus inventory and the
# store's own menu. They do NOT get owner-only config: master menu, locations,
# departments/positions setup, or user administration.
WORKER_PERMISSION_CODES: Set[str] = {
    'dashboard.view',
    # Orders — place & manage the store's orders
    'orders.view', 'orders.create', 'orders.edit', 'orders.delete', 'orders.approve', 'orders.export',
    # Inventory — the worker records consumption (daily usage / leftover) and sees
    # their location's item list, suppliers and purchase lists. Master inventory
    # and stock-quantity management are gated to owners at the route level.
    'inventory.view', 'inventory.create', 'inventory.edit', 'inventory.export',
    # Location menu — what the store sells and at what price
    'location_menu.view', 'location_menu.manage',
    # Chat assistant — access is really gated by BitBerry's own per-user
    # agent assignment (a worker with no assigned agent just sees "No agents
    # are currently assigned to you"), so there's no reason to also block it
    # at the POS permission layer. Without this, a worker whose email BitBerry
    # assigned an agent to would never see it show up anywhere in the POS.
    'chat.view',
    # Staff + payroll are hidden from store managers for now.
}


def admin_emails() -> Set[str]:
    """Emails that should always be treated as admins (from the ADMIN_EMAILS env)."""
    raw = os.getenv('ADMIN_EMAILS', '')
    return {e.strip().lower() for e in raw.split(',') if e.strip()}


def _all_permission_codes() -> Set[str]:
    rows = execute_query("SELECT code FROM permissions", fetch=True) or []
    return {r['code'] for r in rows}


def role_permission_codes(role: Optional[str]) -> Set[str]:
    """Resolve the permission codes implied by a role."""
    if role == ROLE_ADMIN:
        return _all_permission_codes()
    if role == ROLE_MANAGER:
        return {c for c in _all_permission_codes() if not c.startswith('users.')}
    return set(WORKER_PERMISSION_CODES)


def _get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    return execute_query_one("SELECT * FROM users WHERE email=%s", (email,))


def get_or_create_current_user() -> Optional[Dict[str, Any]]:
    # Cache for the duration of the request to avoid repeated upserts/queries
    # (templates call has_perm() many times while rendering the nav).
    if hasattr(g, '_sn_current_user'):
        return g._sn_current_user

    email = session.get('user_id')
    if not email:
        g._sn_current_user = None
        return None
    full_name = session.get('user_name')
    picture = session.get('user_picture')
    user = upsert_user_from_session(email, full_name, picture)

    # Bootstrap: configured admin emails are always promoted to admin.
    if user and email.lower() in admin_emails() and user.get('role') != ROLE_ADMIN:
        execute_query("UPDATE users SET role=%s WHERE id=%s", (ROLE_ADMIN, user['id']))
        user['role'] = ROLE_ADMIN

    # A deactivated user has no current-user identity — every login_required /
    # permission_required check downstream treats this exactly like "not
    # logged in", which is what makes deactivation actually revoke access.
    if user and user.get('is_active') is False:
        g._sn_current_user = None
        return None

    g._sn_current_user = user
    return user


def current_user_role() -> str:
    """Role of the logged-in user, defaulting to worker."""
    user = get_or_create_current_user()
    return (user.get('role') if user else None) or ROLE_WORKER


def current_user_permissions() -> Set[str]:
    """Effective permission codes for the logged-in user (request-cached)."""
    if hasattr(g, '_sn_perms'):
        return g._sn_perms
    user = get_or_create_current_user()
    perms = compute_effective_permission_codes(user['id']) if user else set()
    g._sn_perms = perms
    return perms


def has_permission(code: str) -> bool:
    return code in current_user_permissions()


def is_store_manager() -> bool:
    """True for the worker role — a store manager scoped to one store."""
    return current_user_role() == ROLE_WORKER


def assigned_location_id() -> Optional[str]:
    """The store an admin has permanently assigned to this user (via Users &
    Access). When set, the manager is locked to it and cannot see other stores."""
    user = get_or_create_current_user()
    return str(user['location_id']) if user and user.get('location_id') else None


def active_location_id() -> Optional[str]:
    """The store this manager is operating: their admin-assigned store if set,
    otherwise the one they picked this session."""
    return assigned_location_id() or session.get('active_location_id')


def is_location_locked() -> bool:
    """True when a manager is pinned to one store by an admin and may not switch."""
    return is_store_manager() and assigned_location_id() is not None


def current_user_location_id() -> Optional[str]:
    """The store this user is tied to. Store managers use their admin-assigned
    store, else the one they selected; owners/managers aren't store-bound."""
    if is_store_manager():
        return active_location_id()
    return assigned_location_id()


def is_location_scoped() -> bool:
    """True when the user is limited to a single store's data. Store managers
    are always scoped; owners see every location."""
    return is_store_manager() and active_location_id() is not None


def scoped_location_id() -> Optional[str]:
    """The location to filter by, or None to mean 'all locations'."""
    return active_location_id() if is_location_scoped() else None


def owner_required(f):
    """Restrict a view to owners (admin/manager). Store-manager workers are
    bounced — used for master inventory and stock-quantity management."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('auth.login'))
        if current_user_role() == ROLE_WORKER:
            flash('That section is managed by the owner.', 'error')
            return redirect(url_for('inventory.location_inventory'))
        return f(*args, **kwargs)
    return wrapped


def compute_effective_permission_codes(user_id: str) -> Set[str]:
    # Collect allow/deny from role, position, department, user; denies override
    user = execute_query_one("SELECT id, position_id, department_id, role FROM users WHERE id=%s", (user_id,))
    if not user:
        return set()

    # Admins always have every permission, regardless of any deny rules.
    if user.get('role') == ROLE_ADMIN:
        return _all_permission_codes()

    # Start from the role's baseline grants, then layer position/department/user rules.
    allow_codes: Set[str] = set(role_permission_codes(user.get('role')))
    deny_codes: Set[str] = set()

    # Position
    if user.get('position_id'):
        rows = execute_query(
            """
            SELECT p.code, pp.effect FROM position_permissions pp
            JOIN permissions p ON p.id = pp.permission_id
            WHERE pp.position_id=%s
            """,
            (user['position_id'],),
            fetch=True,
        ) or []
        for r in rows:
            (deny_codes if r['effect'] == 'deny' else allow_codes).add(r['code'])

    # Department
    if user.get('department_id'):
        rows = execute_query(
            """
            SELECT p.code, dp.effect FROM department_permissions dp
            JOIN permissions p ON p.id = dp.permission_id
            WHERE dp.department_id=%s
            """,
            (user['department_id'],),
            fetch=True,
        ) or []
        for r in rows:
            (deny_codes if r['effect'] == 'deny' else allow_codes).add(r['code'])

    # User specific
    rows = execute_query(
        """
        SELECT p.code, up.effect FROM user_permissions up
        JOIN permissions p ON p.id = up.permission_id
        WHERE up.user_id=%s
        """,
        (user_id,),
        fetch=True,
    ) or []
    for r in rows:
        (deny_codes if r['effect'] == 'deny' else allow_codes).add(r['code'])

    # Deny overrides
    effective = {c for c in allow_codes if c not in deny_codes}
    return effective


def permission_required(permission_code: str):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not session.get('authenticated'):
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))

            user = get_or_create_current_user()
            if not user:
                flash('User account not found.', 'error')
                return redirect(url_for('auth.login'))

            perms = compute_effective_permission_codes(user['id'])
            if permission_code not in perms:
                flash('You do not have permission to perform this action.', 'error')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def require_module_view(view_code: str):
    """Build a blueprint ``before_request`` guard that requires ``view_code``.

    Used to lock entire management sections (inventory, staff, ...) so that
    workers without the permission are bounced to the dashboard.
    """
    def guard():
        if request.method == 'OPTIONS':
            return None
        if not session.get('authenticated'):
            return redirect(url_for('auth.login'))
        if not has_permission(view_code):
            flash('You do not have access to that section.', 'error')
            return redirect(url_for('main.dashboard'))
        return None
    return guard


# Payroll endpoints a worker may use on their own record even without payroll.view.
PAYROLL_SELF_SERVICE_ENDPOINTS = {
    'payroll.clock_in', 'payroll.clock_out',
    'payroll.start_break', 'payroll.end_break',
    'payroll.leave_request',
}


def payroll_access_guard():
    """Allow self-service clock/leave endpoints for everyone; gate the rest on payroll.view."""
    if request.method == 'OPTIONS':
        return None
    if not session.get('authenticated'):
        return redirect(url_for('auth.login'))
    if request.endpoint in PAYROLL_SELF_SERVICE_ENDPOINTS:
        return None
    if not has_permission('payroll.view'):
        flash('You do not have access to that section.', 'error')
        return redirect(url_for('main.dashboard'))
    return None


def register_template_helpers(app):
    """Expose role/permission helpers to all Jinja templates."""
    @app.context_processor
    def _inject_access_helpers():
        return {
            'has_perm': has_permission,
            'current_role': current_user_role,
            'is_scoped': is_location_scoped,
            'scoped_location_id': scoped_location_id,
            'is_store_manager': is_store_manager,
            'active_location_id': active_location_id,
            'is_location_locked': is_location_locked,
        }


def _get_api_key_from_request() -> Optional[Dict[str, Any]]:
    header = request.headers.get('Authorization')
    api_key = None
    if header and header.lower().startswith('bearer '):
        api_key = header.split(' ', 1)[1].strip()
    if not api_key:
        api_key = request.headers.get('X-API-Key')
    if not api_key:
        return None

    from database import hash_api_key
    token_hash = hash_api_key(api_key)
    prefix = api_key[:12]
    key_row = execute_query_one(
        """
        SELECT * FROM api_keys WHERE token_prefix=%s AND token_hash=%s AND revoked_at IS NULL
        """,
        (prefix, token_hash),
    )
    if key_row:
        # Touch last used
        execute_query("UPDATE api_keys SET last_used_at=CURRENT_TIMESTAMP WHERE id=%s", (key_row['id'],))
    return key_row


def api_key_required(required_scopes: Optional[List[str]] = None):
    required_scopes = required_scopes or []

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            key_row = _get_api_key_from_request()
            if not key_row:
                return ({'success': False, 'message': 'Invalid or missing API key'}, 401)

            # Validate scopes
            key_scopes = set((key_row.get('scopes') or []))
            for s in required_scopes:
                if s not in key_scopes:
                    return ({'success': False, 'message': 'Insufficient scope'}, 403)

            # Stash for auditing
            g.api_key = key_row
            return f(*args, **kwargs)
        return wrapped
    return decorator


def register_audit_hooks(app):
    @app.before_request
    def _before():
        g._sn_action_success = None  # to be set by view optionally

    @app.after_request
    def _after(response):
        try:
            actor_user_id = None
            if session.get('authenticated'):
                user = _get_user_by_email(session.get('user_id'))
                actor_user_id = user['id'] if user else None

            actor_api_key_id = getattr(g, 'api_key', {}).get('id') if hasattr(g, 'api_key') else None
            record_audit_log(
                actor_user_id=actor_user_id,
                actor_api_key_id=actor_api_key_id,
                action='request',
                target_type=None,
                target_id=None,
                route=request.path,
                method=request.method,
                status_code=response.status_code,
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
                success=True if 200 <= response.status_code < 400 else False,
                metadata={
                    'endpoint': request.endpoint,
                    'args': request.args.to_dict(),
                },
            )
        except Exception:
            # Avoid breaking responses on audit failures
            pass
        return response


