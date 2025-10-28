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


def _get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    return execute_query_one("SELECT * FROM users WHERE email=%s", (email,))


def get_or_create_current_user() -> Optional[Dict[str, Any]]:
    email = session.get('user_id')
    if not email:
        return None
    full_name = session.get('user_name')
    picture = session.get('user_picture')
    return upsert_user_from_session(email, full_name, picture)


def compute_effective_permission_codes(user_id: str) -> Set[str]:
    # Collect allow/deny from position, department, user; denies override
    user = execute_query_one("SELECT id, position_id, department_id FROM users WHERE id=%s", (user_id,))
    if not user:
        return set()

    allow_codes: Set[str] = set()
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


