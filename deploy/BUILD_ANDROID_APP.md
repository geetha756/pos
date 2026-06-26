# Building the installable Android app (.apk) — no Play Store

The Android app is a **TWA** (Trusted Web Activity): a thin native shell that
opens your live PWA fullscreen. It's a real `.apk` you install directly on each
manager's phone. It still updates instantly — because it loads your server, you
never rebuild the APK for content/feature changes (only for icon/name changes).

> Prerequisite: the app must already be live and reachable at
> `https://portal.YOURDOMAIN.com` (see DEPLOYMENT.md). The APK points at that URL.

---

## Option A — PWABuilder (easiest, no Android tools needed) ✅ recommended

1. Go to **https://www.pwabuilder.com**.
2. Enter `https://portal.YOURDOMAIN.com` and click **Start**. It reads your
   manifest (already set up) and scores the PWA.
3. Click **Package For Stores → Android**.
4. Choose **"Signed APK"** (for direct install) rather than the Play Store AAB.
   - Set **Package ID** to e.g. `com.sipnsnack.portal` (remember this exact value).
   - Let it **generate a new signing key** and **download the key + the
     `assetlinks.json` it shows** — keep both safe.
5. Download the zip. Inside is the **`.apk`** and the signing info, including the
   **SHA-256 fingerprint** of your key.
6. Finish the "remove URL bar" step (see **Digital Asset Links** below).
7. Send the `.apk` to each phone (email / USB / a download link) and install it.

## Option B — Bubblewrap CLI (if you prefer the command line)

Needs Node.js + JDK 17. On your dev machine or server:
```bash
npm install -g @bubblewrap/cli
bubblewrap init --manifest https://portal.YOURDOMAIN.com/manifest.webmanifest
# answer prompts; set applicationId to com.sipnsnack.portal
bubblewrap build          # produces app-release-signed.apk + signing keystore
# Get the fingerprint for assetlinks:
bubblewrap fingerprint    # prints the SHA-256
```
The generated `.apk` is what you install on phones.

---

## Digital Asset Links (removes the browser URL bar)
A TWA shows a small URL bar **until** the website confirms it owns the app. This
app serves that confirmation at `/.well-known/assetlinks.json` from two env vars.
After you build the APK and have its package id + SHA-256 fingerprint, set on the
**server** `.env`:
```
ANDROID_PACKAGE_NAME=com.sipnsnack.portal
ANDROID_CERT_FINGERPRINTS=AA:BB:CC:...:99   # SHA-256 from the signing key (comma-separate if several)
```
Then `sudo systemctl restart sipnsnack`. Verify:
```
curl https://portal.YOURDOMAIN.com/.well-known/assetlinks.json
```
It should list your package + fingerprint. Reinstall the APK once and the URL bar
is gone — it now looks fully native.

---

## Installing on a manager's phone (sideload, no Play Store)
1. Send them the `.apk`.
2. On the phone, open it; Android will ask to **allow installing from this
   source** — approve it for the app you're installing from (e.g. Files/Chrome).
3. Install. The Sip & Snack icon appears; it opens fullscreen.

## When you DO need to rebuild the APK
Only for: app **name**, **icon**, **package id**, or **start URL** changes.
Everything else (features, pages, bug fixes, roles) updates automatically from the
server with no new APK.
