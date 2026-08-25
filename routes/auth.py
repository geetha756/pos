from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from google.auth.transport import requests
from google.oauth2 import id_token
import requests as req
import os
import json
from urllib.parse import quote

auth_bp = Blueprint('auth', __name__)

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://127.0.0.1:5000/auth/callback')

# Only Google accounts on these domains may sign in (comma-separated in env).
# Defaults to the SN15 organization domain so only @sn15.ai accounts are allowed.
ALLOWED_EMAIL_DOMAINS = [
    d.strip().lower().lstrip('@')
    for d in os.getenv('ALLOWED_EMAIL_DOMAINS', 'sn15.ai').split(',')
    if d.strip()
]

@auth_bp.route('/login')
def login():
    """Display login page"""
    return render_template('auth/login.html')

@auth_bp.route('/auth/google')
def google_auth():
    """Initiate Google OAuth flow"""
    if not GOOGLE_CLIENT_ID:
        flash('Google OAuth not configured. Please set GOOGLE_CLIENT_ID environment variable.', 'error')
        return redirect(url_for('auth.login'))

    # Where to send the user after a successful callback (defaults to the
    # dashboard). Used by silent-reauth (see /auth/google/silent below) so a
    # feature like chat can send the user right back to what they were doing.
    next_url = request.args.get('next')
    if next_url:
        session['post_login_next'] = next_url

    # Google OAuth URL
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={GOOGLE_REDIRECT_URI}&"
        f"scope=openid email profile&"
        f"response_type=code&"
        f"access_type=offline&"
        f"prompt=select_account&"
        f"include_granted_scopes=true"
    )

    return redirect(auth_url)


@auth_bp.route('/auth/google/silent')
def google_auth_silent():
    """Re-run the OAuth flow with prompt=none: Google issues a fresh code
    with no visible consent/account screen as long as the browser still has
    an active Google session, so this refreshes an expired ID token
    invisibly. If Google can't do it silently (no active Google session), it
    redirects to /auth/callback with error=login_required/interaction_required,
    and that callback falls back to the normal visible login screen.
    """
    if not GOOGLE_CLIENT_ID:
        flash('Google OAuth not configured. Please set GOOGLE_CLIENT_ID environment variable.', 'error')
        return redirect(url_for('auth.login'))

    next_url = request.args.get('next')
    if next_url:
        session['post_login_next'] = next_url

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={quote(GOOGLE_CLIENT_ID)}&"
        f"redirect_uri={quote(GOOGLE_REDIRECT_URI, safe='')}&"
        f"scope=openid email profile&"
        f"response_type=code&"
        f"prompt=none&"
        f"include_granted_scopes=true&"
        # login_hint is an email; must be percent-encoded (a '+' in a
        # Gmail-style plus-addressed email is otherwise read as a literal
        # space by Google's query parser and the hint silently breaks).
        f"login_hint={quote(session.get('user_id', ''), safe='')}"
    )

    return redirect(auth_url)

@auth_bp.route('/auth/callback')
def google_callback():
    """Handle Google OAuth callback"""
    code = request.args.get('code')
    error = request.args.get('error')

    if error:
        # These two are Google's expected response to a prompt=none silent
        # reauth when it can't complete one without user interaction (no
        # active Google browser session) — fall through to a normal, visible
        # login instead of showing an "authentication failed" error for what
        # is really just "silent refresh wasn't possible this time".
        if error in ('login_required', 'interaction_required'):
            return redirect(url_for('auth.login'))
        flash(f'Authentication failed: {error}', 'error')
        return redirect(url_for('auth.login'))

    if not code:
        flash('No authorization code received', 'error')
        return redirect(url_for('auth.login'))

    # Show loading page first
    return render_template('auth/loading.html')

@auth_bp.route('/auth/process')
def process_auth():
    """Process the authentication in background"""
    code = request.args.get('code')
    
    if not code:
        flash('No authorization code received', 'error')
        return redirect(url_for('auth.login'))
    
    try:
        # Exchange code for tokens
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': GOOGLE_REDIRECT_URI
        }
        
        token_response = req.post(token_url, data=token_data)
        token_json = token_response.json()
        
        if 'error' in token_json:
            flash(f'Token exchange failed: {token_json["error"]}', 'error')
            return redirect(url_for('auth.login'))
        
        access_token = token_json.get('access_token')
        id_token_jwt = token_json.get('id_token')
        
        # Verify and decode the ID token
        try:
            # Create a custom request object with clock skew tolerance
            from google.auth.transport import requests as google_requests
            from google.auth.exceptions import GoogleAuthError
            
            # Use a custom request that allows for clock skew
            custom_request = google_requests.Request()
            
            # First try with clock skew tolerance
            try:
                idinfo = id_token.verify_oauth2_token(
                    id_token_jwt, 
                    custom_request, 
                    GOOGLE_CLIENT_ID,
                    clock_skew_in_seconds=60  # Allow 60 seconds of clock skew
                )
            except ValueError as clock_error:
                # If clock skew error, try without verification (less secure but works)
                if "Token used too early" in str(clock_error) or "clock" in str(clock_error).lower():
                    print(f"Clock skew detected, using fallback verification: {clock_error}")
                    # Decode without verification as fallback
                    import base64
                    import json
                    
                    # Split the JWT token
                    parts = id_token_jwt.split('.')
                    if len(parts) != 3:
                        raise ValueError("Invalid JWT token format")
                    
                    # Decode the payload (middle part)
                    payload = parts[1]
                    # Add padding if needed
                    payload += '=' * (4 - len(payload) % 4)
                    decoded_payload = base64.urlsafe_b64decode(payload)
                    idinfo = json.loads(decoded_payload)
                    
                    # Basic validation
                    if idinfo.get('aud') != GOOGLE_CLIENT_ID:
                        raise ValueError("Token audience mismatch")
                    if idinfo.get('iss') not in ['https://accounts.google.com', 'accounts.google.com']:
                        raise ValueError("Invalid token issuer")
                else:
                    raise clock_error
            
            # Extract user information
            user_email = idinfo.get('email')
            user_name = idinfo.get('name')
            user_picture = idinfo.get('picture')
            
            # Restrict sign-in to approved organization domains (default @sn15.ai).
            # Explicitly-configured admins (ADMIN_EMAILS) are always allowed in,
            # even off-domain, so the owner can never be locked out.
            from security import admin_emails
            normalized_email = (user_email or '').strip().lower()
            email_domain = normalized_email.rsplit('@', 1)[-1]
            if email_domain not in ALLOWED_EMAIL_DOMAINS and normalized_email not in admin_emails():
                flash('Access denied. Please sign in with your @sn15.ai account.', 'error')
                return redirect(url_for('auth.login'))
            
            # Store user information in session
            session.permanent = True  # honour PERMANENT_SESSION_LIFETIME (stay logged in)
            session['user_id'] = user_email  # legacy key used across app (email)
            # Keep the raw ID token around (not just its decoded claims) so
            # features that call out to services expecting a Google ID token
            # as a bearer credential (e.g. the BitBerry chat agent) have one
            # to send. It's short-lived (~1h, per the 'exp' claim) — routes/
            # chat.py checks that and silently re-runs this OAuth flow via
            # prompt=none when it's expired, instead of storing it forever.
            session['google_id_token'] = id_token_jwt
            session['google_id_token_exp'] = idinfo.get('exp')
            session['user_name'] = user_name
            session['user_picture'] = user_picture
            session['authenticated'] = True
            # A fresh sign-in always re-fetches the BitBerry-assigned agent
            # list rather than trusting whatever was cached under the old
            # token/session (assignments may have changed since last login).
            session.pop('bitberry_agents_cache', None)

            user_row = None

            # Ensure application user exists/updated
            try:
                from database import upsert_user_from_session
                user_row = upsert_user_from_session(user_email, user_name, user_picture)
            except Exception as e:
                print(f"Failed to upsert user: {e}")

            # A deactivated account may not sign in, even with a valid Google
            # token — undo the session flags set above and bounce to login.
            if user_row and user_row.get('is_active') is False:
                session.clear()
                flash('Your account has been deactivated. Contact your administrator.', 'error')
                return redirect(url_for('auth.login'))

            # If an admin pinned this store manager to a store, lock them to it
            # (skips the picker; they can't see other stores).
            try:
                if user_row and user_row.get('role') == 'worker' and user_row.get('location_id'):
                    from database import execute_query_one
                    loc = execute_query_one("SELECT name FROM locations WHERE id = %s", (user_row['location_id'],))
                    session['active_location_id'] = str(user_row['location_id'])
                    session['active_location_name'] = loc['name'] if loc else 'Your store'
            except Exception as e:
                print(f"Failed to pin manager location: {e}")

            # Cache user/staff identifiers for downstream writes
            if user_row:
                if user_row.get('id'):
                    session['user_uuid'] = str(user_row['id'])
                else:
                    session.pop('user_uuid', None)

                if user_row.get('staff_id'):
                    session['staff_id'] = str(user_row['staff_id'])
                else:
                    session.pop('staff_id', None)
            else:
                session.pop('user_uuid', None)
                session.pop('staff_id', None)
            
            # Log user session to database
            try:
                from database import execute_query
                execute_query("""
                    INSERT INTO user_sessions (user_email, user_name, ip_address, user_agent, is_active)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_email, user_name, request.remote_addr, request.headers.get('User-Agent'), True))
            except Exception as e:
                print(f"Failed to log user session: {e}")
            
            next_url = session.pop('post_login_next', None)
            if next_url and next_url.startswith('/'):  # only ever follow a same-site path, never an absolute/external URL
                # No "Welcome" flash here — this branch is also used by the
                # silent (prompt=none) token-refresh redirect, which should
                # be invisible to the user rather than surface a login toast.
                return redirect(next_url)
            flash(f'Welcome, {user_name}!', 'success')
            # One-time "you have AI Helpers assigned" notice on the very
            # next page render — real interactive login only (the silent
            # prompt=none reauth branch above returns before this line).
            # base.html pops this flag so it fires exactly once per login,
            # not on every subsequent page navigation this session.
            session['show_ai_helpers_login_notice'] = True
            return redirect(url_for('main.dashboard'))
            
        except ValueError as e:
            error_msg = str(e)
            if "Token used too early" in error_msg or "clock" in error_msg.lower():
                flash('Authentication failed due to clock synchronization. Please check your system time and try again.', 'error')
            else:
                flash(f'Invalid token: {error_msg}', 'error')
            return redirect(url_for('auth.login'))
            
    except Exception as e:
        flash(f'Authentication error: {str(e)}', 'error')
        return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    """Logout user"""
    # Mark user session as inactive
    if session.get('user_id'):
        try:
            from database import execute_query
            execute_query("""
                UPDATE user_sessions 
                SET is_active = FALSE, logout_time = CURRENT_TIMESTAMP
                WHERE user_email = %s AND is_active = TRUE
            """, (session.get('user_id'),))
        except Exception as e:
            print(f"Failed to update user session: {e}")
    
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))

def login_required(f):
    """Decorator to require authentication"""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            flash('Please log in to access this page.', 'warning')
            try:
                return redirect(url_for('auth.login'))
            except Exception as e:
                # Fallback if url_for fails
                return redirect('/login')

        # Catches an account deactivated mid-session — the next request after
        # an admin flips is_active off signs them out instead of letting an
        # already-authenticated session keep working.
        from security import get_or_create_current_user
        if get_or_create_current_user() is None:
            session.clear()
            flash('Your account is inactive. Contact your administrator.', 'error')
            return redirect(url_for('auth.login'))

        return f(*args, **kwargs)
    return decorated_function
