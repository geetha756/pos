from flask import Flask
import os
from dotenv import load_dotenv

# Load environment variables from dev.env file
load_dotenv('dev.env')

def create_app():
    """Create and configure the Flask application"""
    app = Flask(__name__)

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
        'SESSION_COOKIE_SAMESITE': 'Strict' if os.getenv('FLASK_ENV') == 'production' else 'Lax',

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

    # Register audit hooks after blueprints
    register_audit_hooks(app)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
