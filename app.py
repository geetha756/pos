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

        # CSRF protection
        'WTF_CSRF_ENABLED': True,
        'WTF_CSRF_SECRET_KEY': os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production'),
    })

    # Initialize security schema and permissions within app context
    from security import init_security_schema_and_seed, register_audit_hooks
    with app.app_context():
        init_security_schema_and_seed()

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
    # Machines module is disabled for now (not in use). Re-enable by restoring
    # this import, its registration, and the schema init below.
    # from routes.machines import machines_bp, init_machines_schema

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
    # app.register_blueprint(machines_bp, url_prefix='/machines')  # disabled

    # Machines schema init disabled along with the module:
    # with app.app_context():
    #     init_machines_schema()

    # Make has_perm()/current_role available in templates (nav gating)
    register_template_helpers(app)

    # Register audit hooks after blueprints
    register_audit_hooks(app)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
