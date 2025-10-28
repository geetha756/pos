from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from google.auth.transport import requests
from google.oauth2 import id_token
import requests as req
import os
import json

auth_bp = Blueprint('auth', __name__)

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://127.0.0.1:5000/auth/callback')

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

@auth_bp.route('/auth/callback')
def google_callback():
    """Handle Google OAuth callback"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
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
            idinfo = id_token.verify_oauth2_token(
                id_token_jwt, 
                requests.Request(), 
                GOOGLE_CLIENT_ID
            )
            
            # Extract user information
            user_email = idinfo.get('email')
            user_name = idinfo.get('name')
            user_picture = idinfo.get('picture')
            
            # Validate organization - check if email ends with @sn15.com, @sn15.org, or @sipnsnack.com (for testing)
            if not (user_email.endswith('@sn15.ai') or user_email.endswith('@sn15.com') or user_email.endswith('@sipnsnack.com')):
                flash('Access denied. This application is restricted to SN15 organization members only. Please use an SN15 email address to sign in.', 'error')
                return redirect(url_for('auth.login'))
            
            # Store user information in session
            session['user_id'] = user_email
            session['user_name'] = user_name
            session['user_picture'] = user_picture
            session['authenticated'] = True

            # Ensure application user exists/updated
            try:
                from database import upsert_user_from_session
                upsert_user_from_session(user_email, user_name, user_picture)
            except Exception as e:
                print(f"Failed to upsert user: {e}")
            
            # Log user session to database
            try:
                from database import execute_query
                execute_query("""
                    INSERT INTO user_sessions (user_email, user_name, ip_address, user_agent, is_active)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_email, user_name, request.remote_addr, request.headers.get('User-Agent'), True))
            except Exception as e:
                print(f"Failed to log user session: {e}")
            
            flash(f'Welcome, {user_name}!', 'success')
            return redirect(url_for('main.dashboard'))
            
        except ValueError as e:
            flash(f'Invalid token: {str(e)}', 'error')
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
        return f(*args, **kwargs)
    return decorated_function
