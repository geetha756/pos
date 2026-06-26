from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from database import execute_query, execute_query_one
from .auth import login_required
import json
import os
import psycopg2

main_bp = Blueprint('main', __name__)


@main_bp.route('/.well-known/assetlinks.json')
def assetlinks():
    """Digital Asset Links — proves this site owns the Android app so the
    installed TWA opens fullscreen with no browser URL bar.

    Fill ANDROID_PACKAGE_NAME and ANDROID_CERT_FINGERPRINTS (comma-separated
    SHA-256 fingerprints from your signing key) in the server's .env after you
    build the APK. Until then this returns an empty list (harmless).
    """
    package = os.getenv('ANDROID_PACKAGE_NAME', '').strip()
    fingerprints = [fp.strip() for fp in os.getenv('ANDROID_CERT_FINGERPRINTS', '').split(',') if fp.strip()]
    data = []
    if package and fingerprints:
        data = [{
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": package,
                "sha256_cert_fingerprints": fingerprints,
            },
        }]
    return Response(json.dumps(data), mimetype="application/json")


# ---------------------------------------------------------------------------
# Progressive Web App (installable "Add to Home Screen") support
# ---------------------------------------------------------------------------
@main_bp.route('/manifest.webmanifest')
def manifest():
    """Web app manifest so the portal can be installed like a native app."""
    data = {
        "name": "Sip & Snack Portal",
        "short_name": "Sip & Snack",
        "description": "Restaurant Chain Management Portal",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#ffffff",
        "theme_color": "#0d6efd",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")


@main_bp.route('/sw.js')
def service_worker():
    """Service worker served from the root so its scope covers the whole app."""
    js = """
const CACHE = 'sns-cache-v1';
const PRECACHE = ['/static/css/bootstrap.min.css', '/static/css/dashboard.css', '/static/icons/icon-192.png'];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE).catch(() => {})));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // Network-first for page navigations so role-specific content stays fresh.
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match(req).then((r) => r || caches.match('/'))));
    return;
  }
  // Cache-first for static assets.
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(req).then((r) => r || fetch(req).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return resp;
      }))
    );
  }
});
"""
    resp = Response(js, mimetype="application/javascript")
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@main_bp.route('/')
@login_required
def dashboard():
    """Main dashboard page"""
    try:
        # Scope the tiles to the manager's store when applicable
        from security import scoped_location_id
        stats = get_dashboard_stats(scoped_location_id())
        return render_template('dashboard.html', stats=stats)
    except Exception as e:
        flash(f'Database error: {str(e)}', 'error')
        return render_template('dashboard.html', stats={'locations': 0, 'menu_items': 0, 'orders': 0, 'total_revenue': 0.0})


def get_dashboard_stats(location_id=None):
    """Get dashboard statistics, optionally scoped to a single store."""
    loc = location_id  # when set, scope the location-specific tiles to this store
    stats = {
        'locations': 0,
        'menu_items': 0,
        'orders': 0,
        'total_revenue': 0.0,
        'pending_orders': 0,
        'today_orders': 0,
        'staff': 0,
        'active_staff': 0,
        'departments': 0,
        'positions': 0,
        'total_employees': 0,
        'active_timesheets': 0,
        'pending_leave_requests': 0,
        'total_payroll_expense': 0.0,
        # Users & Access
        'users': 0,
        'active_users': 0,
        # Inventory
        'total_master_items': 0,
        'low_stock_items': 0,
        'active_purchase_lists': 0,
        'suppliers': 0
    }

    try:
        # Count locations (a scoped manager has exactly their one store)
        if loc:
            stats['locations'] = 1
        else:
            result = execute_query_one("SELECT COUNT(*) as count FROM locations")
            stats['locations'] = result['count'] if result else 0

        # Count menu items (this store's menu when scoped, else the master catalog)
        if loc:
            result = execute_query_one("SELECT COUNT(*) as count FROM location_menu WHERE location_id = %s AND is_available = TRUE", (loc,))
        else:
            result = execute_query_one("SELECT COUNT(*) as count FROM master_menu WHERE is_active = TRUE")
        stats['menu_items'] = result['count'] if result else 0

        # Count total orders
        result = execute_query_one("SELECT COUNT(*) as count FROM orders WHERE (%s IS NULL OR location_id = %s)", (loc, loc))
        stats['orders'] = result['count'] if result else 0

        # Total revenue
        result = execute_query_one("SELECT COALESCE(SUM(total_amount), 0) as total FROM orders WHERE status != 'cancelled' AND (%s IS NULL OR location_id = %s)", (loc, loc))
        stats['total_revenue'] = float(result['total']) if result else 0.0

        # Pending orders
        result = execute_query_one("SELECT COUNT(*) as count FROM orders WHERE status IN ('pending', 'preparing') AND (%s IS NULL OR location_id = %s)", (loc, loc))
        stats['pending_orders'] = result['count'] if result else 0

        # Today's orders
        result = execute_query_one("SELECT COUNT(*) as count FROM orders WHERE DATE(created_at) = CURRENT_DATE AND (%s IS NULL OR location_id = %s)", (loc, loc))
        stats['today_orders'] = result['count'] if result else 0

        # Total staff count
        result = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE (%s IS NULL OR location_id = %s)", (loc, loc))
        stats['staff'] = result['count'] if result else 0

        # Active staff count
        result = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE is_active = TRUE AND (%s IS NULL OR location_id = %s)", (loc, loc))
        stats['active_staff'] = result['count'] if result else 0

        # Department count
        result = execute_query_one("SELECT COUNT(*) as count FROM departments WHERE is_active = TRUE")
        stats['departments'] = result['count'] if result else 0

        # Position count
        result = execute_query_one("SELECT COUNT(*) as count FROM positions WHERE is_active = TRUE")
        stats['positions'] = result['count'] if result else 0

        # Users & Access statistics
        result = execute_query_one("SELECT COUNT(*) as count FROM users")
        stats['users'] = result['count'] if result else 0

        result = execute_query_one("SELECT COUNT(*) as count FROM users WHERE is_active = TRUE")
        stats['active_users'] = result['count'] if result else 0

        # Payroll statistics
        # Total employees (from staff table)
        result = execute_query_one("SELECT COUNT(*) as count FROM staff WHERE is_active = TRUE AND (%s IS NULL OR location_id = %s)", (loc, loc))
        stats['total_employees'] = result['count'] if result else 0

        # Active timesheets (draft or submitted this week)
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM timesheets t
            JOIN staff s ON t.staff_id = s.id
            WHERE t.date >= CURRENT_DATE - INTERVAL '7 days'
            AND t.status IN ('draft', 'submitted')
            AND (%s IS NULL OR s.location_id = %s)
        """, (loc, loc))
        stats['active_timesheets'] = result['count'] if result else 0

        # Pending leave requests
        result = execute_query_one("""
            SELECT COUNT(*) as count FROM leave_requests lr
            JOIN staff s ON lr.staff_id = s.id
            WHERE lr.status = 'pending' AND (%s IS NULL OR s.location_id = %s)
        """, (loc, loc))
        stats['pending_leave_requests'] = result['count'] if result else 0

        # Total payroll expense (last 30 days)
        result = execute_query_one("""
            SELECT COALESCE(SUM(pe.net_pay), 0) as total FROM payroll_entries pe
            JOIN payroll_cycles pc ON pe.payroll_cycle_id = pc.id
            JOIN staff s ON pe.staff_id = s.id
            WHERE pc.end_date >= CURRENT_DATE - INTERVAL '30 days'
            AND pe.status = 'paid'
            AND (%s IS NULL OR s.location_id = %s)
        """, (loc, loc))
        stats['total_payroll_expense'] = result['total'] if result else 0.0

        # Inventory statistics
        result = execute_query_one("SELECT COUNT(*) as count FROM master_inventory WHERE is_active = TRUE")
        stats['total_master_items'] = result['count'] if result else 0

        result = execute_query_one("""
            SELECT COUNT(*) as count FROM location_inventory
            WHERE current_stock <= reorder_point AND (%s IS NULL OR location_id = %s)
        """, (loc, loc))
        stats['low_stock_items'] = result['count'] if result else 0

        result = execute_query_one("""
            SELECT COUNT(*) as count FROM purchase_lists
            WHERE status IN ('draft', 'submitted', 'approved') AND (%s IS NULL OR location_id = %s)
        """, (loc, loc))
        stats['active_purchase_lists'] = result['count'] if result else 0

        result = execute_query_one("SELECT COUNT(*) as count FROM suppliers WHERE is_active = TRUE")
        stats['suppliers'] = result['count'] if result else 0

    except Exception as e:
        print(f"Error getting dashboard stats: {e}")

    return stats
