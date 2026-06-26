# Deploying Sip & Snack Portal to your server (remote access for store managers)

This guide takes the app from your dev PC to your always-on server, reachable
from **any network** over HTTPS via **Cloudflare Tunnel**, so store managers can
install it on a phone/tablet and place orders that reach the central database.

```
 Store manager's phone (any network)
        │  https://portal.YOURDOMAIN.com   (installed PWA)
        ▼
   Cloudflare edge  ──► Cloudflare Tunnel (cloudflared on your server)
        │  http://127.0.0.1:5000 (local, private)
        ▼
   gunicorn (Flask app)  ──►  PostgreSQL (same server, never exposed)
```

Only `cloudflared` reaches the internet. The app and database stay private on
the server — no router ports opened, no public DB.

---

## 0. One-time: pick your subdomain
Choose something like `portal.YOURDOMAIN.com`. The domain must be on Cloudflare
(add it as a site in your Cloudflare dashboard if it isn't already). Replace
`portal.YOURDOMAIN.com` everywhere below with your real value.

## 1. Get the code on the server
```bash
sudo mkdir -p /opt/sip-n-snack-portal
sudo chown $USER:$USER /opt/sip-n-snack-portal
git clone <your-repo-url> /opt/sip-n-snack-portal   # or rsync/scp the project
cd /opt/sip-n-snack-portal
```

## 2. PostgreSQL (create DB + dedicated user, load schema)
Run as the postgres superuser (production uses a real password, not the dev
socket trick):
```bash
sudo -u postgres psql -c "CREATE DATABASE sipnsnack;"
sudo -u postgres psql -c "CREATE USER sipnsnack_user WITH PASSWORD 'STRONG_DB_PASSWORD';"
sudo -u postgres psql -d sipnsnack -c "GRANT ALL PRIVILEGES ON DATABASE sipnsnack TO sipnsnack_user;"
sudo -u postgres psql -d sipnsnack -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
# Load the schema (the full file works here because you ARE superuser):
sudo -u postgres psql -d sipnsnack -f database_setup.sql
# Make sure the app user owns the objects it needs:
sudo -u postgres psql -d sipnsnack -c "GRANT ALL ON ALL TABLES IN SCHEMA public TO sipnsnack_user; GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO sipnsnack_user;"
```

## 3. Python environment
```bash
cd /opt/sip-n-snack-portal
python3 -m venv venv
./venv/bin/pip install -r requirements.txt   # includes gunicorn
```

## 4. Production .env
```bash
cp .env.production.example .env
# Edit .env and set: SECRET_KEY (random), DATABASE_URL (the password above),
# GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI=https://portal.YOURDOMAIN.com/auth/callback,
# ADMIN_EMAILS. Generate a secret:
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## 5. Run the app as a service (gunicorn)
```bash
# Create a service user (optional but cleaner):
sudo useradd --system --no-create-home sipnsnack || true
sudo chown -R sipnsnack:sipnsnack /opt/sip-n-snack-portal
sudo cp deploy/sipnsnack.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sipnsnack
systemctl status sipnsnack          # should be active (running)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/   # expect 302
```

## 6. Cloudflare Tunnel (public HTTPS, no port forwarding)
```bash
# Install cloudflared (Debian/Ubuntu):
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o cloudflared.deb
sudo dpkg -i cloudflared.deb

cloudflared tunnel login                       # opens a browser; pick your domain
cloudflared tunnel create sipnsnack            # note the UUID + credentials .json path
cloudflared tunnel route dns sipnsnack portal.YOURDOMAIN.com

# Configure: copy deploy/cloudflared-config.yml to /etc/cloudflared/config.yml
sudo mkdir -p /etc/cloudflared
sudo cp deploy/cloudflared-config.yml /etc/cloudflared/config.yml
sudo nano /etc/cloudflared/config.yml          # fill in UUID, credentials-file, hostname

# Run it as a service:
sudo cloudflared service install                # OR use deploy/cloudflared.service
sudo systemctl enable --now cloudflared
```
Now `https://portal.YOURDOMAIN.com` should load the login page.

## 7. Update Google OAuth for the real domain
In Google Cloud Console → your OAuth client (sip-n-snack-web):
- **Authorized JavaScript origins:** add `https://portal.YOURDOMAIN.com`
- **Authorized redirect URIs:** add `https://portal.YOURDOMAIN.com/auth/callback`
(Keep the localhost ones for dev.) This must match `GOOGLE_REDIRECT_URI` in `.env`.

Also add each store manager's Google account under **Test users** (or publish the
OAuth consent screen so any Google account can sign in).

## 8. Install on the store manager's phone
1. Open `https://portal.YOURDOMAIN.com` in Chrome (Android) / Safari (iOS).
2. Sign in with Google.
3. Browser menu → **Add to Home Screen / Install app**.
4. It launches fullscreen like a native app and works from any network.

---

## Redeploying after code changes
```bash
cd /opt/sip-n-snack-portal && git pull
./venv/bin/pip install -r requirements.txt
sudo systemctl restart sipnsnack
```

## Notes & gotchas
- **HTTPS is required** for the PWA install, the service worker, and Google
  login. Cloudflare Tunnel provides it automatically — don't use a bare IP.
- The app already trusts Cloudflare's `X-Forwarded-Proto` (via ProxyFix), so it
  knows it's on HTTPS, and cookies use `Secure` + `SameSite=Lax`.
- The database is never exposed to the internet; only the app connects to it
  locally. Keep it that way.
- Multiple store locations all point at this one server/DB, so everyone shares
  live data. To tie a manager to a specific store later, we can scope their
  views by location — ask when you're ready.
- Security hardening worth doing before wide rollout: add an OAuth `state`
  parameter (CSRF) to the login flow, and rotate `SECRET_KEY`/DB password.
```
