"""
Mints a valid Flask session cookie for E2E testing without going through the
real Google OAuth flow (which needs a real Google account + org domain and
can't be automated headlessly).

Uses the *same* SECRET_KEY the running dev server loads from .env, and the
exact same session interface Flask itself uses to sign cookies, so the
cookie this prints is indistinguishable from one produced by a real login.

Usage: python mint_session_cookie.py <email> [full_name]
Prints: <cookie_name>\t<cookie_value>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv('.env')

from flask import Flask, Response, session

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = __import__('datetime').timedelta(days=30)

email = sys.argv[1] if len(sys.argv) > 1 else 'deepthi@sn15.ai'
full_name = sys.argv[2] if len(sys.argv) > 2 else 'Deepthi kommuri'

with app.test_request_context():
    session.permanent = True
    session['authenticated'] = True
    session['user_id'] = email
    session['user_name'] = full_name
    session['user_picture'] = None

    resp = Response()
    app.session_interface.save_session(app, session, resp)
    set_cookie = resp.headers.get('Set-Cookie')

# Set-Cookie: session=<value>; HttpOnly; Path=/; SameSite=Lax; Expires=...
cookie_name, rest = set_cookie.split('=', 1)
cookie_value = rest.split(';', 1)[0]
print(f'{cookie_name}\t{cookie_value}')
