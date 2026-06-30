import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import threading
from flask import current_app
from typing import Optional, List, Dict, Any, Tuple
import hashlib
import secrets
import json

# ---------------------------------------------------------------------------
# Connection pool — reuse connections instead of opening a new one per query.
# This is a large speed-up: each request previously paid a full TCP + auth
# handshake for every single query.
# ---------------------------------------------------------------------------
_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    1, 10, dsn=current_app.config['DATABASE_URL']
                )
    return _pool


def get_db_connection():
    """Borrow a pooled DB connection (falls back to a direct connect if pooling
    is somehow unavailable)."""
    try:
        return _get_pool().getconn()
    except Exception as e:
        print(f"Database connection error: {e}")
        # Last-resort fallback so the app keeps working even if the pool breaks.
        return psycopg2.connect(current_app.config['DATABASE_URL'])


def _put(conn, broken=False):
    """Return a connection to the pool (or close it if it's broken)."""
    try:
        _get_pool().putconn(conn, close=broken)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _execute(query, params, fetch):
    """fetch: 'all' | 'one' | None. Retries idempotent reads once if a pooled
    connection turns out to be stale."""
    for attempt in (1, 2):
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if fetch else conn.cursor()
        try:
            cursor.execute(query, params or ())
            result = cursor.fetchall() if fetch == 'all' else (cursor.fetchone() if fetch == 'one' else None)
            conn.commit()
            cursor.close()
            _put(conn)
            return result
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            try:
                cursor.close()
            except Exception:
                pass
            _put(conn, broken=True)            # drop the stale/broken connection
            if fetch and attempt == 1:
                continue                        # safe to retry a read once
            raise
        except Exception:
            try:
                cursor.close()
            except Exception:
                pass
            try:
                conn.rollback()
                _put(conn)                      # query error; connection still healthy
            except Exception:
                _put(conn, broken=True)
            raise


# Utility functions for database operations
def execute_query(query, params=None, fetch=False):
    """Execute a database query."""
    return _execute(query, params, 'all' if fetch else None)


def execute_query_one(query, params=None):
    """Execute a query and fetch one result."""
    return _execute(query, params, 'one')


def execute_transaction(operations):
    """Run several (query, params) statements in ONE transaction — all commit
    together or none do. Use for multi-row writes that must stay consistent
    (e.g. an order + its items), so a failure can never leave a half-saved row."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for query, params in operations:
            cursor.execute(query, params or ())
        conn.commit()
        cursor.close()
        _put(conn)
    except Exception:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.rollback()
            _put(conn)
        except Exception:
            _put(conn, broken=True)
        raise


def init_user_admin_schema():
    """Create tables for user administration, permissions, API keys, and audit logs if they don't exist."""
    # Core users table
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            email VARCHAR(255) UNIQUE NOT NULL,
            full_name VARCHAR(255),
            picture_url TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            staff_id UUID REFERENCES staff(id),
            position_id UUID REFERENCES positions(id),
            department_id UUID REFERENCES departments(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # Access role for each user: 'worker' (default), 'manager', or 'admin'.
    # Added via ALTER so existing databases pick it up too.
    execute_query(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'worker'"
    )

    # The store a worker is tied to. When set (and role='worker') the user only
    # sees that location's data. NULL = not scoped (owner/manager, or unassigned).
    execute_query(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS location_id UUID REFERENCES locations(id)"
    )

    # Track when/by whom an order was edited after being placed, so the admin
    # can see an "Edited" marker on the order.
    execute_query("ALTER TABLE orders ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP")
    execute_query("ALTER TABLE orders ADD COLUMN IF NOT EXISTS edited_by UUID")

    # Self-healing migrations for features added over time. Every column uses
    # "IF NOT EXISTS" so a deploy (fresh DB or existing) always converges to the
    # right schema with no manual SQL — the safe pattern to follow when payroll
    # and other modules are switched on later.
    execute_query("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(20) DEFAULT 'cash'")
    execute_query("ALTER TABLE location_menu ADD COLUMN IF NOT EXISTS section VARCHAR(20) DEFAULT 'all'")
    # Idempotency key for offline order queue: a unique client id makes a
    # re-sent / queued order return the same order instead of duplicating it.
    execute_query("ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(64)")
    execute_query("CREATE UNIQUE INDEX IF NOT EXISTS orders_client_order_id_uniq "
                  "ON orders (client_order_id) WHERE client_order_id IS NOT NULL")

    # Permissions catalog
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS permissions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            code VARCHAR(100) UNIQUE NOT NULL, -- e.g., 'inventory.view'
            module VARCHAR(100) NOT NULL,
            action VARCHAR(100) NOT NULL,
            description TEXT
        );
        """
    )

    # Grants/denies at different levels
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS user_permissions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
            permission_id UUID REFERENCES permissions(id) ON DELETE CASCADE NOT NULL,
            effect VARCHAR(10) NOT NULL CHECK (effect IN ('allow','deny')),
            UNIQUE(user_id, permission_id)
        );
        """
    )

    execute_query(
        """
        CREATE TABLE IF NOT EXISTS position_permissions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            position_id UUID REFERENCES positions(id) ON DELETE CASCADE NOT NULL,
            permission_id UUID REFERENCES permissions(id) ON DELETE CASCADE NOT NULL,
            effect VARCHAR(10) NOT NULL CHECK (effect IN ('allow','deny')),
            UNIQUE(position_id, permission_id)
        );
        """
    )

    execute_query(
        """
        CREATE TABLE IF NOT EXISTS department_permissions (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            department_id UUID REFERENCES departments(id) ON DELETE CASCADE NOT NULL,
            permission_id UUID REFERENCES permissions(id) ON DELETE CASCADE NOT NULL,
            effect VARCHAR(10) NOT NULL CHECK (effect IN ('allow','deny')),
            UNIQUE(department_id, permission_id)
        );
        """
    )

    # API keys
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
            name VARCHAR(255) NOT NULL,
            token_prefix VARCHAR(12) NOT NULL,
            token_hash VARCHAR(128) NOT NULL,
            scopes JSONB NOT NULL DEFAULT '[]'::jsonb, -- array of permission codes
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP,
            revoked_at TIMESTAMP,
            UNIQUE(token_prefix)
        );
        """
    )

    # Audit logs
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            actor_user_id UUID REFERENCES users(id),
            actor_api_key_id UUID REFERENCES api_keys(id),
            action VARCHAR(100) NOT NULL, -- e.g., 'user.create', 'orders.update_status'
            target_type VARCHAR(100), -- e.g., 'user','order','position'
            target_id UUID,
            route TEXT,
            method VARCHAR(10),
            status_code INTEGER,
            ip_address INET,
            user_agent TEXT,
            success BOOLEAN,
            metadata JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # Helpful indexes
    execute_query("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
    execute_query("CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor_user_id);")
    execute_query("CREATE INDEX IF NOT EXISTS idx_audit_logs_route ON audit_logs(route);")
    execute_query("CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);")


def seed_permissions_if_needed():
    """Seed a standard set of module/action permissions if the table is empty."""
    existing = execute_query_one("SELECT COUNT(*) AS c FROM permissions")
    count = existing['c'] if existing else 0
    if count and count > 0:
        return

    modules_actions: Dict[str, List[str]] = {
        'dashboard': ['view'],
        'master_menu': ['view','create','edit','delete','export'],
        'locations': ['view','create','edit','delete'],
        'location_menu': ['view','manage'],
        'orders': ['view','create','edit','delete','approve','export'],
        'staff': ['view','create','edit','delete','export'],
        'departments': ['view','create','edit','delete'],
        'positions': ['view','create','edit','delete'],
        'payroll': ['view','create','edit','approve','export'],
        'inventory': ['view','create','edit','delete','adjust','export'],
        'users': ['view','create','edit','delete','manage_permissions','manage_api_keys','view_audit']
    }

    for module, actions in modules_actions.items():
        for action in actions:
            code = f"{module}.{action}"
            execute_query(
                """
                INSERT INTO permissions (code, module, action, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (code) DO NOTHING
                """,
                (code, module, action, f"Permission to {action.replace('_',' ')} for {module}")
            )

    # Bootstrap: grant Users module permissions to Management department if present
    management = execute_query_one("SELECT id FROM departments WHERE name='Management' LIMIT 1")
    if management and management.get('id'):
        perm_rows = execute_query("SELECT id FROM permissions WHERE module='users'", fetch=True) or []
        for pr in perm_rows:
            execute_query(
                """
                INSERT INTO department_permissions (department_id, permission_id, effect)
                VALUES (%s, %s, 'allow')
                ON CONFLICT (department_id, permission_id) DO NOTHING
                """,
                (management['id'], pr['id'])
            )


def upsert_user_from_session(email: str, full_name: Optional[str], picture_url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Ensure a users row exists for the given email. Update profile fields if changed. Return the user row."""
    if not email:
        return None
    user = execute_query_one("SELECT * FROM users WHERE email=%s", (email,))
    if user:
        execute_query(
            """
            UPDATE users SET full_name=COALESCE(%s, full_name), picture_url=COALESCE(%s, picture_url), updated_at=CURRENT_TIMESTAMP
            WHERE email=%s
            """,
            (full_name, picture_url, email)
        )
    else:
        # Try to link to staff by email if exists
        staff = execute_query_one("SELECT id, position_id, department_id FROM staff WHERE email=%s", (email,))
        execute_query(
            """
            INSERT INTO users (email, full_name, picture_url, staff_id, position_id, department_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING
            """,
            (
                email,
                full_name,
                picture_url,
                staff['id'] if staff else None,
                staff['position_id'] if staff else None,
                staff['department_id'] if staff else None,
            )
        )
    return execute_query_one("SELECT * FROM users WHERE email=%s", (email,))


def generate_api_key_token() -> Tuple[str, str]:
    """Generate a new API key token and return (token, prefix)."""
    token = secrets.token_urlsafe(40)
    prefix = token[:12]
    return token, prefix


def hash_api_key(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create_api_key(user_id: str, name: str, scopes: List[str]) -> Tuple[str, Dict[str, Any]]:
    """Create an API key for a user. Returns (plain_token, api_key_row)."""
    token, prefix = generate_api_key_token()
    token_hash = hash_api_key(token)
    execute_query(
        """
        INSERT INTO api_keys (user_id, name, token_prefix, token_hash, scopes)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        """,
        (user_id, name, prefix, token_hash, json.dumps(scopes or []))
    )
    row = execute_query_one("SELECT * FROM api_keys WHERE token_prefix=%s", (prefix,))
    return token, row


def revoke_api_key(api_key_id: str):
    execute_query("UPDATE api_keys SET revoked_at=CURRENT_TIMESTAMP WHERE id=%s AND revoked_at IS NULL", (api_key_id,))


def record_audit_log(
    *,
    actor_user_id: Optional[str],
    actor_api_key_id: Optional[str],
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    route: Optional[str] = None,
    method: Optional[str] = None,
    status_code: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    execute_query(
        """
        INSERT INTO audit_logs (actor_user_id, actor_api_key_id, action, target_type, target_id, route, method, status_code, ip_address, user_agent, success, metadata)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        """,
        (
            actor_user_id,
            actor_api_key_id,
            action,
            target_type,
            target_id,
            route,
            method,
            status_code,
            ip_address,
            user_agent,
            success,
            json.dumps(metadata) if metadata is not None else None,
        ),
    )
