"""Production WSGI entrypoint.

Run with a production server instead of the Flask dev server, e.g.:

    gunicorn --workers 3 --bind 127.0.0.1:5000 wsgi:app

Cloudflare Tunnel (cloudflared) then forwards your public HTTPS domain to
this local 127.0.0.1:5000 — see deploy/DEPLOYMENT.md.
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
