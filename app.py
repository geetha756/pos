from flask import Flask
import os
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables from dev.env file
load_dotenv('.env')

def create_app():
    """Create and configure the Flask application"""
    app = Flask(__name__)

    # Trust the X-Forwarded-* headers set by Cloudflare Tunnel / reverse proxy
    # so the app knows it is actually being served over HTTPS. Without this,
    # generated absolute URLs would use http and break behind the tunnel.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Load configuration from environment variables
    app.config.update({
        # Flask configuration
        'SECRET_KEY': os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production'),
        'FLASK_ENV': os.getenv('FLASK_ENV', 'development'),
        'DEBUG': os.getenv('FLASK_ENV', 'development') == 'development',
        'TESTING': os.getenv('FLASK_ENV', 'development') == 'testing',

        # Database configuration
        'DATABASE_URL': os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/sipnsnack'),

        # Security settings
        'SESSION_COOKIE_SECURE': os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true',
        'SESSION_COOKIE_HTTPONLY': True,
        # 'Lax' (not 'Strict') so the session cookie survives the top-level
        # redirect back from Google during OAuth login.
        'SESSION_COOKIE_SAMESITE': 'Lax',
        # Keep store managers logged in across shifts (30 days) instead of being
        # signed out when the app/browser is closed. Paired with session.permanent
        # in the auth flow.
        'PERMANENT_SESSION_LIFETIME': __import__('datetime').timedelta(days=30),

        # CSRF protection
        'WTF_CSRF_ENABLED': True,
        'WTF_CSRF_SECRET_KEY': os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production'),
    })

    # Initialize security schema and permissions within app context
    from security import init_security_schema_and_seed, register_audit_hooks
    from database import init_store_purchases_schema
    with app.app_context():
        init_security_schema_and_seed()
        init_store_purchases_schema()

    # Register blueprints
    from routes.auth import auth_bp
    from routes.main import main_bp
    from routes.master_menu import master_menu_bp
    from routes.locations import locations_bp
    from routes.location_menu import location_menu_bp
    from routes.orders import orders_bp
    from routes.staff import staff_bp
    from routes.departments import departments_bp
    from routes.positions import positions_bp
    from routes.payroll import payroll_bp
    from routes.inventory import inventory_bp
    from routes.users import users_bp
    from routes.machines import machines_bp, init_machines_schema
    from routes.chat import chat_bp

    # Role-based access control: lock management sections behind their module's
    # view permission. Must be attached before the blueprints are registered.
    # Workers (default role) only keep the dashboard + payroll self-service.
    from security import require_module_view, payroll_access_guard, register_template_helpers
    master_menu_bp.before_request(require_module_view('master_menu.view'))
    locations_bp.before_request(require_module_view('locations.view'))
    location_menu_bp.before_request(require_module_view('location_menu.view'))
    orders_bp.before_request(require_module_view('orders.view'))
    staff_bp.before_request(require_module_view('staff.view'))
    departments_bp.before_request(require_module_view('departments.view'))
    positions_bp.before_request(require_module_view('positions.view'))
    inventory_bp.before_request(require_module_view('inventory.view'))
    users_bp.before_request(require_module_view('users.view'))
    payroll_bp.before_request(payroll_access_guard)
    # No blueprint-wide guard for machines_bp: its /api/push/* routes are
    # called by Node-RED hardware with no login session at all (matching the
    # other system's documented, intentional design). Only the dashboard page
    # itself is permission-gated — see @permission_required in routes/machines.py.

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(master_menu_bp, url_prefix='/master-menu')
    app.register_blueprint(locations_bp, url_prefix='/locations')
    app.register_blueprint(location_menu_bp, url_prefix='/location-menu')
    app.register_blueprint(orders_bp, url_prefix='/orders')
    app.register_blueprint(staff_bp, url_prefix='/staff')
    app.register_blueprint(departments_bp, url_prefix='/departments')
    app.register_blueprint(positions_bp, url_prefix='/positions')
    app.register_blueprint(payroll_bp, url_prefix='/payroll')
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(machines_bp, url_prefix='/machines')
    app.register_blueprint(chat_bp, url_prefix='/chat')

    with app.app_context():
        init_machines_schema()

    # Background /status poller (see eidli_client.start_status_poller) — the
    # Electric Idli Machine's /status is measurably slower and far more
    # variable than every other endpoint on that service (400ms-1000ms vs.
    # consistently <300ms elsewhere), consistent with a live device
    # round-trip rather than a database read. This keeps a fresh cached
    # result the /idli/api/status route can serve instantly instead of the
    # browser waiting on that round-trip on every single poll.
    #
    # Guarded so it starts exactly once per real serving process: under the
    # debug reloader, create_app() runs once in the parent watcher process
    # (which never actually serves a request) and once in the forked child
    # — WERKZEUG_RUN_MAIN distinguishes them. Outside debug mode there's no
    # reloader/no parent process, so this always starts.
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        import eidli_client
        eidli_client.start_status_poller(EIDLI_MACHINE_ID)

    # Make has_perm()/current_role available in templates (nav gating)
    register_template_helpers(app)

    # Display timestamps in IST. Columns are `timestamp without time zone`
    # stored in UTC (the DB runs in UTC), so we add the fixed +5:30 offset
    # (IST has no DST) and format for display via the `ist` Jinja filter.
    from datetime import timedelta
    _IST_OFFSET = timedelta(hours=5, minutes=30)

    @app.template_filter('ist')
    def _to_ist(value, fmt='%d %b %Y, %I:%M %p'):
        if not value:
            return ''
        try:
            return (value + _IST_OFFSET).strftime(fmt)
        except Exception:
            return str(value)

    # Short, consistent display labels for inventory units (kg/g/liter/ml/...).
    # Unrecognized/legacy free-text unit values (entered before units were a
    # dropdown) pass through unchanged.
    _UNIT_LABELS = {
        'kg': 'kg', 'g': 'g', 'liter': 'L', 'l': 'L', 'ml': 'mL',
        'pieces': 'pcs', 'boxes': 'box', 'cans': 'can', 'packets': 'pkt',
    }

    @app.template_filter('unit_label')
    def _unit_label(value):
        if not value:
            return ''
        return _UNIT_LABELS.get(str(value).strip().lower(), value)

    # Store managers must pick which store they're operating before they can use
    # the app; until they do, every page redirects to the location picker.
    from flask import request, redirect, url_for, session
    _LOCATION_EXEMPT = {
        'static', 'main.select_location', 'main.manifest', 'main.service_worker',
        'main.assetlinks', 'main.download_app', 'main.install_page',
        'auth.login', 'auth.google_auth', 'auth.google_callback',
        'auth.process_auth', 'auth.logout',
    }

    @app.before_request
    def _require_store_selection():
        if not session.get('authenticated'):
            return None
        if (request.endpoint or '') in _LOCATION_EXEMPT:
            return None
        from security import is_store_manager, active_location_id
        if is_store_manager() and not active_location_id():
            return redirect(url_for('main.select_location'))
        return None

    # Register audit hooks after blueprints
    register_audit_hooks(app)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5002)
